from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from hashlib import sha256
import sqlite3
import json
import unittest

from anka_canonical.writer import CanonicalWriter,ExactReleaseAdmissionPolicy,CanonicalCommitUncertain,CanonicalOrderingError,CanonicalAdmissionRejected,CanonicalIntegrityError,CanonicalWriterFenced
from anka_contracts.canonical import CanonicalCandidate
from anka_contracts.evidence import EvidencePointer
from anka_contracts.protocol import CandidateCanonicalBatch,DecoderCheckpointRef,WireEnvelopeRef
from anka_live_state.projector import StateProjector,LiveStateProjectionError

ADAPTER='adapter-test-m6-r1';BUILD='Dofus TEST-M6';CONN='conn-test-1';ACCOUNT='acct-cra';CLIENT='client-cra'

def evidence(tag:str)->EvidencePointer:
    digest=sha256(tag.encode()).hexdigest()
    return EvidencePointer('evidence-'+digest[:32],'OBSERVED_EXTERNAL','anka_protocol','test-selector:'+digest,digest,'M6_TEST')

def candidate(tag:str,kind:str,payload:dict[str,object],*,fight_epoch=None,turn_epoch=None,world_epoch=None)->CanonicalCandidate:
    digest=sha256(tag.encode()).hexdigest()[:32]
    return CanonicalCandidate('candidate-'+digest,kind,ACCOUNT,CLIENT,(evidence(tag),),tuple((k,str(v).lower() if isinstance(v,bool) else str(v)) for k,v in payload.items()),world_epoch,fight_epoch,turn_epoch)

def batch(n:int,*candidates,health='SEMANTIC_CANDIDATES',batch_id=None,source_seq=None)->CandidateCanonicalBatch:
    seq=n if source_seq is None else source_seq
    ref=WireEnvelopeRef('capture-m6',CONN,1,seq,'server_to_client','COMPLETE',sha256(f'payload-{seq}'.encode()).hexdigest())
    cp=DecoderCheckpointRef(ADAPTER,BUILD,CONN,1,n,sha256(f'context-{n}'.encode()).hexdigest())
    return CandidateCanonicalBatch(batch_id or f'batch-m6-{n}',ADAPTER,BUILD,CONN,1,(ref,),tuple(candidates),health,cp)

def fight_bootstrap(n=1):
    return batch(n,
        candidate(f'{n}-fight','FIGHT_STARTED',{'fight_id':'fight-1','map_id':200},fight_epoch=1),
        candidate(f'{n}-actor','ACTOR_SEEN',{'actor_id':41},fight_epoch=1),
        candidate(f'{n}-ap','ACTOR_RESOURCE_ABSOLUTE',{'actor_id':41,'resource':'AP','value':11},fight_epoch=1),
        candidate(f'{n}-mp','ACTOR_RESOURCE_ABSOLUTE',{'actor_id':41,'resource':'MP','value':6},fight_epoch=1),
    )

class Base(unittest.TestCase):
    def setUp(self):self.tmp=TemporaryDirectory();self.path=Path(self.tmp.name)/'canonical.sqlite';self.policy=ExactReleaseAdmissionPolicy(((ADAPTER,BUILD),));self.projector=StateProjector()
    def tearDown(self):self.tmp.cleanup()
    def writer(self,**kw):return CanonicalWriter(self.path,projector=self.projector,admission_policy=self.policy,**kw)

