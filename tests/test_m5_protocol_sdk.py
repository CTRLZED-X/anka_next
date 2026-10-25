from __future__ import annotations
import ast
import unittest
from pathlib import Path

from anka_contracts.protocol import AdapterReleaseDescriptor,ProtocolAdmissionDecision
from anka_contracts.wire import WireEnvelope
from anka_protocol.adapters.dofus_3_7_10_10.adapter import Historical371010Adapter,BUILD,RELEASE_ID
from anka_protocol.adapters.dofus_3_7_10_10.manifest import descriptor
from anka_protocol.certification.impact import semantic_impact_report
from anka_protocol.registry import ProtocolRegistry,ProtocolAdapterNotFound,ProtocolActivationRejected
from anka_protocol.sdk import ProtocolTransaction,OpaqueFingerprint,OpaquePolicy
from anka_protocol.upgrade import CurrentBuildIntake

ROOT=Path(__file__).resolve().parents[1]

def varint(v:int)->bytes:
    out=[]
    while v>=128:out.append((v&127)|128);v>>=7
    out.append(v);return bytes(out)

def field(n:int,value:bytes)->bytes:
    return varint((n<<3)|2)+varint(len(value))+value

def framed_any(name:str,body:bytes)->bytes:
    any_msg=field(1,b'type.ankama.com/'+name.encode())+field(2,body)
    return varint(len(any_msg))+any_msg

def env(payload:bytes,*,seq=1,connection='conn-cra-1',generation=1,continuity='COMPLETE',client='client-cra'):
    return WireEnvelope('capture-test',client,connection,'server_to_client',0,seq,'2026-10-22T00:00:00+00:00',seq,payload,
                        continuity=continuity,connection_generation=generation,source_packet_number=100,timestamp_provenance='TEST_FIXTURE')

JTK=bytes.fromhex('0a1b221110010a0d080b10feffffffffffffffff01220610170a020805108906')

class Admission:
    def __init__(self,status='COMMITTED',raise_exc=False):self.status=status;self.raise_exc=raise_exc;self.seen=[]
    def admit_candidate_batch(self,batch):
        self.seen.append(batch)
        if self.raise_exc:raise RuntimeError('boom')
        return ProtocolAdmissionDecision(self.status,10 if self.status=='COMMITTED' else None,None if self.status=='COMMITTED' else 'TEST_REJECT')

class DummyAdapter:
    def __init__(self,d): self.descriptor=d

class TestM5Registry(unittest.TestCase):
    def test_registered_candidate_cannot_auto_activate(self):
        d=AdapterReleaseDescriptor('adapter-test','9.9.9','0'*64,'1'*64,1,0,'STAGED')
        r=ProtocolRegistry();r.register(d,lambda **kw:DummyAdapter(d))
        with self.assertRaises(ProtocolAdapterNotFound):r.select_active_exact('9.9.9')
        self.assertEqual(r.descriptor('adapter-test').lifecycle,'STAGED')

    def test_promotion_is_stepwise_and_activation_is_fenced(self):
        d=AdapterReleaseDescriptor('adapter-test','9.9.9','0'*64,'1'*64,1,0,'STAGED',action_scopes=('observe',))
        r=ProtocolRegistry();r.register(d,lambda **kw:DummyAdapter(d))
        for target in ('STRUCTURALLY_VALID','REPLAY_CERTIFIED','OBSERVATION_CERTIFIED','ACTION_SCOPED_CERTIFIED'):
            r.promote('adapter-test',target,evidence_ok=True)
        with self.assertRaises(ProtocolActivationRejected):r.activate('adapter-test',physical_input_disarmed=False,unresolved_may_have_sent=False,fresh_connection_generation=True)
        with self.assertRaises(ProtocolActivationRejected):r.activate('adapter-test',physical_input_disarmed=True,unresolved_may_have_sent=True,fresh_connection_generation=True)
        with self.assertRaises(ProtocolActivationRejected):r.activate('adapter-test',physical_input_disarmed=True,unresolved_may_have_sent=False,fresh_connection_generation=False)
        r.activate('adapter-test',physical_input_disarmed=True,unresolved_may_have_sent=False,fresh_connection_generation=True)
        self.assertEqual(r.descriptor('adapter-test').lifecycle,'ACTIVE')

    def test_exact_build_only_no_nearest_version(self):
        d=AdapterReleaseDescriptor('adapter-test','9.9.9','0'*64,'1'*64,1,0,'ACTION_SCOPED_CERTIFIED')
        r=ProtocolRegistry();r.register(d,lambda **kw:DummyAdapter(d));r.activate('adapter-test',physical_input_disarmed=True,unresolved_may_have_sent=False,fresh_connection_generation=True)
        with self.assertRaises(ProtocolAdapterNotFound):r.select_active_exact('9.9.10')

