"""P55: synthetic Canonical journal batch atomicity + commit-uncertainty fencing."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from anka_canonical.journal import (
    SQLiteFixtureJournal,
    JournalError,
    JournalOrderingError,
    JournalPersistenceError,
    JournalUnhealthyError,
)
from anka_contracts.state import OfflineStateEvent
from anka_live_state.reducer import apply_offline_event, StateTransitionError


def ev(seq:int, kind:str='FIGHT_STARTED', *, session:str='s1', account:str='cra', gen:int=1,
       fight:str='f1', actor:int|None=None, **kwargs) -> OfflineStateEvent:
    return OfflineStateEvent(f'e-{session}-{seq}', session, account, gen, fight, seq, kind,
                             actor_id=actor, **kwargs)


def valid_batch() -> tuple[OfflineStateEvent,...]:
    return (
        ev(1),
        ev(2,'ACTOR_SEEN',actor=41),
        ev(3,'ACTOR_RESOURCE_SET',actor=41,resource='AP',value=11),
        ev(4,'ACTOR_POSITION_SET',actor=41,value=300),
    )


class P55TransactionalBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'journal.sqlite3'

    def tearDown(self):
        self.tmp.cleanup()

    def journal(self):
        return SQLiteFixtureJournal(self.path,reducer=apply_offline_event)

    def test_batch_commits_all_events_and_final_projection_atomically(self):
        with self.journal() as j:
            result=j.append_fixture_batch(valid_batch())
            self.assertEqual((result['status'],result['revision'],result['batch_size']),
                             ('COMMITTED_SIMULATED',4,4))
            self.assertEqual(j.audit()['events'],4)
            state=j.snapshot('s1')
            self.assertEqual((state['revision'],state['actors']['41']['AP'],state['actors']['41']['cell_id']),
                             (4,11,300))
            self.assertFalse(state['actionable'])

    def test_reducer_failure_in_later_event_persists_nothing(self):
        batch=(ev(1),ev(2,'ACTOR_HP_SET',actor=99,value=10,maximum=20))
        with self.journal() as j:
            with self.assertRaises(StateTransitionError):j.append_fixture_batch(batch)
            self.assertEqual(j.audit()['events'],0)
            self.assertIsNone(j.snapshot('s1'))
            self.assertTrue(j.is_write_healthy())

    def test_after_reduction_fault_persists_nothing_and_writer_reusable(self):
        with self.journal() as j:
            with self.assertRaisesRegex(JournalError,'AFTER_REDUCTION'):
                j.append_fixture_batch(valid_batch(),failure_injection='after_reduction')
            self.assertEqual(j.audit()['events'],0)
            self.assertTrue(j.is_write_healthy())
            self.assertEqual(j.append_fixture_batch(valid_batch())['revision'],4)

    def test_after_insert_fault_rolls_back_entire_batch(self):
        with self.journal() as j:
            with self.assertRaisesRegex(JournalError,'BEFORE_PROJECTION'):
                j.append_fixture_batch(valid_batch(),failure_injection='after_insert')
            self.assertEqual(j.audit()['events'],0)
            self.assertIsNone(j.snapshot('s1'))
            self.assertTrue(j.is_write_healthy())

    def test_after_projection_fault_rolls_back_events_and_projection(self):
        with self.journal() as j:
            with self.assertRaisesRegex(JournalError,'BEFORE_COMMIT'):
                j.append_fixture_batch(valid_batch(),failure_injection='after_projection')
            self.assertEqual(j.audit()['events'],0)
            self.assertIsNone(j.snapshot('s1'))
            self.assertTrue(j.is_write_healthy())

    def test_commit_ack_loss_fences_writer_instead_of_guessing(self):
        with self.journal() as j:
            with self.assertRaises(JournalPersistenceError) as ctx:
                j.append_fixture_batch(valid_batch(),failure_injection='commit_ack_lost')
            self.assertEqual(ctx.exception.stage,'commit')
            self.assertFalse(ctx.exception.rollback_succeeded)
            self.assertFalse(j.is_write_healthy())
            self.assertEqual(j.runtime_status()['write_health'],'FENCED')
            with self.assertRaisesRegex(JournalUnhealthyError,'FENCED'):
                j.append_fixture(ev(5,'TURN_STARTED',actor=41))
            # Reads remain possible, but cannot be used to un-fence the writer.
            self.assertEqual(j.audit()['events'],4)
            self.assertEqual(j.snapshot('s1')['revision'],4)

    def test_reopen_after_commit_ack_loss_recovers_durable_truth(self):
        j=self.journal()
        try:
            with self.assertRaises(JournalPersistenceError):
                j.append_fixture_batch(valid_batch(),failure_injection='commit_ack_lost')
        finally:
            j.close()
        with self.journal() as recovered:
            self.assertTrue(recovered.is_write_healthy())
            self.assertEqual(recovered.audit()['events'],4)
            self.assertEqual(recovered.append_fixture(ev(5,'TURN_STARTED',actor=41))['revision'],5)

    def test_rollback_failure_fences_even_before_commit(self):
        class BrokenRollback(SQLiteFixtureJournal):
            def _rollback_transaction(self):
                raise RuntimeError('rollback unavailable')
        j=BrokenRollback(self.path,reducer=apply_offline_event)
        try:
            with self.assertRaises(JournalPersistenceError) as ctx:
                j.append_fixture_batch(valid_batch(),failure_injection='after_insert')
            self.assertEqual(ctx.exception.stage,'journal')
            self.assertFalse(ctx.exception.rollback_succeeded)
            self.assertFalse(j.is_write_healthy())
        finally:
            # SQLite will roll back the uncommitted transaction on close.
            j.close()
        with self.journal() as recovered:
            self.assertEqual(recovered.audit()['events'],0)

    def test_exact_batch_replay_is_idempotent(self):
        with self.journal() as j:
            j.append_fixture_batch(valid_batch())
            result=j.append_fixture_batch(valid_batch())
            self.assertEqual(result['status'],'IDEMPOTENT_DUPLICATE')
            self.assertFalse(result['committed'])
            self.assertEqual(j.audit()['events'],4)

    def test_partial_batch_replay_is_rejected(self):
        with self.journal() as j:
            j.append_fixture(ev(1))
            with self.assertRaisesRegex(JournalOrderingError,'PARTIAL_DUPLICATE'):
                j.append_fixture_batch((ev(1),ev(2,'ACTOR_SEEN',actor=41)))
            self.assertEqual(j.audit()['events'],1)

    def test_cross_session_or_account_batch_rejected_before_transaction(self):
        cases=(
            (ev(1),ev(2,'ACTOR_SEEN',session='other',actor=41)),
            (ev(1),ev(2,'ACTOR_SEEN',account='enu',actor=41)),
            (ev(1),ev(2,'ACTOR_SEEN',gen=2,actor=41)),
        )
        with self.journal() as j:
            for batch in cases:
                with self.subTest(batch=batch[1].session_id):
                    with self.assertRaisesRegex(JournalOrderingError,'SCOPE_MISMATCH'):
                        j.append_fixture_batch(batch)
            self.assertEqual(j.audit()['events'],0)

    def test_gap_inside_batch_is_rejected(self):
        with self.journal() as j:
            with self.assertRaisesRegex(JournalOrderingError,'BATCH_SEQUENCE'):
                j.append_fixture_batch((ev(1),ev(3,'ACTOR_SEEN',actor=41)))
            self.assertEqual(j.audit()['events'],0)

    def test_duplicate_event_id_inside_batch_is_rejected(self):
        second=OfflineStateEvent('e-s1-1','s1','cra',1,'f1',2,'ACTOR_SEEN',actor_id=41)
        with self.journal() as j:
            with self.assertRaisesRegex(JournalOrderingError,'DUPLICATE_EVENT_ID'):
                j.append_fixture_batch((ev(1),second))

    def test_non_fixture_object_cannot_enter_batch(self):
        with self.journal() as j:
            with self.assertRaisesRegex(TypeError,'SYNTHETIC'):
                j.append_fixture_batch((ev(1),object()))
            self.assertEqual(j.audit()['events'],0)

    def test_batch_must_be_bounded_nonempty_sequence(self):
        with self.journal() as j:
            with self.assertRaisesRegex(JournalError,'BATCH_SIZE'):j.append_fixture_batch(())
            with self.assertRaisesRegex(TypeError,'BATCH_SEQUENCE'):j.append_fixture_batch(iter(valid_batch()))

    def test_single_append_uses_same_batch_transaction_path(self):
        with self.journal() as j:
            result=j.append_fixture(ev(1))
            self.assertEqual((result['status'],result['batch_size']),('COMMITTED_SIMULATED',1))
            self.assertEqual(j.audit()['events'],1)

    def test_runtime_status_contains_no_fixture_payload_or_identity(self):
        with self.journal() as j:
            j.append_fixture(ev(1,session='private-session',account='private-account'))
            text=__import__('json').dumps(j.runtime_status(),sort_keys=True)
            self.assertNotIn('private-session',text)
            self.assertNotIn('private-account',text)
            self.assertIn('SYNTHETIC_FIXTURE_ONLY',text)
            self.assertNotIn('LIVE_PROTOCOL',text)

    def test_concurrent_exact_batches_commit_once(self):
        batch=valid_batch()
        def worker(_):
            with self.journal() as j:
                return j.append_fixture_batch(batch)['status']
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses=sorted(pool.map(worker,range(2)))
        self.assertEqual(statuses,['COMMITTED_SIMULATED','IDEMPOTENT_DUPLICATE'])
        with self.journal() as j:self.assertEqual(j.audit()['events'],4)

    def test_read_only_journal_never_accepts_batch(self):
        with self.journal() as j:j.append_fixture_batch(valid_batch())
        with SQLiteFixtureJournal(self.path,reducer=apply_offline_event,read_only=True) as ro:
            self.assertFalse(ro.is_write_healthy())
            with self.assertRaisesRegex(JournalError,'READ_ONLY'):
                ro.append_fixture_batch((ev(5,'TURN_STARTED',actor=41),))
            self.assertEqual(ro.audit()['events'],4)


    def test_reducer_cannot_forge_revision_or_scope(self):
        def bad_reducer(prior,event):
            state=apply_offline_event(prior,event)
            state['revision']=999
            return state
        with SQLiteFixtureJournal(self.path,reducer=bad_reducer) as j:
            with self.assertRaisesRegex(JournalError,'SCOPE_OR_REVISION'):
                j.append_fixture_batch((ev(1),))
            self.assertEqual(j.audit()['events'],0)
            self.assertTrue(j.is_write_healthy())

    def test_reducer_non_mapping_projection_is_rejected_before_insert(self):
        with SQLiteFixtureJournal(self.path,reducer=lambda prior,event: None) as j:
            with self.assertRaisesRegex(JournalError,'PROJECTION_INVALID'):
                j.append_fixture_batch((ev(1),))
            self.assertEqual(j.audit()['events'],0)

    def test_invalid_fault_name_rejected_without_mutation(self):
        with self.journal() as j:
            with self.assertRaisesRegex(ValueError,'FAULT_STAGE'):
                j.append_fixture_batch(valid_batch(),failure_injection='mystery')
            self.assertEqual(j.audit()['events'],0)


if __name__=='__main__':
    unittest.main()
