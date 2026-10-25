"""P7 historical semantic mapping is deliberately non-authoritative."""
import unittest
from dataclasses import FrozenInstanceError,replace
from hashlib import sha256
from anka_contracts.protocol import WireMessage
from anka_contracts.canonical import CanonicalDraft,EvidenceRef,CanonicalAdmission
from anka_contracts.semantic import SemanticResult
from anka_protocol.adapters.historical_semantic import HistoricalContext,HistoricalSemanticAdapter
from anka_canonical.staging import CanonicalStagingGate
from anka_protocol.wire import extract_any


def vi(x):
    if x<0:x=(1<<64)+x
    out=bytearray()
    while x>=128:out.append((x&127)|128);x>>=7
    out.append(x);return bytes(out)
def n(i,x):return vi((i<<3)|0)+vi(x)
def b(i,x):return vi((i<<3)|2)+vi(len(x))+x
def wm(name,body,*,direction='server_to_client',packet=9,idx=0):
    return WireMessage(direction,name,body,packet,'example-flow',2,idx)
def row(cid,branch=1,fields=None):
    if fields is None:fields=[(1,11),(2,-2)]
    return n(2,cid)+b(branch,b''.join(n(i,x) for i,x in fields))
def jtk(actor=777,rows=None):
    if rows is None:rows=[row(1),row(23,fields=[(1,5)])]
    return b(1,b''.join(b(4,r) for r in rows))+n(2,actor)
def evidence():return EvidenceRef('Dofus 3.7.10.10','historical','jtk',1,1,sha256(b'flow').hexdigest())

class TestHistoricalP7(unittest.TestCase):
    def setUp(self):
        self.adapter=HistoricalSemanticAdapter(requested_build='Dofus 3.7.10.10')
    def test_historical_ap_mp_absolute(self):
        result=self.adapter.decode(wm('jtk',jtk()))
        self.assertEqual(result.status,'CANDIDATES_ONLY')
        self.assertEqual([(d.actor_id,d.resource,d.value) for d in result.candidates],[(777,'AP',9),(777,'MP',5)])
        self.assertTrue(all(d.authority=='HISTORICAL_CANDIDATE_ONLY' for d in result.candidates))
    def test_composition_field_seven_not_double_counted(self):
        raw=jtk(rows=[row(1,1,[(1,11),(2,-2),(7,12345)])])
        result=self.adapter.decode(wm('jtk',raw))
        # R5.198 explicitly identifies field 7 as duplicate spending metadata; do not sum it.
        self.assertEqual(result.candidates[0].value,9)
    def test_branch_three_composition(self):
        result=self.adapter.decode(wm('jtk',jtk(rows=[row(1,3,[(1,7),(7,2)])])))
        self.assertEqual(result.candidates[0].value,9)
    def test_unknown_composition_branch_quarantined(self):
        result=self.adapter.decode(wm('jtk',jtk(rows=[row(1,4)])))
        self.assertEqual(result.status,'QUARANTINED')
        self.assertEqual(result.failure_code,'CHARACTERISTIC_BRANCH_DRIFT')
    def test_two_composition_branches_quarantined(self):
        result=self.adapter.decode(wm('jtk',jtk(rows=[row(1,1)+b(3,n(1,4))])))
        self.assertEqual(result.status,'QUARANTINED')
    def test_duplicate_characteristic_blocks_entire_batch(self):
        result=self.adapter.decode(wm('jtk',jtk(rows=[row(1),row(1)])))
        self.assertEqual(result.status,'QUARANTINED')
        self.assertEqual(result.candidates,())
    def test_bad_second_row_prevents_partial_emission(self):
        result=self.adapter.decode(wm('jtk',jtk(rows=[row(1),row(23,2)])))
        self.assertEqual(result.candidates,())
    def test_truncated_protobuf_quarantined(self):
        result=self.adapter.decode(wm('jtk',b'\x0a\xff'))
        self.assertEqual(result.status,'QUARANTINED')
    def test_current_build_mismatch(self):
        r=HistoricalSemanticAdapter(requested_build='Dofus 3.7.11.11').decode(wm('jtk',jtk()))
        self.assertEqual(r.status,'BUILD_MISMATCH')
    def test_client_request_cannot_mutate_state(self):
        result=self.adapter.decode(wm('jtk',jtk(),direction='client_to_server'))
        self.assertEqual(result.status,'QUARANTINED')
    def test_unknown_wire_is_observed_not_guessed(self):
        result=self.adapter.decode(wm('emerging',n(1,500)))
        self.assertEqual(result.status,'NO_SEMANTIC_MAPPING')
    def test_hp_requires_fight_identity_context(self):
        message=wm('kqo',n(1,1000)+n(3,700))
        for context in (None,HistoricalContext(123,True,False),HistoricalContext(123,False,True)):
            self.assertEqual(self.adapter.decode(message,context=context).status,'CONTEXT_MISSING')
        found=self.adapter.decode(message,context=HistoricalContext(123,True,True))
        self.assertEqual((found.candidates[0].actor_id,found.candidates[0].value,found.candidates[0].maximum),(123,700,1000))
    def test_hp_out_of_range_quarantined(self):
        message=wm('kqo',n(1,1000)+n(3,1200))
        result=self.adapter.decode(message,context=HistoricalContext(123,True,True))
        self.assertEqual(result.status,'QUARANTINED')
    def test_missing_hp_field_quarantined(self):
        result=self.adapter.decode(wm('kqo',n(1,1000)),context=HistoricalContext(123,True,True))
        self.assertEqual(result.status,'QUARANTINED')
    def test_cooldown_empty_complete_snapshot_candidate(self):
        result=self.adapter.decode(wm('jti',n(2,123)))
        self.assertEqual(result.status,'CANDIDATES_ONLY')
        self.assertEqual(result.candidates[0].cooldowns,())
    def test_cooldown_duplicate_quarantined(self):
        body=n(2,123)+b(4,n(3,7)+n(2,2))+b(4,n(3,7)+n(2,1))
        self.assertEqual(self.adapter.decode(wm('jti',body)).status,'QUARANTINED')
    def test_cooldown_positive(self):
        body=n(2,123)+b(4,n(3,7)+n(2,2))
        d=self.adapter.decode(wm('jti',body)).candidates[0]
        self.assertEqual(d.cooldowns,((7,2),))
    def test_actor_zero_rejected(self):
        self.assertEqual(self.adapter.decode(wm('jtk',jtk(actor=0))).status,'QUARANTINED')
    def test_immutable_candidate(self):
        d=self.adapter.decode(wm('jtk',jtk())).candidates[0]
        with self.assertRaises(FrozenInstanceError):d.value=999
    def test_canonical_rejects_unplausible_ap(self):
        with self.assertRaisesRegex(ValueError,'CANONICAL_RESOURCE_INVALID'):
            CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',7,evidence(),resource='AP',value=10000)
    def test_wire_message_ordinal_strict(self):
        with self.assertRaisesRegex(ValueError,'PROTOCOL_MESSAGE_INDEX_INVALID'):
            wm('jtk',jtk()).__class__('server_to_client','jtk',b'',4,'flow',1,-1)
    def test_unchanged_canonical_type_across_wire_builds(self):
        self.assertEqual(CanonicalDraft.__module__,'anka_contracts.canonical')

