from __future__ import annotations
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from anka_app.adapters.protocol_canonical import CanonicalAdmissionAdapter
from anka_canonical.writer import CanonicalWriter, ExactReleaseAdmissionPolicy, CanonicalOrderingError, CanonicalIntegrityError
from anka_contracts.canonical import CanonicalCandidate
from anka_contracts.evidence import EvidencePointer
from anka_contracts.protocol import CandidateCanonicalBatch, DecoderCheckpointRef, WireEnvelopeRef, AdapterReleaseDescriptor
from anka_contracts.wire import WireEnvelope
from anka_live_state.projector import StateProjector
from anka_protocol.sdk.runtime import AdapterContextCheckpoint, ProtocolTransaction

ADAPTER='adapter-m6-integration-r1'; BUILD='Dofus M6-INTEGRATION'; CONN='conn-m6-integration'; ACCOUNT='acct-cra'; CLIENT='client-cra'

def evidence(tag):
    h=sha256(tag.encode()).hexdigest()
    return EvidencePointer('evidence-'+h[:32],'OBSERVED_EXTERNAL','anka_protocol','integration:'+h,h,'M6_M7_PROTOCOL_CANONICAL')

def cand(tag,kind,payload,*,fight_epoch=None,turn_epoch=None):
    return CanonicalCandidate('candidate-'+sha256(tag.encode()).hexdigest()[:32],kind,ACCOUNT,CLIENT,(evidence(tag),),tuple((k,str(v).lower() if isinstance(v,bool) else str(v)) for k,v in payload.items()),None,fight_epoch,turn_epoch)

def envelope(seq=1,payload=b'wire'):
    return WireEnvelope('capture-m6-integration',CLIENT,CONN,'server_to_client',0,seq,'2026-10-22T00:00:00Z',seq,payload,'COMPLETE',len(payload),1,seq,'TEST_FIXTURE')

class FakeTransactionalAdapter:
    def __init__(self, mode='good'):
        self.connection_id=CONN;self.connection_generation=1;self.revision=0;self.mode=mode
        self.descriptor=AdapterReleaseDescriptor(ADAPTER,BUILD,'0'*64,'1'*64,1,0,'REPLAY_CERTIFIED')
    def checkpoint_runtime_context(self):
        raw=f'{self.mode}:{self.revision}'
        return AdapterContextCheckpoint(ADAPTER,BUILD,CONN,1,self.revision,raw,sha256(raw.encode()).hexdigest())
    def restore_runtime_context(self,cp):
        self.revision=cp.revision
    def decode_envelope(self,env):
        self.revision+=1
        cp=DecoderCheckpointRef(ADAPTER,BUILD,CONN,1,self.revision,sha256(f'{self.mode}:{self.revision}'.encode()).hexdigest())
        ref=WireEnvelopeRef.from_envelope(env)
        if self.mode=='good':
            candidates=(cand('fight','FIGHT_STARTED',{'fight_id':'fight-1'},fight_epoch=1),cand('actor','ACTOR_SEEN',{'actor_id':41},fight_epoch=1))
            health='SEMANTIC_CANDIDATES'
        elif self.mode=='bad_projection':
            candidates=(cand('ap','ACTOR_RESOURCE_ABSOLUTE',{'actor_id':41,'resource':'AP','value':11},fight_epoch=1),)
            health='SEMANTIC_CANDIDATES'
        elif self.mode=='unmapped':
            candidates=();health='NO_SEMANTIC_MAPPING'
        elif self.mode=='framing':
            candidates=();health='FRAMING_IN_PROGRESS'
        else:
            candidates=();health='OPAQUE_CERTIFIED_ZERO_SEMANTIC'
        return CandidateCanonicalBatch('batch-'+self.mode+'-'+str(env.producer_sequence),ADAPTER,BUILD,CONN,1,(ref,),candidates,health,cp)

class InjectUncertainWriter:
    def __init__(self,writer): self.writer=writer
    def commit_candidate_batch(self,batch): return self.writer.commit_candidate_batch(batch,failure_injection='commit_ack_lost')

