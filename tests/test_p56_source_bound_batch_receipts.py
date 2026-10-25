"""P56: synthetic source-bound batch receipts for crash/retry-safe journal handoff."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path

from anka_canonical.journal import (
    SQLiteFixtureJournal,
    JournalError,
    JournalIntegrityError,
    JournalOrderingError,
    JournalPersistenceError,
)
from anka_contracts.state import OfflineBatchEnvelope, OfflineStateEvent
from anka_live_state.reducer import apply_offline_event


def event(seq:int, kind:str='FIGHT_STARTED', *, session='s1', account='cra', actor=None, event_id=None, **kwargs):
    return OfflineStateEvent(event_id or f'e-{session}-{seq}', session, account, 1, 'f1', seq, kind,
                             actor_id=actor, **kwargs)


def events():
    return (
        event(1),
        event(2,'ACTOR_SEEN',actor=41),
        event(3,'ACTOR_RESOURCE_SET',actor=41,resource='AP',value=11),
    )


def digest(label:str)->str:
    return sha256(label.encode('ascii')).hexdigest()


def envelope(*,batch_id='batch-1', source='packet-1', batch=None):
    return OfflineBatchEnvelope(batch_id,digest(source),events() if batch is None else tuple(batch))


class P56SourceBoundReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'journal.sqlite3'

    def tearDown(self):
        self.tmp.cleanup()

    def journal(self):
        return SQLiteFixtureJournal(self.path,reducer=apply_offline_event)

    def test_envelope_commit_binds_receipt_events_and_projection_atomically(self):
        with self.journal() as j:
            result=j.append_fixture_envelope(envelope())
            self.assertEqual((result['status'],result['revision'],result['batch_receipt']),
                             ('COMMITTED_SIMULATED',3,True))
            audit=j.audit()
            self.assertEqual((audit['events'],audit['batch_receipts']),(3,1))
            receipt=j.batch_receipt_status('batch-1')
            self.assertEqual(receipt['status'],'DURABLE_SYNTHETIC_RECEIPT')
            self.assertEqual((receipt['first_sequence'],receipt['last_sequence'],receipt['event_count']),(1,3,3))
            self.assertFalse(receipt['actionable'])

    def test_exact_receipt_replay_is_idempotent(self):
        with self.journal() as j:
            j.append_fixture_envelope(envelope())
            result=j.append_fixture_envelope(envelope())
            self.assertEqual(result['status'],'IDEMPOTENT_RECEIPT')
            self.assertFalse(result['committed'])
            self.assertEqual(j.audit()['events'],3)

    def test_commit_ack_loss_reopens_to_exact_receipt_truth(self):
        j=self.journal()
        try:
            with self.assertRaises(JournalPersistenceError):
                j.append_fixture_envelope(envelope(),failure_injection='commit_ack_lost')
            self.assertFalse(j.is_write_healthy())
        finally:
            j.close()
        with self.journal() as recovered:
            result=recovered.append_fixture_envelope(envelope())
            self.assertEqual(result['status'],'IDEMPOTENT_RECEIPT')
            self.assertEqual(recovered.audit()['batch_receipts'],1)

    def test_after_receipt_fault_rolls_back_everything(self):
        with self.journal() as j:
            with self.assertRaisesRegex(JournalError,'AFTER_RECEIPT'):
                j.append_fixture_envelope(envelope(),failure_injection='after_receipt')
            self.assertTrue(j.is_write_healthy())
            self.assertEqual(j.audit()['events'],0)
            self.assertIsNone(j.batch_receipt_status('batch-1'))

    def test_same_batch_id_cannot_change_source(self):
        with self.journal() as j:
            j.append_fixture_envelope(envelope())
            with self.assertRaisesRegex(JournalOrderingError,'RECEIPT_CONFLICT'):
                j.append_fixture_envelope(envelope(source='other-packet'))

    def test_same_batch_id_cannot_change_payload(self):
        with self.journal() as j:
            j.append_fixture_envelope(envelope())
            changed=(event(1),event(2,'ACTOR_SEEN',actor=41),event(3,'ACTOR_RESOURCE_SET',actor=41,resource='AP',value=10))
            with self.assertRaisesRegex(JournalOrderingError,'RECEIPT_CONFLICT'):
                j.append_fixture_envelope(envelope(batch=changed))

    def test_same_source_digest_cannot_be_relabelled_as_new_batch(self):
        with self.journal() as j:
            j.append_fixture_envelope(envelope())
            later=(event(4,'TURN_STARTED',actor=41,event_id='e-s1-4'),)
            with self.assertRaisesRegex(JournalOrderingError,'SOURCE_RECEIPT_REUSED'):
                j.append_fixture_envelope(envelope(batch_id='batch-2',batch=later))

    def test_receipted_envelope_cannot_adopt_unreceipted_existing_events(self):
        with self.journal() as j:
            j.append_fixture_batch(events())
            with self.assertRaisesRegex(JournalOrderingError,'UNRECEIPTED_EVENT_COLLISION'):
                j.append_fixture_envelope(envelope())
            self.assertEqual(j.audit()['batch_receipts'],0)

    def test_receipt_digest_tamper_is_detected(self):
        with self.journal() as j:
            j.append_fixture_envelope(envelope())
            j.db.execute("UPDATE batch_receipts SET batch_digest=? WHERE batch_id='batch-1'",('0'*64,))
            with self.assertRaisesRegex(JournalIntegrityError,'RECEIPT_DIGEST'):
                j.audit()

    def test_receipt_event_hash_tamper_is_detected(self):
        with self.journal() as j:
            j.append_fixture_envelope(envelope())
            j.db.execute("UPDATE batch_receipts SET last_event_hash=? WHERE batch_id='batch-1'",('f'*64,))
            with self.assertRaisesRegex(JournalIntegrityError,'RECEIPT_EVENT_MISMATCH'):
                j.audit()

    def test_receipt_range_tamper_is_detected(self):
        with self.journal() as j:
            j.append_fixture_envelope(envelope())
            j.db.execute("UPDATE batch_receipts SET last_sequence=2 WHERE batch_id='batch-1'")
            with self.assertRaisesRegex(JournalIntegrityError,'RECEIPT_INVALID'):
                j.audit()

    def test_concurrent_exact_envelopes_commit_once(self):
        env=envelope()
        def worker(_):
            with self.journal() as j:
                return j.append_fixture_envelope(env)['status']
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses=sorted(pool.map(worker,range(2)))
        self.assertEqual(statuses,['COMMITTED_SIMULATED','IDEMPOTENT_RECEIPT'])
        with self.journal() as j:
            self.assertEqual((j.audit()['events'],j.audit()['batch_receipts']),(3,1))

    def test_receipt_status_does_not_expose_event_account_or_session_values(self):
        private=(event(1,session='secret-session',account='secret-account'),)
        env=envelope(batch_id='opaque-batch',source='opaque-source',batch=private)
        with self.journal() as j:
            j.append_fixture_envelope(env)
            text=repr(j.batch_receipt_status('opaque-batch'))
            self.assertNotIn('secret-session',text)
            self.assertNotIn('secret-account',text)
            self.assertNotIn(private[0].event_id,text)
            self.assertIn('SYNTHETIC_FIXTURE_ONLY',text)

    def test_envelope_contract_rejects_unbounded_invalid_or_non_fixture_input(self):
        with self.assertRaisesRegex(ValueError,'BATCH_ID'):
            OfflineBatchEnvelope('',digest('x'),events())
        with self.assertRaisesRegex(ValueError,'SOURCE_DIGEST'):
            OfflineBatchEnvelope('b','nope',events())
        with self.assertRaisesRegex(ValueError,'BATCH_EVENTS'):
            OfflineBatchEnvelope('b',digest('x'),())
        with self.assertRaisesRegex(ValueError,'BATCH_EVENTS'):
            OfflineBatchEnvelope('b',digest('x'),[event(1)])
        with self.journal() as j:
            with self.assertRaisesRegex(TypeError,'SYNTHETIC_ENVELOPE'):
                j.append_fixture_envelope(object())

    def test_empty_v1_database_migrates_transactionally_to_v2(self):
        raw=sqlite3.connect(self.path)
        try:
            raw.executescript('''
            CREATE TABLE ledger_version(schema INTEGER NOT NULL);
            INSERT INTO ledger_version(schema) VALUES (1);
            CREATE TABLE events(event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, sequence INTEGER NOT NULL,
              event_json TEXT NOT NULL, prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL, UNIQUE(session_id,sequence));
            CREATE TABLE projections(session_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, state_json TEXT NOT NULL,
              state_hash TEXT NOT NULL, last_event_hash TEXT NOT NULL);
            ''')
            raw.commit()
        finally:
            raw.close()
        with self.journal() as migrated:
            self.assertEqual(migrated.db.execute('SELECT schema FROM ledger_version').fetchone()[0],2)
            self.assertEqual(migrated.audit()['batch_receipts'],0)
            migrated.append_fixture_envelope(envelope())
            self.assertEqual(migrated.audit()['batch_receipts'],1)

    def test_read_only_v1_database_is_not_silently_migrated(self):
        raw=sqlite3.connect(self.path)
        try:
            raw.executescript('''
            CREATE TABLE ledger_version(schema INTEGER NOT NULL);
            INSERT INTO ledger_version(schema) VALUES (1);
            CREATE TABLE events(event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, sequence INTEGER NOT NULL,
              event_json TEXT NOT NULL, prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL, UNIQUE(session_id,sequence));
            CREATE TABLE projections(session_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, state_json TEXT NOT NULL,
              state_hash TEXT NOT NULL, last_event_hash TEXT NOT NULL);
            ''')
            raw.commit()
        finally:
            raw.close()
        with self.assertRaisesRegex(JournalIntegrityError,'SCHEMA_UNSUPPORTED'):
            SQLiteFixtureJournal(self.path,reducer=apply_offline_event,read_only=True)
        with closing(sqlite3.connect(self.path)) as check:
            self.assertEqual(check.execute('SELECT schema FROM ledger_version').fetchone()[0],1)


if __name__=='__main__':
    unittest.main()
