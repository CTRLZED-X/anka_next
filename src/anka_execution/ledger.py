"""P18 durable *offline fixture* intent and settlement journal.

The dispatch boundary is a persisted intent to attempt an input, NOT a driver
call. A committed dispatch boundary stays uncertain after crash/restart and
may never be replayed automatically. Live authority/actuators are absent.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator
from anka_contracts.execution_flow import OfflineActionIntent, OfflineOutcomeEvidence, OfflineActionAudit
from anka_execution.settlement import next_status, reason_for, ExecutionTransitionRejected


class ExecutionLedgerRejected(ValueError):
    pass


class ExecutionLedgerIntegrityError(RuntimeError):
    pass


def _encode(data: dict) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False)


def _hash(seq: int, action_id: str, event: str, payload: str, prev: str) -> str:
    return hashlib.sha256(_encode({'seq': seq, 'action_id': action_id, 'event': event,
                                   'payload': payload, 'previous': prev}).encode('utf8')).hexdigest()


class OfflineExecutionLedger:
    """SQLite single-writer fixture simulation; has NO input-driver dependency."""
    def __init__(self, path: Path, *, fault_hook: Callable[[str], None] | None = None, read_only: bool = False):
        self.path = Path(path)
        self.fault_hook = fault_hook
        self.read_only = read_only
        if read_only and not self.path.is_file():
            raise ExecutionLedgerRejected('P18_AUDIT_DATABASE_NOT_FOUND')
        if self.path.exists() and not self.path.is_file():
            raise ExecutionLedgerRejected('P18_DATABASE_PATH_INVALID')
        if read_only:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as con:
            con.executescript('''
                CREATE TABLE IF NOT EXISTS action_intents (
                    action_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL, account_id TEXT NOT NULL,
                    client_id TEXT NOT NULL, window_generation INTEGER NOT NULL,
                    fight_id TEXT NOT NULL, actor_id INTEGER NOT NULL,
                    turn_id TEXT NOT NULL, action_key TEXT NOT NULL,
                    payload TEXT NOT NULL, status TEXT NOT NULL,
                    UNIQUE(session_id, fight_id, actor_id, turn_id, action_key)
                );
                CREATE TABLE IF NOT EXISTS action_events (
                    sequence INTEGER PRIMARY KEY,
                    action_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    record_hash TEXT NOT NULL,
                    FOREIGN KEY(action_id) REFERENCES action_intents(action_id)
                );
                CREATE TABLE IF NOT EXISTS observed_evidence (
                    evidence_id TEXT PRIMARY KEY, action_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY(action_id) REFERENCES action_intents(action_id)
                );
                CREATE INDEX IF NOT EXISTS action_client_scope ON action_intents(client_id,window_generation,status);
                CREATE UNIQUE INDEX IF NOT EXISTS one_global_dispatch ON action_intents((1))
                    WHERE status='DISPATCH_UNCERTAIN';
                CREATE TRIGGER IF NOT EXISTS forbid_event_update
                    BEFORE UPDATE ON action_events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY_EVENTS'); END;
                CREATE TRIGGER IF NOT EXISTS forbid_event_delete
                    BEFORE DELETE ON action_events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY_EVENTS'); END;
            ''')

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path.absolute().as_uri()+'?mode=ro' if self.read_only else str(self.path),
                              uri=self.read_only, timeout=3.0, isolation_level=None)
        try:
            con.execute('PRAGMA foreign_keys=ON')
            con.execute('PRAGMA busy_timeout=3000')
            if self.read_only:
                con.execute('PRAGMA query_only=ON')
            else:
                con.execute('PRAGMA synchronous=FULL')
                con.execute('PRAGMA journal_mode=WAL')
            yield con
        finally:
            con.close()

    def _fault(self, stage: str):
        if self.fault_hook is not None:
            self.fault_hook(stage)

    @staticmethod
    def _append(con: sqlite3.Connection, action_id: str, event: str, payload: dict):
        tail = con.execute('SELECT sequence,record_hash FROM action_events ORDER BY sequence DESC LIMIT 1').fetchone()
        seq = 1 if tail is None else tail[0] + 1
        prev = 'GENESIS' if tail is None else tail[1]
        encoded = _encode(payload)
        con.execute('INSERT INTO action_events VALUES(?,?,?,?,?,?)',
                    (seq, action_id, event, encoded, prev, _hash(seq, action_id, event, encoded, prev)))

    def _commit_transition(self, action_id: str, event: str, payload: dict):
        if self.read_only: raise ExecutionLedgerRejected('P18_AUDIT_READ_ONLY')
        with self._db() as con:
            con.execute('BEGIN IMMEDIATE')
            try:
                row = con.execute('SELECT status FROM action_intents WHERE action_id=?',(action_id,)).fetchone()
                if row is None:
                    raise ExecutionLedgerRejected('P18_UNKNOWN_ACTION')
                new_status = next_status(row[0], event)
                if event == 'DISPATCH_BOUNDARY_COMMITTED':
                    busy = con.execute("SELECT action_id FROM action_intents WHERE status='DISPATCH_UNCERTAIN' AND action_id<>? LIMIT 1",(action_id,)).fetchone()
                    if busy is not None:
                        raise ExecutionLedgerRejected('P18_GLOBAL_DISPATCH_BUSY')
                self._append(con, action_id, event, payload)
                self._fault('after_event_before_status')
                con.execute('UPDATE action_intents SET status=? WHERE action_id=?',(new_status,action_id))
                self._fault('after_status_before_commit')
                con.commit()
            except Exception:
                con.rollback()
                raise
        return new_status

    def prepare(self, intent: OfflineActionIntent) -> OfflineActionAudit:
        if self.read_only: raise ExecutionLedgerRejected('P18_AUDIT_READ_ONLY')
        if not isinstance(intent, OfflineActionIntent):
            raise ExecutionLedgerRejected('P18_ACTION_INTENT_REQUIRED')
        with self._db() as con:
            con.execute('BEGIN IMMEDIATE')
            try:
                existing = con.execute('SELECT action_id FROM action_intents WHERE action_id=?',(intent.action_id,)).fetchone()
                if existing:
                    raise ExecutionLedgerRejected('P18_DUPLICATE_ACTION_ID')
                overlap = con.execute('''SELECT action_id FROM action_intents
                    WHERE client_id=? AND window_generation=? AND status IN ('PREPARED','DISPATCH_UNCERTAIN') LIMIT 1''',
                    (intent.client_id,intent.window_generation)).fetchone()
                if overlap:
                    raise ExecutionLedgerRejected('P18_CLIENT_HAS_PENDING_ACTION')
                encoded = _encode(intent.to_dict())
                con.execute('''INSERT INTO action_intents VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                    (intent.action_id,intent.session_id,intent.account_id,intent.client_id,
                     intent.window_generation,intent.fight_id,intent.actor_id,intent.turn_id,
                     intent.action_key,encoded,'PREPARED'))
                self._append(con,intent.action_id,'PREPARED',intent.to_dict())
                self._fault('after_prepare_event_before_commit')
                con.commit()
            except sqlite3.IntegrityError as exc:
                con.rollback()
                raise ExecutionLedgerRejected('P18_DUPLICATE_LOGICAL_ACTION_OR_SCHEMA') from exc
            except Exception:
                con.rollback()
                raise
        return self.audit(intent.action_id)

    def mark_dispatch_boundary(self, action_id: str) -> OfflineActionAudit:
        if self.read_only: raise ExecutionLedgerRejected('P18_AUDIT_READ_ONLY')
        # Never calls an IO provider: only records the boundary durably.
        self._commit_transition(action_id,'DISPATCH_BOUNDARY_COMMITTED',{'physical_input_sent': False})
        return self.audit(action_id)

    def cancel_before_dispatch(self, action_id: str) -> OfflineActionAudit:
        if self.read_only: raise ExecutionLedgerRejected('P18_AUDIT_READ_ONLY')
        self._commit_transition(action_id,'CANCELLED_BEFORE_DISPATCH',{'physical_input_sent':False})
        return self.audit(action_id)

    def record_outcome(self, evidence: OfflineOutcomeEvidence) -> OfflineActionAudit:
        if self.read_only: raise ExecutionLedgerRejected('P18_AUDIT_READ_ONLY')
        if not isinstance(evidence,OfflineOutcomeEvidence):
            raise ExecutionLedgerRejected('P18_OUTCOME_EVIDENCE_REQUIRED')
        with self._db() as con:
            con.execute('BEGIN IMMEDIATE')
            try:
                row=con.execute('SELECT payload,status FROM action_intents WHERE action_id=?',
                                (evidence.action_id,)).fetchone()
                if row is None:raise ExecutionLedgerRejected('P18_UNKNOWN_ACTION')
                intent=OfflineActionIntent(**json.loads(row[0]))
                fields=('action_id','session_id','account_id','client_id','window_generation','fight_id','turn_id','actor_id')
                if any(getattr(evidence,f)!=getattr(intent,f) for f in fields):
                    raise ExecutionLedgerRejected('P18_OUTCOME_SCOPE_MISMATCH')
                if evidence.observed_revision <= intent.state_revision:
                    raise ExecutionLedgerRejected('P18_STALE_OUTCOME_REVISION')
                if con.execute('SELECT 1 FROM observed_evidence WHERE evidence_id=?',(evidence.evidence_id,)).fetchone():
                    raise ExecutionLedgerRejected('P18_DUPLICATE_EVIDENCE')
                event='OUTCOME_'+evidence.outcome
                status=next_status(row[1],event)
                con.execute('INSERT INTO observed_evidence VALUES(?,?,?)',
                            (evidence.evidence_id,evidence.action_id,_encode(evidence.to_dict())))
                self._append(con,evidence.action_id,event,evidence.to_dict())
                self._fault('after_outcome_event_before_status')
                con.execute('UPDATE action_intents SET status=? WHERE action_id=?',(status,evidence.action_id))
                self._fault('after_outcome_status_before_commit')
                con.commit()
            except Exception:
                con.rollback()
                raise
        return self.audit(evidence.action_id)

    def audit_all(self) -> tuple[OfflineActionAudit,...]:
        """Single consistent read transaction, verifying global hash chain and projections."""
        with self._db() as con:
            con.execute('BEGIN')
            try:
                intents=con.execute('SELECT action_id,payload,status FROM action_intents ORDER BY action_id').fetchall()
                events=con.execute('SELECT sequence,action_id,event_type,payload,previous_hash,record_hash FROM action_events ORDER BY sequence').fetchall()
                proofs=con.execute('SELECT evidence_id,action_id,payload FROM observed_evidence ORDER BY evidence_id').fetchall()
                # Verify the database contents, not just the projection flags.
                reconstructed={}
                prev='GENESIS'
                evidence_rows={}
                for expected, (seq,action,event,payload,ph,rh) in enumerate(events,1):
                    if seq!=expected or ph!=prev or rh!=_hash(seq,action,event,payload,prev):
                        raise ExecutionLedgerIntegrityError('P18_EVENT_CHAIN_CORRUPTED')
                    prev=rh
                    try: data=json.loads(payload)
                    except (ValueError,TypeError):raise ExecutionLedgerIntegrityError('P18_EVENT_PAYLOAD_CORRUPTED') from None
                    entry=reconstructed.setdefault(action,{'status':None,'count':0,'evidence':[],'intent':None})
                    try:
                        status=next_status(entry['status'],event)
                    except ExecutionTransitionRejected:
                        raise ExecutionLedgerIntegrityError('P18_REPLAY_TRANSITION_INVALID') from None
                    if event=='PREPARED':
                        try: entry['intent']=OfflineActionIntent(**data)
                        except (ValueError,TypeError):raise ExecutionLedgerIntegrityError('P18_REPLAY_INTENT_INVALID') from None
                        if entry['intent'].action_id!=action:raise ExecutionLedgerIntegrityError('P18_REPLAY_ACTION_MISMATCH')
                    elif event.startswith('OUTCOME_'):
                        try: proof=OfflineOutcomeEvidence(**data)
                        except (ValueError,TypeError):raise ExecutionLedgerIntegrityError('P18_REPLAY_EVIDENCE_INVALID') from None
                        if proof.action_id!=action or event!='OUTCOME_'+proof.outcome:
                            raise ExecutionLedgerIntegrityError('P18_REPLAY_OUTCOME_MISMATCH')
                        base=entry['intent']
                        scope=('action_id','session_id','account_id','client_id','window_generation',
                               'fight_id','turn_id','actor_id')
                        if (base is None or any(getattr(proof,k)!=getattr(base,k) for k in scope)
                                or proof.observed_revision<=base.state_revision):
                            raise ExecutionLedgerIntegrityError('P18_REPLAY_EVIDENCE_SCOPE_INVALID')
                        if proof.evidence_id in evidence_rows:
                            raise ExecutionLedgerIntegrityError('P18_REPLAY_DUPLICATE_EVIDENCE')
                        evidence_rows[proof.evidence_id]=(action,payload)
                        entry['evidence'].append(proof.evidence_id)
                    entry['status']=status
                    entry['count']+=1
                stored={}
                for action,payload,status in intents:
                    entry=reconstructed.get(action)
                    if entry is None or entry['intent'] is None or entry['status']!=status or payload!=_encode(entry['intent'].to_dict()):
                        raise ExecutionLedgerIntegrityError('P18_PROJECTION_MISMATCH')
                    stored[action]=OfflineActionAudit(action,status,reason_for(status),entry['count'],tuple(entry['evidence']))
                if len(stored)!=len(reconstructed):raise ExecutionLedgerIntegrityError('P18_MISSING_PROJECTED_ACTION')
                if sum(r.status=='DISPATCH_UNCERTAIN' for r in stored.values())>1:
                    raise ExecutionLedgerIntegrityError('P18_MULTIPLE_UNCERTAIN_DISPATCHES')
                if len(proofs)!=len(evidence_rows) or any(evidence_rows.get(eid)!=(aid,payload) for eid,aid,payload in proofs):
                    raise ExecutionLedgerIntegrityError('P18_EVIDENCE_TABLE_MISMATCH')
                con.commit()
                return tuple(stored[k] for k in sorted(stored))
            except Exception:
                con.rollback()
                raise

    def audit(self, action_id: str) -> OfflineActionAudit:
        if type(action_id) is not str:
            raise ExecutionLedgerRejected('P18_ACTION_ID_INVALID')
        for report in self.audit_all():
            if report.action_id==action_id:return report
        raise ExecutionLedgerRejected('P18_UNKNOWN_ACTION')