class TestM6Durability(Base):
    def test_commit_assigns_durable_cursors_and_projection_atomically(self):
        with self.writer() as w:
            r=w.commit_candidate_batch(fight_bootstrap())
            self.assertEqual((r.status,r.event_count,r.first_cursor,r.last_cursor),('COMMITTED',4,1,4))
            self.assertEqual(w.current_cursor(),4);self.assertEqual(w.current_cursor(ACCOUNT),4)
            snap=w.snapshot(ACCOUNT);self.assertEqual((snap.canonical_cursor,snap.fight_id.value,snap.fight_map.value),(4,'fight-1',200))
            actor=snap.actors[0];self.assertEqual((actor.ap.value,actor.mp.value),(11,6))
            self.assertEqual(w.audit()['events'],4)

    def test_exact_duplicate_is_idempotent(self):
        b=fight_bootstrap()
        with self.writer() as w:
            w.commit_candidate_batch(b);r=w.commit_candidate_batch(b)
            self.assertEqual(r.status,'IDEMPOTENT_DUPLICATE');self.assertFalse(r.committed);self.assertEqual(w.current_cursor(),4)

    def test_same_source_cannot_be_relabelled(self):
        b=fight_bootstrap();relabeled=replace(b,batch_id='batch-m6-relabeled')
        with self.writer() as w:
            w.commit_candidate_batch(b)
            with self.assertRaisesRegex(CanonicalOrderingError,'SOURCE_RELABELED'):w.commit_candidate_batch(relabeled)

    def test_same_batch_id_with_changed_semantics_conflicts(self):
        b=fight_bootstrap();changed=replace(b,candidates=b.candidates[:-1]+(candidate('changed','ACTOR_RESOURCE_ABSOLUTE',{'actor_id':41,'resource':'MP','value':5},fight_epoch=1),))
        with self.writer() as w:
            w.commit_candidate_batch(b)
            with self.assertRaisesRegex(CanonicalOrderingError,'BATCH_ID_CONFLICT'):w.commit_candidate_batch(changed)

    def test_precommit_crash_cuts_leave_no_partial_truth(self):
        for stage in ('before_begin','after_begin','after_events','after_snapshot','before_commit'):
            with self.subTest(stage=stage):
                p=Path(self.tmp.name)/f'{stage}.sqlite'
                with CanonicalWriter(p,projector=self.projector,admission_policy=self.policy) as w:
                    with self.assertRaises(Exception):w.commit_candidate_batch(fight_bootstrap(),failure_injection=stage)
                    self.assertEqual(w.current_cursor(),0);self.assertIsNone(w.snapshot(ACCOUNT));self.assertEqual(w.audit()['batches'],0)

    def test_commit_ack_uncertainty_fences_writer_and_reopen_recovers_durable_truth(self):
        b=fight_bootstrap();w=self.writer()
        try:
            with self.assertRaises(CanonicalCommitUncertain) as ctx:w.commit_candidate_batch(b,failure_injection='commit_ack_lost')
            self.assertEqual(ctx.exception.receipt.status,'COMMIT_UNCERTAIN');self.assertEqual(w.current_cursor(),4)
            self.assertEqual(w.runtime_status()['write_health'],'FENCED')
            with self.assertRaises(CanonicalWriterFenced):w.commit_candidate_batch(batch(2, health='OPAQUE_CERTIFIED_ZERO_SEMANTIC'))
        finally:w.close()
        with self.writer() as recovered:
            self.assertEqual(recovered.audit()['events'],4)
            self.assertEqual(recovered.commit_candidate_batch(b).status,'IDEMPOTENT_DUPLICATE')

    def test_after_commit_before_publish_is_same_uncertain_fence(self):
        w=self.writer()
        try:
            with self.assertRaises(CanonicalCommitUncertain):w.commit_candidate_batch(fight_bootstrap(),failure_injection='after_commit_before_publish')
            self.assertEqual(w.current_cursor(),4);self.assertEqual(w.runtime_status()['write_health'],'FENCED')
        finally:w.close()
        with self.writer() as r:self.assertEqual(r.snapshot(ACCOUNT).canonical_cursor,4)

    def test_projection_failure_rolls_back_events_and_batch_receipt(self):
        bad=batch(1,candidate('bad-ap','ACTOR_RESOURCE_ABSOLUTE',{'actor_id':99,'resource':'AP','value':10},fight_epoch=1))
        with self.writer() as w:
            with self.assertRaises(LiveStateProjectionError):w.commit_candidate_batch(bad)
            self.assertEqual(w.current_cursor(),0);self.assertEqual(w.audit()['batches'],0)

    def test_unsafe_protocol_health_is_rejected_before_sqlite_mutation(self):
        b=batch(1,health='UNKNOWN_CRITICAL')
        with self.writer() as w:
            with self.assertRaises(CanonicalAdmissionRejected):w.commit_candidate_batch(b)
            self.assertEqual(w.current_cursor(),0)

    def test_certified_zero_semantic_batch_advances_decoder_linkage_not_state_cursor(self):
        b=batch(1,health='OPAQUE_CERTIFIED_ZERO_SEMANTIC')
        with self.writer() as w:
            r=w.commit_candidate_batch(b);self.assertEqual((r.event_count,r.last_cursor),(0,0));self.assertEqual(w.current_cursor(),0)
            self.assertEqual(w.audit()['batches'],1);self.assertIsNone(w.snapshot(ACCOUNT))

    def test_restart_replay_reconstructs_same_snapshot(self):
        with self.writer() as w:w.commit_candidate_batch(fight_bootstrap());expected=w.snapshot(ACCOUNT).to_dict()
        with self.writer() as w:self.assertEqual(w.snapshot(ACCOUNT).to_dict(),expected);self.assertEqual(w.audit()['events'],4)

    def test_event_tampering_is_detected_on_reopen(self):
        with self.writer() as w:w.commit_candidate_batch(fight_bootstrap())
        db=sqlite3.connect(self.path);db.execute("UPDATE canonical_events SET event_json='{}' WHERE cursor=1");db.commit();db.close()
        with self.assertRaises(CanonicalIntegrityError):self.writer()

    def test_runtime_snapshot_reader_rejects_semantically_rewritten_row_even_with_matching_storage_hash(self):
        with self.writer() as w:
            w.commit_candidate_batch(fight_bootstrap())
            raw=w.db.execute('SELECT snapshot_json FROM canonical_snapshots WHERE account_id=?',(ACCOUNT,)).fetchone()[0]
            obj=json.loads(raw);obj['actors'][0]['ap']['value']=99
            altered=json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)
            storage_hash=sha256(altered.encode()).hexdigest()
            w.db.execute('UPDATE canonical_snapshots SET snapshot_json=?,snapshot_sha256=? WHERE account_id=?',
                         (altered,storage_hash,ACCOUNT))
            with self.assertRaisesRegex(CanonicalIntegrityError,'CANONICAL_SNAPSHOT_SEMANTIC_HASH_MISMATCH'):
                w.snapshot(ACCOUNT)

    def test_events_after_is_ordered_committed_only(self):
        with self.writer() as w:
            w.commit_candidate_batch(fight_bootstrap());out=w.events_after(1,10)
            self.assertEqual([e.canonical_cursor for e in out.events],[2,3,4]);self.assertEqual(out.through_cursor,4)

