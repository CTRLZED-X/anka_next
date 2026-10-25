"""P8 composition root; only this layer knows both Canonical storage + reducer."""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import closing
from hashlib import sha256
import sqlite3
from anka_contracts.state import OfflineStateEvent,OfflineBatchEnvelope
from anka_canonical.journal import SQLiteFixtureJournal,JournalPersistenceError,JournalUnhealthyError
from anka_live_state.reducer import apply_offline_event,summarize_snapshot


def _event(n:int,kind:str,**kwargs)->OfflineStateEvent:
    return OfflineStateEvent(event_id=f'synthetic-p8-{n}',session_id='synthetic-session',account_id='synthetic-cra',
                             account_generation=1,fight_id='synthetic-fight',sequence=n,kind=kind,**kwargs)


def synthetic_state_demo(*,observer=None)->dict:
    with TemporaryDirectory(prefix='anka-p8-synthetic-') as folder:
        with SQLiteFixtureJournal(Path(folder)/'synthetic.sqlite3',reducer=apply_offline_event) as journal:
            events=[_event(1,'FIGHT_STARTED'),_event(2,'ACTOR_SEEN',actor_id=777),
                    _event(3,'ACTOR_POSITION_SET',actor_id=777,value=215),
                    _event(4,'ACTOR_HP_SET',actor_id=777,value=2800,maximum=3200),
                    _event(5,'ACTOR_RESOURCE_SET',actor_id=777,resource='AP',value=11),
                    _event(6,'ACTOR_RESOURCE_SET',actor_id=777,resource='MP',value=5),
                    _event(7,'TURN_STARTED',actor_id=777)]
            receipts=[journal.append_fixture(e) for e in events]
            audit=journal.audit()
            state=summarize_snapshot(journal.snapshot('synthetic-session'))
    if observer is not None:
        observer.record('state.synthetic_demo_verified',boundary='canonical.synthetic_atomic_replay',
                        payload={'event_count':audit['events'],'revision':state['revision'],'actionable':False})
    return {'operation':'state-demo','status':'SYNTHETIC_STATE_ONLY','journal':audit,'state':state,
            'commits':len(receipts),'live_ready':False,'physical_input_sent':False}


def transactional_journal_smoke()->dict:
    """P55 setup-time proof of batch atomicity and commit-ambiguity fencing.

    Uses temporary synthetic fixtures only.  No historical/current protocol
    evidence is accepted and no operating-system input exists on this path.
    """
    with TemporaryDirectory(prefix='anka-p55-transactional-') as folder:
        path=Path(folder)/'synthetic.sqlite3'
        batch=(
            _event(1,'FIGHT_STARTED'),
            _event(2,'ACTOR_SEEN',actor_id=777),
            _event(3,'ACTOR_RESOURCE_SET',actor_id=777,resource='AP',value=11),
        )
        journal=SQLiteFixtureJournal(path,reducer=apply_offline_event)
        try:
            try:
                journal.append_fixture_batch(batch,failure_injection='commit_ack_lost')
            except JournalPersistenceError as exc:
                if exc.stage!='commit' or exc.rollback_succeeded:
                    raise RuntimeError('P55_COMMIT_UNCERTAINTY_CLASSIFICATION_FAILED') from exc
            else:
                raise RuntimeError('P55_COMMIT_UNCERTAINTY_NOT_DETECTED')
            if journal.is_write_healthy():
                raise RuntimeError('P55_COMMIT_UNCERTAINTY_NOT_FENCED')
            try:
                journal.append_fixture(_event(4,'TURN_STARTED',actor_id=777))
            except JournalUnhealthyError:
                pass
            else:
                raise RuntimeError('P55_FENCED_WRITER_ACCEPTED_WRITE')
        finally:
            journal.close()
        with SQLiteFixtureJournal(path,reducer=apply_offline_event) as recovered:
            audit=recovered.audit()
            if audit['events']!=3 or recovered.snapshot('synthetic-session')['revision']!=3:
                raise RuntimeError('P55_REOPEN_REPLAY_RECOVERY_FAILED')
            if not recovered.is_write_healthy():
                raise RuntimeError('P55_REOPEN_DID_NOT_RESTORE_WRITER')
    return {'status':'PASS_SYNTHETIC_TRANSACTION_FENCE',
            'atomic_batch_events':3,'commit_uncertainty_fenced':True,
            'reopen_replay_verified':True,'authority':'SYNTHETIC_FIXTURE_ONLY',
            'canonical_live_commits':0,'live_ready':False,'actionable':False,
            'physical_input_sent':False}