class TestCanonicalStagingP7(unittest.TestCase):
    def setUp(self):
        self.adapter=HistoricalSemanticAdapter(requested_build='Dofus 3.7.10.10')
        self.gate=CanonicalStagingGate()
    def test_stage_keeps_zero_commits_even_if_caller_claims_certified(self):
        result=self.adapter.decode(wm('jtk',jtk()))
        receipt=self.gate.inspect(result,transport_complete=True,account_attested=True)
        self.assertEqual(receipt.status,'STAGED_UNCERTIFIED')
        self.assertEqual(receipt.committed_events,0)
        self.assertIsNone(receipt.live_state_revision)
        self.assertEqual(self.gate.staged_count,2)
    def test_replay_duplication_quarantined(self):
        result=self.adapter.decode(wm('jtk',jtk()))
        self.assertEqual(self.gate.inspect(result).status,'STAGED_UNCERTIFIED')
        self.assertEqual(self.gate.inspect(result).status,'QUARANTINED')
        self.assertEqual(self.gate.staged_count,2)
    def test_two_identical_messages_distinct_ordinals_preserved(self):
        for idx in (0,1):
            res=self.adapter.decode(wm('jtk',jtk(),idx=idx))
            self.assertEqual(self.gate.inspect(res).status,'STAGED_UNCERTIFIED')
        self.assertEqual(self.gate.staged_count,4)
    def test_invalid_candidate_source_rejected(self):
        r=self.adapter.decode(wm('jtk',jtk()))
        tampered=replace(r.candidates[0],evidence=replace(r.candidates[0].evidence,adapter_id='other'))
        forged=replace(r,candidates=(tampered,))
        self.assertEqual(self.gate.inspect(forged).status,'QUARANTINED')
    def test_no_candidates_quarantined(self):
        r=self.adapter.decode(wm('abc',b''))
        self.assertEqual(self.gate.inspect(r).status,'QUARANTINED')
    def test_staging_capacity_is_bounded(self):
        self.gate._research=[None]*2048
        r=self.adapter.decode(wm('jtk',jtk()))
        self.assertEqual(self.gate.inspect(r).status,'QUARANTINED')
    def test_forbid_fake_mutation_receipt(self):
        with self.assertRaises(ValueError):
            CanonicalAdmission('STAGED_UNCERTIFIED',(),(),committed_events=1)
    def test_repeated_any_message_in_frame_is_not_deduplicated(self):
        inner=b(1,b'type.ankama.com/jtk')+b(2,b'\x08\x01')
        outer=b(3,inner)+b(3,inner)
        self.assertEqual(len(extract_any(outer)),2)

if __name__=='__main__':unittest.main()
