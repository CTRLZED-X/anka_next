"""P8: independent pass/fail probes for synthetic journal/reducer boundaries."""
from __future__ import annotations
import json,sqlite3, tempfile, unittest
from contextlib import closing
from pathlib import Path
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from anka_contracts.state import OfflineStateEvent
from anka_contracts.canonical import CanonicalDraft,EvidenceRef
from anka_canonical.journal import SQLiteFixtureJournal,JournalError,JournalOrderingError,JournalIntegrityError
from anka_live_state.reducer import apply_offline_event, StateTransitionError, summarize_snapshot
from anka_app.state_offline import synthetic_state_demo,audit_state_db
from hashlib import sha256


def event(seq=1,kind='FIGHT_STARTED',session='s1',fight='f1',account='cra',gen=2,actor=None,**kwargs):
    return OfflineStateEvent(f'e-{session}-{seq}',session,account,gen,fight,seq,kind,actor_id=actor,**kwargs)

class TestP8StateContracts(unittest.TestCase):
    def test_strict_event_identity(self):
        for val in ('','/escape','white space','x'*101):
            with self.assertRaisesRegex(ValueError,'IDENTITY'):event(session=val)
    def test_reject_negative_sequence_generation_bool(self):
        for kwargs in ({'seq':0},{'gen':-1},{'seq':True}):
            with self.assertRaises(ValueError):event(**kwargs)
    def test_actor_required_and_forbidden(self):
        for k in ('ACTOR_SEEN','TURN_STARTED','ACTOR_POSITION_SET'):
            with self.assertRaises(ValueError):event(2,k)
        with self.assertRaises(ValueError):event(1,'FIGHT_STARTED',actor=7)
    def test_resource_hp_and_position_ranges(self):
        for kw in ({'resource':'AP','value':-1},{'resource':'MP','value':201},{'resource':'XP','value':11},{'resource':'AP','value':True}):
            with self.assertRaises(ValueError):event(2,'ACTOR_RESOURCE_SET',actor=7,**kw)
        for kw in ({'value':40,'maximum':30},{'value':-1,'maximum':40},{'value':40,'maximum':False}):
            with self.assertRaises(ValueError):event(2,'ACTOR_HP_SET',actor=7,**kw)
        with self.assertRaises(ValueError):event(2,'ACTOR_POSITION_SET',actor=7,value=-1)
    def test_cooldown_conflicts(self):
        for cd in (((1,0),(1,2)),((1,-1),),((0,1),)):
            with self.assertRaises(ValueError):event(2,'ACTOR_COOLDOWNS_SET',actor=7,cooldowns=cd)
    def test_extra_fields_fail(self):
        with self.assertRaises(ValueError):event(2,'ACTOR_SEEN',actor=7,value=10)
        with self.assertRaises(ValueError):event(2,'TURN_STARTED',actor=7,resource='MP')
    def test_origin_unmodifiable(self):
        with self.assertRaises(TypeError):event(origin='CERTIFIED_LIVE')
        with self.assertRaises(Exception):event().__setattr__('origin','CERTIFIED_LIVE')
    def test_missing_facts_stay_unknown(self):
        state=apply_offline_event(None,event())
        state=apply_offline_event(state,event(2,'ACTOR_SEEN',actor=7))
        summary=summarize_snapshot(state)
        self.assertEqual(summary['missing_fields_by_actor']['7'],['hp','max_hp','AP','MP','cell_id'])
        self.assertFalse(summary['actionable'])
    def test_reducer_pure_and_no_authority(self):
        state=apply_offline_event(None,event())
        copy=dict(state)
        next_state=apply_offline_event(state,event(2,'ACTOR_SEEN',actor=7))
        self.assertEqual(state,copy)
        self.assertNotIn('7',state['actors'])
        self.assertFalse(next_state['actionable'])
    def test_missing_actor_turn_and_double_turn(self):
        state=apply_offline_event(None,event())
        with self.assertRaises(StateTransitionError):apply_offline_event(state,event(2,'TURN_STARTED',actor=7))
        state=apply_offline_event(state,event(2,'ACTOR_SEEN',actor=7))
        state=apply_offline_event(state,event(3,'TURN_STARTED',actor=7))
        with self.assertRaises(StateTransitionError):apply_offline_event(state,event(4,'TURN_STARTED',actor=7))
    def test_turn_end_and_fight_end_invariants(self):
        state=apply_offline_event(None,event())
        with self.assertRaises(StateTransitionError):apply_offline_event(state,event(2,'TURN_ENDED',actor=7))
        state=apply_offline_event(state,event(2,'ACTOR_SEEN',actor=7))
        state=apply_offline_event(state,event(3,'TURN_STARTED',actor=7))
        with self.assertRaises(StateTransitionError):apply_offline_event(state,event(4,'FIGHT_ENDED'))
        with self.assertRaises(StateTransitionError):apply_offline_event(state,event(4,'TURN_ENDED',actor=9))
        state=apply_offline_event(state,event(4,'TURN_ENDED',actor=7))
        state=apply_offline_event(state,event(5,'FIGHT_ENDED'))
        self.assertEqual(state['phase'],'ENDED')
        with self.assertRaises(StateTransitionError):apply_offline_event(state,event(6,'ACTOR_SEEN',actor=8))
        state=apply_offline_event(state,event(6,'FIGHT_STARTED',fight='f2'))
        self.assertEqual(state['actors'],{})
        self.assertIsNone(state['turn_owner_id'])
    def test_fight_id_and_generation_isolation(self):
        state=apply_offline_event(None,event())
        with self.assertRaises(StateTransitionError):apply_offline_event(state,event(2,'ACTOR_SEEN',fight='f2',actor=7))
        with self.assertRaises(StateTransitionError):apply_offline_event(state,event(2,'ACTOR_SEEN',gen=3,actor=7))
        with self.assertRaises(StateTransitionError):apply_offline_event(state,event(3,'ACTOR_SEEN',actor=7))
    def test_historical_draft_forbidden_as_reducer_input(self):
        ev=EvidenceRef('Dofus 3.7.10.10','historical','jtk',1,1,sha256(b'flow').hexdigest())
        draft=CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',7,ev,resource='AP',value=11)
        with self.assertRaises(TypeError):apply_offline_event(None,draft)