def source_bound_receipt_smoke()->dict:
    """P56 setup-time proof that source identity and durable batch stay atomic."""
    with TemporaryDirectory(prefix='anka-p56-receipt-') as folder:
        path=Path(folder)/'synthetic.sqlite3'
        batch=(
            _event(1,'FIGHT_STARTED'),
            _event(2,'ACTOR_SEEN',actor_id=777),
            _event(3,'ACTOR_RESOURCE_SET',actor_id=777,resource='AP',value=11),
        )
        source=sha256(b'p56-synthetic-source').hexdigest()
        envelope=OfflineBatchEnvelope('p56-synthetic-batch',source,batch)
        journal=SQLiteFixtureJournal(path,reducer=apply_offline_event)
        try:
            try:
                journal.append_fixture_envelope(envelope,failure_injection='commit_ack_lost')
            except JournalPersistenceError:
                pass
            else:
                raise RuntimeError('P56_COMMIT_ACK_LOSS_NOT_DETECTED')
        finally:
            journal.close()
        with SQLiteFixtureJournal(path,reducer=apply_offline_event) as recovered:
            replay=recovered.append_fixture_envelope(envelope)
            audit=recovered.audit()
            receipt=recovered.batch_receipt_status(envelope.batch_id)
            if replay.get('status')!='IDEMPOTENT_RECEIPT' or audit.get('events')!=3 or audit.get('batch_receipts')!=1:
                raise RuntimeError('P56_RECEIPT_REPLAY_RECOVERY_FAILED')
            if not receipt or receipt.get('status')!='DURABLE_SYNTHETIC_RECEIPT':
                raise RuntimeError('P56_DURABLE_RECEIPT_MISSING')
    return {'status':'PASS_SYNTHETIC_SOURCE_RECEIPT',
            'atomic_events':3,'durable_receipts':1,'lost_ack_replay':'IDEMPOTENT_RECEIPT',
            'authority':'SYNTHETIC_FIXTURE_ONLY','canonical_live_commits':0,
            'live_ready':False,'actionable':False,'physical_input_sent':False}

def audit_state_db(path:Path,*,observer=None)->dict:
    with SQLiteFixtureJournal(path,reducer=apply_offline_event,read_only=True) as journal:
        result=journal.audit()
    if observer is not None:observer.record('state.offline_journal_audited',boundary='canonical.replay',
                 payload={'sessions':result['sessions'],'events':result['events'],'live_ready':False})
    return {'operation':'state-audit', 'audit':result,'live_ready':False,'physical_input_sent':False}


def schema_atomic_bootstrap_smoke()->dict:
    """P57 preflight: deny the final DDL, prove no partial schema survived.

    Uses an isolated synthetic SQLite file; never probes or modifies user data.
    """
    with TemporaryDirectory(prefix='anka-p57-ddl-') as folder:
        path=Path(folder)/'synthetic.sqlite3'
        class FailFinalDDL(SQLiteFixtureJournal):
            def _create_schema(self):
                def deny(action,name,_table,_db,_trigger):
                    if action==sqlite3.SQLITE_CREATE_TABLE and name=='batch_receipts':
                        return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK
                self.db.set_authorizer(deny)
                try:
                    super()._create_schema()
                finally:
                    self.db.set_authorizer(None)
        try:
            with FailFinalDDL(path,reducer=apply_offline_event):
                pass
        except sqlite3.DatabaseError:
            pass
        else:
            raise RuntimeError('P57_FAULT_INJECTION_FAILED')
        with closing(sqlite3.connect(path)) as database:
            existing=database.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if existing:
            raise RuntimeError('P57_SCHEMA_CREATION_WAS_NOT_ATOMIC')
        with SQLiteFixtureJournal(path,reducer=apply_offline_event) as journal:
            if journal.audit()['events']!=0:
                raise RuntimeError('P57_SCHEMA_REOPEN_NOT_CLEAN')
        return {'status':'PASS_SYNTHETIC_SCHEMA_ATOMIC',
                'fault_rolled_back_every_table':True,'fresh_reopen_audited':True,
                'authority':'SYNTHETIC_FIXTURE_ONLY','canonical_live_commits':0,
                'live_ready':False,'actionable':False,'physical_input_sent':False}
