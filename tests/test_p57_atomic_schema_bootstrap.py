"""P57: SQLite schema bootstrapping is crash-atomic, never silently repaired.

All inputs are synthetic test databases; no live admission path is present.
"""
from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from anka_canonical.journal import SQLiteFixtureJournal, JournalIntegrityError
from anka_live_state.reducer import apply_offline_event


def tables(path: Path) -> set[str]:
    with closing(sqlite3.connect(path)) as db:
        return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


class P57AtomicSchemaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'synthetic.db'

    def open(self, cls=SQLiteFixtureJournal):
        return cls(self.path, reducer=apply_offline_event)

    def fail_create(self, table_name: str):
        class Denied(SQLiteFixtureJournal):
            def _create_schema(self):
                def deny(action, name, _table, _database, _trigger):
                    if action == sqlite3.SQLITE_CREATE_TABLE and name == table_name:
                        return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK
                self.db.set_authorizer(deny)
                try:
                    return super()._create_schema()
                finally:
                    self.db.set_authorizer(None)
        return Denied

    def test_failed_fresh_schema_creation_leaves_no_partial_tables(self):
        with self.assertRaises(sqlite3.DatabaseError):
            self.open(self.fail_create('projections'))
        self.assertEqual(tables(self.path), set())
        with self.open() as j:
            self.assertEqual(j.audit()['events'], 0)

    def test_failure_in_last_schema_table_rolls_back_every_table(self):
        with self.assertRaises(sqlite3.DatabaseError):
            self.open(self.fail_create('batch_receipts'))
        self.assertEqual(tables(self.path), set())

    def test_abandoned_unversioned_partial_schema_not_promoted(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE ledger_version (schema INTEGER NOT NULL)')
            db.execute('CREATE TABLE events (anything TEXT)')
        with self.assertRaisesRegex(JournalIntegrityError, 'UNVERSIONED'):
            self.open()
        self.assertEqual(tables(self.path), {'ledger_version', 'events'})
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT * FROM ledger_version').fetchall(), [])

    def test_existing_empty_version_table_can_initialize_from_clean_state(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE ledger_version (schema INTEGER NOT NULL)')
        with self.open() as j:
            self.assertEqual(j.db.execute('SELECT schema FROM ledger_version').fetchall(), [(2,)])
            self.assertEqual(j.audit()['events'], 0)

    def test_two_concurrent_writers_initialize_same_fresh_schema(self):
        gate = threading.Barrier(2)
        def worker(_):
            gate.wait(timeout=5)
            with self.open() as j:
                return j.db.execute('SELECT schema FROM ledger_version').fetchone()[0]
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(worker, range(2))), [2, 2])
        self.assertEqual(tables(self.path), {'ledger_version', 'events', 'projections', 'batch_receipts'})

    def test_unsupported_schema_does_not_create_migration_tables(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE ledger_version (schema INTEGER NOT NULL)')
            db.execute('INSERT INTO ledger_version VALUES (91)')
        with self.assertRaisesRegex(JournalIntegrityError, 'SCHEMA_UNSUPPORTED'):
            self.open()
        self.assertEqual(tables(self.path), {'ledger_version'})

    def test_existing_v2_event_unique_constraint_is_required(self):
        with self.open():
            pass
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DROP TABLE events')
            db.execute('''CREATE TABLE events (
                event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                event_json TEXT NOT NULL, prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL)''')
        with self.assertRaisesRegex(JournalIntegrityError, 'UNIQUE_CONSTRAINT_MISSING'):
            self.open()

    def test_existing_v2_receipt_source_uniqueness_is_required(self):
        with self.open():
            pass
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DROP TABLE batch_receipts')
            db.execute('''CREATE TABLE batch_receipts (
                batch_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                first_sequence INTEGER NOT NULL, last_sequence INTEGER NOT NULL,
                event_count INTEGER NOT NULL, source_digest TEXT NOT NULL,
                batch_digest TEXT NOT NULL, last_event_hash TEXT NOT NULL,
                UNIQUE(session_id,first_sequence,last_sequence))''')
        with self.assertRaisesRegex(JournalIntegrityError, 'UNIQUE_CONSTRAINT_MISSING'):
            self.open()

    def test_existing_v2_missing_column_rejected_before_replay(self):
        with self.open():
            pass
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('ALTER TABLE projections RENAME COLUMN state_hash TO forged')
        with self.assertRaisesRegex(JournalIntegrityError, 'SCHEMA_LAYOUT_MISMATCH'):
            self.open()

    def test_v1_migration_rolls_back_if_version_publish_denied(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript('''
                CREATE TABLE ledger_version(schema INTEGER NOT NULL);
                INSERT INTO ledger_version VALUES(1);
                CREATE TABLE events(event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                  sequence INTEGER NOT NULL, event_json TEXT NOT NULL, prev_hash TEXT NOT NULL,
                  event_hash TEXT NOT NULL, UNIQUE(session_id,sequence));
                CREATE TABLE projections(session_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                  state_json TEXT NOT NULL, state_hash TEXT NOT NULL, last_event_hash TEXT NOT NULL);
            ''')
        class DenyVersionUpdate(SQLiteFixtureJournal):
            def _create_schema(self):
                def deny(action, name, _col, _database, _trigger):
                    if action==sqlite3.SQLITE_UPDATE and name=='ledger_version':
                        return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK
                self.db.set_authorizer(deny)
                try:
                    return super()._create_schema()
                finally:
                    self.db.set_authorizer(None)
        with self.assertRaises(sqlite3.DatabaseError):
            self.open(DenyVersionUpdate)
        self.assertEqual(tables(self.path), {'ledger_version','events','projections'})
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT schema FROM ledger_version').fetchall(),[(1,)])
        with self.open() as migrated:
            self.assertEqual(migrated.db.execute('SELECT schema FROM ledger_version').fetchall(),[(2,)])

    def test_preflight_smoke_proves_atomic_schema_failure(self):
        from anka_app.state_offline import schema_atomic_bootstrap_smoke
        status=schema_atomic_bootstrap_smoke()
        self.assertEqual(status['status'],'PASS_SYNTHETIC_SCHEMA_ATOMIC')
        self.assertTrue(status['fault_rolled_back_every_table'])
        self.assertFalse(status['actionable'])

    def test_malformed_v1_is_not_upgraded_to_v2(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript('''
                CREATE TABLE ledger_version (schema INTEGER NOT NULL);
                INSERT INTO ledger_version VALUES(1);
                CREATE TABLE events (event_id TEXT PRIMARY KEY, session_id TEXT,
                    sequence INTEGER, event_json TEXT, prev_hash TEXT, event_hash TEXT);
                CREATE TABLE projections(session_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                    state_json TEXT NOT NULL, state_hash TEXT NOT NULL, last_event_hash TEXT NOT NULL);
            ''')
        with self.assertRaisesRegex(JournalIntegrityError, 'SCHEMA_LAYOUT_MISMATCH'):
            self.open()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT schema FROM ledger_version').fetchall(),[(1,)])
        self.assertNotIn('batch_receipts',tables(self.path))

    def test_read_only_open_never_creates_tables(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE ledger_version (schema INTEGER NOT NULL)')
        with self.assertRaises(JournalIntegrityError):
            SQLiteFixtureJournal(self.path, reducer=apply_offline_event, read_only=True)
        self.assertEqual(tables(self.path), {'ledger_version'})


if __name__ == '__main__':
    unittest.main()