class TestM7StateSemantics(Base):
    def test_missing_resources_never_become_zero(self):
        b=batch(1,candidate('fight','FIGHT_STARTED',{'fight_id':'fight-1'},fight_epoch=1),candidate('actor','ACTOR_SEEN',{'actor_id':41},fight_epoch=1))
        with self.writer() as w:
            w.commit_candidate_batch(b);a=w.snapshot(ACCOUNT).actors[0]
            self.assertEqual(a.ap.status,'UNKNOWN');self.assertIsNone(a.ap.value);self.assertEqual(a.mp.status,'UNKNOWN');self.assertIsNone(a.mp.value)

    def test_valid_same_fight_resource_before_turn_start_is_not_false_staled(self):
        with self.writer() as w:
            w.commit_candidate_batch(fight_bootstrap())
            w.commit_candidate_batch(batch(2,candidate('turn','TURN_STARTED',{'actor_id':41},fight_epoch=1,turn_epoch=1)))
            a=w.snapshot(ACCOUNT).actors[0];self.assertEqual((a.ap.status,a.ap.value,a.mp.status,a.mp.value),('KNOWN',11,'KNOWN',6))

    def test_turn_end_stales_turn_scoped_resources_until_new_absolute_evidence(self):
        with self.writer() as w:
            w.commit_candidate_batch(fight_bootstrap());w.commit_candidate_batch(batch(2,candidate('turn1','TURN_STARTED',{'actor_id':41},fight_epoch=1,turn_epoch=1)))
            w.commit_candidate_batch(batch(3,candidate('turnend','TURN_ENDED',{'actor_id':41},fight_epoch=1,turn_epoch=1)))
            a=w.snapshot(ACCOUNT).actors[0];self.assertEqual((a.ap.status,a.mp.status),('STALE','STALE'))
            w.commit_candidate_batch(batch(4,candidate('ap2','ACTOR_RESOURCE_ABSOLUTE',{'actor_id':41,'resource':'AP','value':12},fight_epoch=1,turn_epoch=2)))
            w.commit_candidate_batch(batch(5,candidate('turn2','TURN_STARTED',{'actor_id':41},fight_epoch=1,turn_epoch=2)))
            a=w.snapshot(ACCOUNT).actors[0];self.assertEqual((a.ap.status,a.ap.value),('KNOWN',12));self.assertEqual(a.mp.status,'STALE')

    def test_ready_does_not_leak_across_fight_epoch(self):
        with self.writer() as w:
            w.commit_candidate_batch(fight_bootstrap());w.commit_candidate_batch(batch(2,candidate('ready','READY_OBSERVED',{'actor_id':41,'ready':True},fight_epoch=1)))
            self.assertTrue(w.snapshot(ACCOUNT).actors[0].ready.value)
            w.commit_candidate_batch(batch(3,candidate('end','FIGHT_ENDED',{},fight_epoch=1)))
            w.commit_candidate_batch(batch(4,candidate('fight2','FIGHT_STARTED',{'fight_id':'fight-2'},fight_epoch=2),candidate('actor2','ACTOR_SEEN',{'actor_id':41},fight_epoch=2)))
            self.assertEqual(w.snapshot(ACCOUNT).actors[0].ready.status,'UNKNOWN')

    def test_world_and_fight_geometry_are_separate_and_reentry_clears_fight_overlay(self):
        with self.writer() as w:
            w.commit_candidate_batch(batch(1,candidate('world','WORLD_MAP_OBSERVED',{'map_id':100},world_epoch=1)))
            w.commit_candidate_batch(fight_bootstrap(2));s=w.snapshot(ACCOUNT);self.assertEqual((s.world_map.value,s.fight_map.value),(100,200))
            w.commit_candidate_batch(batch(3,candidate('end','FIGHT_ENDED',{},fight_epoch=1)))
            w.commit_candidate_batch(batch(4,candidate('reentry','WORLD_REENTRY',{'map_id':101},world_epoch=2)))
            s=w.snapshot(ACCOUNT);self.assertEqual(s.world_map.value,101);self.assertEqual(s.fight_map.status,'UNKNOWN');self.assertEqual(s.actors,())

    def test_reordered_or_duplicate_committed_cursor_is_rejected(self):
        # Use durable events from a real commit, then try to project an old cursor again.
        with self.writer() as w:
            w.commit_candidate_batch(fight_bootstrap());s=w.snapshot(ACCOUNT);old=w.events_after(0,1).events[0]
            with self.assertRaisesRegex(LiveStateProjectionError,'REORDER_OR_DUPLICATE'):self.projector.prepare(s,(old,))

    def test_snapshot_semantic_hash_is_deterministic(self):
        p2=Path(self.tmp.name)/'second.sqlite';b=fight_bootstrap()
        with self.writer() as w:w.commit_candidate_batch(b);h1=w.snapshot(ACCOUNT).semantic_sha256
        with CanonicalWriter(p2,projector=StateProjector(),admission_policy=self.policy) as w:w.commit_candidate_batch(b);h2=w.snapshot(ACCOUNT).semantic_sha256
        self.assertEqual(h1,h2)

if __name__=='__main__':unittest.main()