class TestProtocolCanonicalTransaction(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.path=Path(self.tmp.name)/'canonical.sqlite'
        self.policy=ExactReleaseAdmissionPolicy(((ADAPTER,BUILD),))
    def tearDown(self):self.tmp.cleanup()
    def writer(self):return CanonicalWriter(self.path,projector=StateProjector(),admission_policy=self.policy)

    def test_protocol_context_advances_only_after_durable_commit(self):
        with self.writer() as w:
            adapter=FakeTransactionalAdapter('good');tx=ProtocolTransaction(adapter,CanonicalAdmissionAdapter(w))
            result=tx.process(envelope())
            self.assertEqual(result.status,'COMMITTED');self.assertFalse(result.rollback_performed)
            self.assertEqual(adapter.revision,1);self.assertEqual(w.current_cursor(),2)
            self.assertEqual(w.snapshot(ACCOUNT).fight_id.value,'fight-1')

    def test_projection_rejection_rolls_decoder_context_back(self):
        with self.writer() as w:
            adapter=FakeTransactionalAdapter('bad_projection');tx=ProtocolTransaction(adapter,CanonicalAdmissionAdapter(w))
            result=tx.process(envelope())
            self.assertEqual((result.status,result.rollback_performed,adapter.revision),('ROLLED_BACK',True,0))
            self.assertEqual(result.admission.status,'REJECTED');self.assertEqual(w.current_cursor(),0)
            self.assertTrue(tx.poisoned);self.assertEqual(tx.process(envelope(2)).status,'REJECTED_POISONED')

    def test_unmapped_wire_cannot_advance_canonical_or_decoder_context(self):
        with self.writer() as w:
            adapter=FakeTransactionalAdapter('unmapped');tx=ProtocolTransaction(adapter,CanonicalAdmissionAdapter(w))
            result=tx.process(envelope())
            self.assertEqual((result.status,result.rollback_performed,adapter.revision),('ROLLED_BACK',True,0))
            self.assertEqual(result.admission.reason_code,'CANONICAL_PROTOCOL_HEALTH_UNSAFE');self.assertEqual(w.current_cursor(),0)
            self.assertTrue(tx.poisoned)

    def test_framing_progress_may_advance_checkpoint_without_semantic_cursor(self):
        with self.writer() as w:
            adapter=FakeTransactionalAdapter('framing');tx=ProtocolTransaction(adapter,CanonicalAdmissionAdapter(w))
            result=tx.process(envelope())
            self.assertEqual((result.status,adapter.revision,w.current_cursor()),('COMMITTED',1,0))
            self.assertFalse(tx.poisoned);self.assertEqual(w.audit()['batches'],1)

    def test_exact_certified_opaque_may_advance_checkpoint_without_state_cursor(self):
        with self.writer() as w:
            adapter=FakeTransactionalAdapter('opaque');tx=ProtocolTransaction(adapter,CanonicalAdmissionAdapter(w))
            result=tx.process(envelope())
            self.assertEqual((result.status,adapter.revision,w.current_cursor()),('COMMITTED',1,0))
            self.assertEqual(w.audit()['batches'],1)

    def test_commit_uncertainty_rolls_decoder_back_and_fences_writer_until_reopen(self):
        w=self.writer()
        try:
            adapter=FakeTransactionalAdapter('good');tx=ProtocolTransaction(adapter,CanonicalAdmissionAdapter(InjectUncertainWriter(w)))
            result=tx.process(envelope())
            self.assertEqual((result.status,result.rollback_performed,adapter.revision),('ROLLED_BACK',True,0))
            self.assertEqual(result.admission.status,'UNCERTAIN');self.assertEqual(w.current_cursor(),2)
            self.assertEqual(w.runtime_status()['write_health'],'FENCED');self.assertTrue(tx.poisoned)
            self.assertEqual(tx.process(envelope(2)).status,'REJECTED_POISONED')
        finally:w.close()
        with self.writer() as recovered:
            self.assertEqual(recovered.audit()['events'],2);self.assertEqual(recovered.replay(ACCOUNT).fight_id.value,'fight-1')

class TestCanonicalHardening(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.path=Path(self.tmp.name)/'canonical.sqlite';self.policy=ExactReleaseAdmissionPolicy(((ADAPTER,BUILD),))
    def tearDown(self):self.tmp.cleanup()
    def writer(self):return CanonicalWriter(self.path,projector=StateProjector(),admission_policy=self.policy)
    def _batch(self,refs,candidates):
        cp=DecoderCheckpointRef(ADAPTER,BUILD,CONN,1,1,'1'*64)
        return CandidateCanonicalBatch('batch-hardening',ADAPTER,BUILD,CONN,1,tuple(refs),tuple(candidates),'SEMANTIC_CANDIDATES',cp)

    def test_source_ref_must_match_claimed_connection_generation(self):
        ref=WireEnvelopeRef('capture-x','conn-other',1,1,'server_to_client','COMPLETE','2'*64)
        b=self._batch((ref,),(cand('fight-x','FIGHT_STARTED',{'fight_id':'fight-1'},fight_epoch=1),))
        with self.writer() as w:
            with self.assertRaisesRegex(CanonicalOrderingError,'SOURCE_SCOPE_MISMATCH'):w.commit_candidate_batch(b)

    def test_source_refs_cannot_mix_capture_session_or_direction(self):
        good=WireEnvelopeRef('capture-a',CONN,1,1,'server_to_client','COMPLETE','2'*64)
        for bad in (
            WireEnvelopeRef('capture-b',CONN,1,2,'server_to_client','COMPLETE','3'*64),
            WireEnvelopeRef('capture-a',CONN,1,2,'client_to_server','COMPLETE','4'*64),
        ):
            with self.subTest(bad=bad):
                b=self._batch((good,bad),(cand('fight-causal-'+bad.payload_sha256[:1],'FIGHT_STARTED',{'fight_id':'fight-1'},fight_epoch=1),))
                with self.writer() as w:
                    with self.assertRaisesRegex(CanonicalOrderingError,'SOURCE_CAUSAL_SCOPE_MISMATCH'):
                        w.commit_candidate_batch(b)

    def test_source_ref_sequences_must_be_unique_and_ordered(self):
        a=WireEnvelopeRef('capture-x',CONN,1,2,'server_to_client','COMPLETE','2'*64)
        b=WireEnvelopeRef('capture-x',CONN,1,1,'server_to_client','COMPLETE','3'*64)
        batch=self._batch((a,b),(cand('fight-y','FIGHT_STARTED',{'fight_id':'fight-1'},fight_epoch=1),))
        with self.writer() as w:
            with self.assertRaisesRegex(CanonicalOrderingError,'SOURCE_SEQUENCE_INVALID'):w.commit_candidate_batch(batch)

    def test_duplicate_candidate_ids_rejected_before_sqlite(self):
        ref=WireEnvelopeRef('capture-x',CONN,1,1,'server_to_client','COMPLETE','2'*64)
        c=cand('dupe','FIGHT_STARTED',{'fight_id':'fight-1'},fight_epoch=1)
        batch=self._batch((ref,),(c,c))
        with self.writer() as w:
            with self.assertRaisesRegex(CanonicalOrderingError,'CANDIDATE_ID_DUPLICATE'):w.commit_candidate_batch(batch)
            self.assertEqual(w.current_cursor(),0)

    def test_replay_api_reconstructs_exact_stored_snapshot(self):
        with self.writer() as w:
            adapter=FakeTransactionalAdapter('good');ProtocolTransaction(adapter,CanonicalAdmissionAdapter(w)).process(envelope())
            self.assertEqual(w.replay(ACCOUNT).to_dict(),w.snapshot(ACCOUNT).to_dict())

    def test_orphan_snapshot_is_detected(self):
        with self.writer() as w:
            adapter=FakeTransactionalAdapter('good');ProtocolTransaction(adapter,CanonicalAdmissionAdapter(w)).process(envelope())
        db=sqlite3.connect(self.path)
        row=db.execute('SELECT * FROM canonical_snapshots WHERE account_id=?',(ACCOUNT,)).fetchone()
        cols=[r[1] for r in db.execute('PRAGMA table_info(canonical_snapshots)')]
        changed=list(row);changed[cols.index('account_id')]='acct-orphan';db.execute('DELETE FROM canonical_snapshots')
        db.execute('INSERT INTO canonical_snapshots VALUES (?,?,?,?,?,?)',changed);db.commit();db.close()
        with self.assertRaisesRegex(CanonicalIntegrityError,'SNAPSHOT_ACCOUNT_SET_MISMATCH'):self.writer()

if __name__=='__main__': unittest.main()