class TestM5Transaction(unittest.TestCase):
    def adapter(self,opaque=None):
        return Historical371010Adapter(descriptor=descriptor(),account_id='acct-cra',client_instance_id='client-cra',connection_id='conn-cra-1',connection_generation=1,opaque_policy=opaque)

    def test_known_historical_resource_replay_proposes_stable_semantics(self):
        a=self.adapter();ad=Admission('COMMITTED');result=ProtocolTransaction(a,ad).process(env(framed_any('jtk',JTK)))
        self.assertEqual(result.status,'COMMITTED');self.assertFalse(result.rollback_performed)
        batch=result.batch;self.assertIsNotNone(batch);self.assertEqual(batch.decode_health,'SEMANTIC_CANDIDATES')
        kinds=[x.semantic_kind for x in batch.candidates];self.assertEqual(kinds,['ACTOR_RESOURCE_ABSOLUTE','ACTOR_RESOURCE_ABSOLUTE'])
        values=[dict(x.payload)['value'] for x in batch.candidates];self.assertEqual(values,['9','5'])
        self.assertTrue(all(x.account_id=='acct-cra' for x in batch.candidates))

    def test_canonical_reject_restores_decoder_context_exactly(self):
        a=self.adapter();before=a.checkpoint_runtime_context();result=ProtocolTransaction(a,Admission('REJECTED')).process(env(framed_any('jtk',JTK)))
        after=a.checkpoint_runtime_context();self.assertEqual(result.status,'ROLLED_BACK');self.assertTrue(result.rollback_performed)
        self.assertEqual((before.revision,before.digest),(after.revision,after.digest))

    def test_canonical_uncertain_restores_decoder_context_exactly(self):
        a=self.adapter();before=a.checkpoint_runtime_context();result=ProtocolTransaction(a,Admission('UNCERTAIN')).process(env(framed_any('jtk',JTK)))
        after=a.checkpoint_runtime_context();self.assertEqual(result.status,'ROLLED_BACK');self.assertEqual(before.digest,after.digest)

    def test_admission_exception_restores_decoder_context(self):
        a=self.adapter();before=a.checkpoint_runtime_context();result=ProtocolTransaction(a,Admission(raise_exc=True)).process(env(framed_any('jtk',JTK)))
        self.assertEqual(result.status,'ADMISSION_FAILED');self.assertEqual(before.digest,a.checkpoint_runtime_context().digest)

    def test_transport_gap_is_rejected_before_semantic_decoder(self):
        a=self.adapter();before=a.checkpoint_runtime_context();result=ProtocolTransaction(a,Admission()).process(env(framed_any('jtk',JTK),continuity='GAP_INSIDE'))
        self.assertEqual(result.status,'REJECTED_TRANSPORT');self.assertEqual(before.digest,a.checkpoint_runtime_context().digest)

    def test_connection_generation_mismatch_is_not_reused(self):
        a=self.adapter();result=ProtocolTransaction(a,Admission()).process(env(framed_any('jtk',JTK),generation=2))
        self.assertEqual(result.status,'REJECTED_SCOPE')

    def test_unknown_wire_fences_semantic_batch(self):
        a=self.adapter();body=b'\x08\x01';batch=a.decode_envelope(env(framed_any('zzz',body)))
        self.assertEqual(batch.decode_health,'UNKNOWN_CRITICAL');self.assertEqual(batch.candidates,());self.assertEqual(len(batch.unknown_fingerprints),1)

    def test_exact_opaque_fingerprint_is_zero_semantic_but_one_byte_change_is_unknown(self):
        body=b'\x08\x01';policy=OpaquePolicy((OpaqueFingerprint.from_body('server_to_client','zzz',body),))
        good=self.adapter(policy).decode_envelope(env(framed_any('zzz',body)))
        bad=self.adapter(policy).decode_envelope(env(framed_any('zzz',b'\x08\x02')))
        self.assertEqual(good.decode_health,'OPAQUE_CERTIFIED_ZERO_SEMANTIC');self.assertEqual(good.candidates,())
        self.assertEqual(bad.decode_health,'UNKNOWN_CRITICAL')

class TestM5UpgradeAndArchitecture(unittest.TestCase):
    def test_current_build_intake_never_self_certifies(self):
        i=CurrentBuildIntake();missing=i.assess('Dofus 9.9.9',('BUILD_FINGERPRINT',))
        self.assertEqual(missing.status,'BLOCKED_MISSING_EVIDENCE');self.assertFalse(missing.may_activate)
        all_e=('BUILD_FINGERPRINT','CAPTURE_IDENTITY','WORLD','FIGHT_ENTRY','PLACEMENT_READY','FIRST_TURN','TURN_HANDOFF','FIGHT_END_WORLD_REENTRY')
        ready=i.assess('Dofus 9.9.9',all_e);self.assertEqual(ready.status,'READY_FOR_ADAPTER_REPLAY_QUALIFICATION');self.assertFalse(ready.may_activate)

    def test_semantic_diff_identifies_safety_consumers(self):
        report=semantic_impact_report({'TURN_OWNER_OBSERVED':(('actor','1'),)},{})
        self.assertTrue(report.blocks_build);self.assertIn('TURN_OWNER_OBSERVED',report.changed_kinds)
        row=report.impacts[0];self.assertIn('anka_execution',row.consumers);self.assertIn('end_turn',row.action_scopes)

    def test_historical_release_is_replay_only(self):
        d=descriptor();self.assertEqual(d.lifecycle,'REPLAY_CERTIFIED');self.assertEqual(d.action_scopes,())
        self.assertEqual(d.observed_client_build,BUILD)

    def test_version_adapter_packages_do_not_import_other_version_packages(self):
        bad=[]
        base=ROOT/'src/anka_protocol/adapters'
        version_dirs=[p for p in base.iterdir() if p.is_dir() and p.name.startswith('dofus_')]
        for vd in version_dirs:
            for source in vd.rglob('*.py'):
                tree=ast.parse(source.read_text())
                for n in ast.walk(tree):
                    targets=[]
                    if isinstance(n,ast.Import):targets=[x.name for x in n.names]
                    elif isinstance(n,ast.ImportFrom):targets=[n.module or '']
                    for target in targets:
                        if 'anka_protocol.adapters.dofus_' in target and not target.startswith('anka_protocol.adapters.'+vd.name):bad.append((source,target))
        self.assertEqual(bad,[])

if __name__=='__main__':unittest.main()