class TestP8Durability(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory();self.path=Path(self.dir.name)/'test.sqlite3'
    def tearDown(self):self.dir.cleanup()
    def journal(self,ro=False):return SQLiteFixtureJournal(self.path,reducer=apply_offline_event,read_only=ro)
    def test_atomic_commit_and_reopen(self):
        with self.journal() as j:
            self.assertEqual(j.append_fixture(event())['revision'],1)
            self.assertEqual(j.append_fixture(event(2,'ACTOR_SEEN',actor=7))['revision'],2)
            self.assertEqual(j.append_fixture(event(3,'ACTOR_RESOURCE_SET',actor=7,resource='AP',value=11))['revision'],3)
            self.assertEqual(j.audit()['events'],3)
        with self.journal(ro=True) as j:
            self.assertEqual(j.snapshot('s1')['actors']['7']['AP'],11)
            self.assertEqual(j.audit()['events'],3)
        self.assertEqual(audit_state_db(self.path)['audit']['status'],'PASS')
    def test_atomic_rollback_on_fault_stages(self):
        with self.journal() as j:
            for stage in ('after_insert','after_projection'):
                with self.assertRaisesRegex(JournalError,'INJECTED'):
                    j.append_fixture(event(),failure_injection=stage)
                self.assertEqual(j.audit()['events'],0)
                self.assertIsNone(j.snapshot('s1'))
            self.assertEqual(j.append_fixture(event())['revision'],1)
    def test_reopen_after_failure_and_retry(self):
        with self.journal() as j:
            j.append_fixture(event())
            with self.assertRaises(JournalError):j.append_fixture(event(2,'ACTOR_SEEN',actor=7),failure_injection='after_insert')
        with self.journal() as j:
            self.assertEqual(j.audit()['events'],1)
            self.assertEqual(j.append_fixture(event(2,'ACTOR_SEEN',actor=7))['revision'],2)
    def test_unknown_actor_rolls_back(self):
        with self.journal() as j:
            j.append_fixture(event())
            with self.assertRaises(StateTransitionError):j.append_fixture(event(2,'ACTOR_HP_SET',actor=7,value=1,maximum=2))
            self.assertEqual(j.audit()['events'],1)
    def test_exact_duplicate_idempotent(self):
        with self.journal() as j:
            j.append_fixture(event())
            self.assertFalse(j.append_fixture(event())['committed'])
            self.assertEqual(j.audit()['events'],1)
    def test_same_id_different_payload_fail(self):
        with self.journal() as j:
            j.append_fixture(event())
            with self.assertRaises(JournalOrderingError):j.append_fixture(replace(event(),fight_id='changed'))
    def test_same_revision_different_id_fail(self):
        with self.journal() as j:
            j.append_fixture(event())
            with self.assertRaises(JournalOrderingError):j.append_fixture(replace(event(),event_id='other'))
    def test_missing_revision_rejected(self):
        with self.journal() as j:
            j.append_fixture(event())
            with self.assertRaises(JournalOrderingError):j.append_fixture(event(3,'ACTOR_SEEN',actor=7))
            self.assertEqual(j.audit()['events'],1)
    def test_projection_is_not_mutable_from_caller(self):
        with self.journal() as j:
            j.append_fixture(event())
            snapshot=j.snapshot('s1');snapshot['phase']='HACKED'
            self.assertEqual(j.snapshot('s1')['phase'],'IN_FIGHT')
    def test_projection_tampering_detected_before_append(self):
        with self.journal() as j:j.append_fixture(event())
        with closing(sqlite3.connect(self.path)) as c, c:c.execute("UPDATE projections SET state_json='{}' WHERE session_id='s1'")
        with self.assertRaises(JournalIntegrityError):self.journal()
        with self.assertRaises(JournalIntegrityError):self.journal(ro=True)
    def test_event_body_tamper_replay_detected(self):
        with self.journal() as j:j.append_fixture(event())
        with closing(sqlite3.connect(self.path)) as c, c:c.execute("UPDATE events SET event_json='{}' WHERE session_id='s1'")
        with self.assertRaises(JournalIntegrityError):self.journal(ro=True)
    def test_deletion_of_first_event_detected(self):
        with self.journal() as j:
            j.append_fixture(event());j.append_fixture(event(2,'ACTOR_SEEN',actor=7))
        with closing(sqlite3.connect(self.path)) as c, c:c.execute('DELETE FROM events WHERE sequence=1')
        with self.assertRaises(JournalIntegrityError):self.journal(ro=True)
    def test_lost_last_event_detected_even_if_projection_remains(self):
        with self.journal() as j:
            j.append_fixture(event());j.append_fixture(event(2,'ACTOR_SEEN',actor=7))
        with closing(sqlite3.connect(self.path)) as c, c:c.execute('DELETE FROM events WHERE sequence=2')
        with self.assertRaises(JournalIntegrityError):self.journal(ro=True)
    def test_quarantined_p7_draft_cannot_commit(self):
        proof=EvidenceRef('Dofus 3.7.10.10','historical','jtk',1,1,sha256(b'flow').hexdigest())
        draft=CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',7,proof,resource='AP',value=11)
        with self.journal() as j:
            with self.assertRaises(TypeError):j.append_fixture(draft)
            self.assertEqual(j.audit()['events'],0)
    def test_synthetic_semantics_no_real_authority(self):
        result=synthetic_state_demo()
        self.assertEqual(result['status'],'SYNTHETIC_STATE_ONLY')
        self.assertEqual(result['commits'],7)
        self.assertEqual(result['state']['turn_owner_id'],777)
        self.assertFalse(result['state']['actionable'])
        self.assertFalse(result['physical_input_sent'])
    def test_read_only_disallows_append(self):
        with self.journal() as j:j.append_fixture(event())
        with self.journal(ro=True) as j:
            with self.assertRaises(JournalError):j.append_fixture(event(2,'ACTOR_SEEN',actor=7))
    def test_multi_session_isolation(self):
        with self.journal() as j:
            j.append_fixture(event(session='a'))
            j.append_fixture(event(session='b',account='enu'))
            self.assertEqual(j.snapshot('a')['account_id'],'cra')
            self.assertEqual(j.snapshot('b')['account_id'],'enu')
            self.assertEqual(j.audit()['sessions'],2)
    def test_unknown_schema_fails_safe(self):
        with self.journal() as j:j.append_fixture(event())
        with closing(sqlite3.connect(self.path)) as c, c:c.execute('UPDATE ledger_version SET schema=999')
        with self.assertRaises(JournalIntegrityError):self.journal(ro=True)
    def test_sequential_parallel_writers_do_not_clobber(self):
        with self.journal() as j:j.append_fixture(event())
        def attempt():
            with self.journal() as j:
                return j.append_fixture(event(2,'ACTOR_SEEN',actor=7))['status']
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:attempt(),range(2)))
        self.assertEqual(sorted(results),['COMMITTED_SIMULATED','IDEMPOTENT_DUPLICATE'])
        with self.journal() as j:self.assertEqual(j.audit()['events'],2)

if __name__=='__main__':unittest.main()
