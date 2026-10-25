"""Durable synthetic-event ledger with atomic event + state persistence.

P55 extends the P8 fixture journal with a batch transaction boundary and
commit-uncertainty fencing.  The contract is still SYNTHETIC_FIXTURE_ONLY:
Protocol/Capture internals are forbidden here and there is no live admission or
input authorization path.
"""
from __future__ import annotations
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import json,sqlite3
import time
from typing import Callable,Sequence
from anka_contracts.state import OfflineStateEvent,OfflineBatchEnvelope

SCHEMA=2
GENESIS='0'*64
MAX_EVENT_JSON=8192
MAX_AUDIT_EVENTS_PER_SESSION=50000
MAX_SNAPSHOT_JSON=1024*1024
MAX_BATCH_EVENTS=2048

class JournalError(RuntimeError):pass
class JournalIntegrityError(JournalError):pass
class JournalOrderingError(JournalError):pass
class JournalUnhealthyError(JournalError):pass

class JournalPersistenceError(JournalError):
    """Persistence failed at a boundary where the current writer may be unsafe."""
    def __init__(self,message:str,*,stage:str,rollback_succeeded:bool):
        super().__init__(message)
        self.stage=str(stage)
        self.rollback_succeeded=bool(rollback_succeeded)


def _encode(value)->str:return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)
def _sha(value:str)->str:return sha256(value.encode('ascii')).hexdigest()

def _receipt_digest(batch_id:str,source_digest:str,raws:tuple[str,...])->str:
    return _sha(_encode({'batch_id':batch_id,'source_digest':source_digest,'event_json':list(raws)}))

def _deserialize(raw:str)->OfflineStateEvent:
    obj=json.loads(raw)
    if 'cooldowns' in obj:obj['cooldowns']=tuple(tuple(x) for x in obj['cooldowns'])
    event=OfflineStateEvent(**{k:v for k,v in obj.items() if k!='origin'})
    if obj.get('origin')!='SYNTHETIC_FIXTURE_ONLY' or _encode(asdict(event))!=raw:
        raise JournalIntegrityError('JOURNAL_EVENT_CONTRACT_MISMATCH')
    return event

# The durable format's complete columns and unique keys are part of the
# contract. SQLite accepts TEXT PRIMARY KEY as nullable in rowid tables;
# preserve the existing v2 layout rather than silently changing old archives.
SCHEMA_COLUMNS={
    'ledger_version': (('schema','INTEGER',1,0),),
    'events': (('event_id','TEXT',0,1),('session_id','TEXT',1,0),
               ('sequence','INTEGER',1,0),('event_json','TEXT',1,0),
               ('prev_hash','TEXT',1,0),('event_hash','TEXT',1,0)),
    'projections': (('session_id','TEXT',0,1),('revision','INTEGER',1,0),
                    ('state_json','TEXT',1,0),('state_hash','TEXT',1,0),
                    ('last_event_hash','TEXT',1,0)),
    'batch_receipts': (('batch_id','TEXT',0,1),('session_id','TEXT',1,0),
                       ('first_sequence','INTEGER',1,0),('last_sequence','INTEGER',1,0),
                       ('event_count','INTEGER',1,0),('source_digest','TEXT',1,0),
                       ('batch_digest','TEXT',1,0),('last_event_hash','TEXT',1,0)),
}
SCHEMA_UNIQUE_KEYS={
    'events': {('event_id',),('session_id','sequence')},
    'projections': {('session_id',)},
    'batch_receipts': {('batch_id',),('source_digest',),
                       ('session_id','first_sequence','last_sequence')},
}

class SQLiteFixtureJournal:
    """One SQLite writer, WAL, FULL sync; synthetic/test-only event contract.

    Concurrent writers use ``BEGIN IMMEDIATE`` and deterministic sequential
    revisions.  P55 adds ``append_fixture_batch`` so one logical decoder batch
    cannot be partially persisted. P56 adds source-bound batch receipts so an
    upstream batch retry cannot be relabelled or detached from its durable facts.  A commit-stage ambiguity fences this writer
    until close/reopen + replay establishes the durable truth again.

    Nothing in this class accepts CanonicalDraft or historical/live evidence.
    """
    def __init__(self,path:Path,*,reducer:Callable[[dict|None,OfflineStateEvent],dict],read_only:bool=False):
        self.path=Path(path)
        self.reducer=reducer
        self.read_only=read_only
        self._write_health='READ_ONLY' if read_only else 'HEALTHY'
        self._last_write_failure:dict[str,object]|None=None
        if read_only:
            self.db=sqlite3.connect(f'file:{self.path.resolve().as_posix()}?mode=ro',uri=True,timeout=5,isolation_level=None)
        else:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            self.db=sqlite3.connect(str(self.path),timeout=5,isolation_level=None)
        try:
            # Set busy handling BEFORE any journal-mode negotiation; fresh
            # concurrent writers can race even before the schema lock exists.
            self.db.execute('PRAGMA busy_timeout=5000')
            if not read_only:
                # journal_mode can report SQLITE_BUSY immediately while two
                # fresh clients negotiate WAL concurrently, despite SQLite's
                # connection timeout. Retry only lock contention, bounded.
                for attempt in range(12):
                    try:
                        mode=self.db.execute('PRAGMA journal_mode=WAL').fetchone()
                        if mode!=('wal',):
                            raise JournalIntegrityError('JOURNAL_WAL_MODE_REQUIRED')
                        break
                    except sqlite3.OperationalError as exc:
                        if 'locked' not in str(exc).lower() or attempt==11:
                            raise
                        time.sleep(min(.01*(attempt+1),.05))
                self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('PRAGMA foreign_keys=ON')
            if not read_only:self._create_schema()
            self._check_schema()
            # Fail before any new append when a preexisting history cannot replay.
            # No replay may silently 'repair' stored evidence.
            self.audit()
        except BaseException:
            self.db.close()
            raise

    def _create_schema(self):
        """Create schema v2 or migrate the synthetic v1 ledger in place.

        The complete create/migrate decision is serialized with BEGIN IMMEDIATE,
        preventing two fresh writers from racing while the version table is
        still empty. Existing event/projection bytes are never rewritten.
        """
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute('CREATE TABLE IF NOT EXISTS ledger_version (schema INTEGER NOT NULL)')
            version=self.db.execute('SELECT schema FROM ledger_version').fetchall()
            if not version:
                # P56's executescript() could commit DDL halfway through. A
                # previously interrupted schema without a published version
                # must never be silently promoted to a valid database.
                present={name for (name,) in self.db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('events','projections','batch_receipts')"
                )}
                if present:
                    raise JournalIntegrityError('JOURNAL_SCHEMA_INCOMPLETE_UNVERSIONED')
                # DDL and the version marker stay in the SAME BEGIN IMMEDIATE;
                # sqlite3.Connection.executescript() implicitly COMMITs it.
                self.db.execute('''CREATE TABLE events (
                  event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                  event_json TEXT NOT NULL, prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL,
                  UNIQUE(session_id,sequence))''')
                self.db.execute('''CREATE TABLE projections (
                  session_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, state_json TEXT NOT NULL,
                  state_hash TEXT NOT NULL, last_event_hash TEXT NOT NULL)''')
                self.db.execute('''CREATE TABLE batch_receipts (
                  batch_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                  first_sequence INTEGER NOT NULL, last_sequence INTEGER NOT NULL,
                  event_count INTEGER NOT NULL, source_digest TEXT NOT NULL UNIQUE,
                  batch_digest TEXT NOT NULL, last_event_hash TEXT NOT NULL,
                  UNIQUE(session_id,first_sequence,last_sequence))''')
                self.db.execute('INSERT INTO ledger_version(schema) VALUES (?)',(SCHEMA,))
            elif version==[(1,)]:
                # Refuse a structurally corrupt v1 BEFORE publishing schema v2.
                # The previous existence-only probe could upgrade malformed
                # legacy tables, then fail and leave the wrong version durable.
                self._validate_schema_layout(('ledger_version','events','projections'))
                self.db.execute('''CREATE TABLE batch_receipts (
                  batch_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                  first_sequence INTEGER NOT NULL, last_sequence INTEGER NOT NULL,
                  event_count INTEGER NOT NULL, source_digest TEXT NOT NULL UNIQUE,
                  batch_digest TEXT NOT NULL, last_event_hash TEXT NOT NULL,
                  UNIQUE(session_id,first_sequence,last_sequence))''')
                self.db.execute('UPDATE ledger_version SET schema=?',(SCHEMA,))
            if self.db.in_transaction:self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise

    def _validate_schema_layout(self,tables:tuple[str,...])->None:
        for table in tables:
            expected=SCHEMA_COLUMNS[table]
            cols=self.db.execute(f'PRAGMA table_info({table})').fetchall()
            actual=tuple((name,kind,nonnull,primary) for _,name,kind,nonnull,_,primary in cols)
            if actual!=expected:
                raise JournalIntegrityError('JOURNAL_SCHEMA_LAYOUT_MISMATCH')
            if table in SCHEMA_UNIQUE_KEYS:
                unique=set()
                for index in self.db.execute(f'PRAGMA index_list({table})'):
                    # index tuple: sequence, name, unique, origin, partial
                    if index[2] and not index[4]:
                        names=tuple(row[2] for row in self.db.execute(f'PRAGMA index_info({index[1]})'))
                        unique.add(names)
                if not SCHEMA_UNIQUE_KEYS[table].issubset(unique):
                    raise JournalIntegrityError('JOURNAL_SCHEMA_UNIQUE_CONSTRAINT_MISSING')

    def _check_schema(self):
        try:
            version=self.db.execute('SELECT schema FROM ledger_version').fetchall()
            if version!=[(SCHEMA,)]:raise JournalIntegrityError('JOURNAL_SCHEMA_UNSUPPORTED')
            self._validate_schema_layout(tuple(SCHEMA_COLUMNS))
        except sqlite3.DatabaseError as e:raise JournalIntegrityError('JOURNAL_SCHEMA_CORRUPT') from e

    def _commit_transaction(self)->None:
        """Explicit hook for commit-uncertainty tests."""
        self.db.execute('COMMIT')

    def _rollback_transaction(self)->None:
        """Explicit hook for rollback/fencing tests."""
        self.db.execute('ROLLBACK')

    def _require_writer(self)->None:
        if self.read_only:raise JournalError('JOURNAL_READ_ONLY')
        if self._write_health!='HEALTHY':
            raise JournalUnhealthyError('JOURNAL_WRITER_FENCED_REOPEN_REQUIRED')

    def close(self):self.db.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

    def is_write_healthy(self)->bool:
        return not self.read_only and self._write_health=='HEALTHY'

    def runtime_status(self)->dict:
        """Safe diagnostic status; contains no event payloads/account values."""
        failure=None if self._last_write_failure is None else dict(self._last_write_failure)
        return {'write_health':self._write_health,'read_only':self.read_only,
                'last_write_failure':failure,'authority':'SYNTHETIC_FIXTURE_ONLY',
                'live_ready':False,'actionable':False}

    def snapshot(self,session_id:str)->dict|None:
        row=self.db.execute('SELECT state_json,state_hash FROM projections WHERE session_id=?',(session_id,)).fetchone()
        if row is None:return None
        raw,digest=row
        if _sha(raw)!=digest:raise JournalIntegrityError('JOURNAL_PROJECTION_TAMPERED')
        obj=json.loads(raw)
        if obj.get('authority')!='SYNTHETIC_FIXTURE_ONLY' or obj.get('actionable') is not False:
            raise JournalIntegrityError('JOURNAL_PROJECTION_UNSAFE')
        return obj

    def audited_snapshot(self, session_id: str) -> dict:
        """Replay-audit and read a projection from the SAME SQLite snapshot."""
        if not isinstance(session_id, str) or not session_id:
            raise ValueError('JOURNAL_SESSION_ID_REQUIRED')
        owns_transaction = not self.db.in_transaction
        if owns_transaction:
            self.db.execute('BEGIN')
        try:
            audit = self.audit(session_id=session_id)
            state = self.snapshot(session_id)
            return {'audit': audit, 'snapshot': state}
        finally:
            if owns_transaction:
                self.db.execute('ROLLBACK')

    def append_fixture(self,event:OfflineStateEvent,*,failure_injection:str|None=None)->dict:
        """Persist one fixture through the same transactional path as a batch."""
        result=self.append_fixture_batch((event,),failure_injection=failure_injection)
        # Preserve the P8 public status strings for callers/tests.
        return result

    def append_fixture_batch(self,events:Sequence[OfflineStateEvent],*,failure_injection:str|None=None)->dict:
        return self._append_fixture_batch(events,failure_injection=failure_injection,envelope=None)

    def append_fixture_envelope(self,envelope:OfflineBatchEnvelope,*,failure_injection:str|None=None)->dict:
        """Atomically bind one synthetic source receipt to its durable event batch.

        A receipt is immutable and source-digest unique.  Replaying the exact
        envelope is idempotent, including after a lost COMMIT acknowledgement.
        No historical/current protocol object is accepted by this API.
        """
        if not isinstance(envelope,OfflineBatchEnvelope):
            raise TypeError('JOURNAL_SYNTHETIC_ENVELOPE_REQUIRED')
        return self._append_fixture_batch(envelope.events,failure_injection=failure_injection,envelope=envelope)

    def _append_fixture_batch(self,events:Sequence[OfflineStateEvent],*,failure_injection:str|None=None,envelope:OfflineBatchEnvelope|None=None)->dict:
        """Atomically reduce and persist one logical synthetic event batch.

        All reducer transitions are evaluated before the first event row is
        inserted.  Event rows and the final projection are then persisted in one
        SQLite transaction.  Safe pre-commit failures roll back and the writer
        remains reusable.  Any commit-stage ambiguity or failed rollback fences
        the writer; close/reopen + audit is required before further writes.
        """
        self._require_writer()
        if failure_injection not in (None,'after_reduction','after_insert','after_projection','after_receipt','commit_ack_lost'):
            raise ValueError('UNKNOWN_FAULT_STAGE')
        if not isinstance(events,(tuple,list)):
            raise TypeError('JOURNAL_BATCH_SEQUENCE_REQUIRED')
        batch=tuple(events)
        if not batch or len(batch)>MAX_BATCH_EVENTS:
            raise JournalError('JOURNAL_BATCH_SIZE_INVALID')
        if any(not isinstance(e,OfflineStateEvent) for e in batch):
            raise TypeError('JOURNAL_ONLY_SYNTHETIC_FIXTURES')
        session=batch[0].session_id
        scope=(batch[0].session_id,batch[0].account_id,batch[0].account_generation)
        if any((e.session_id,e.account_id,e.account_generation)!=scope for e in batch):
            raise JournalOrderingError('JOURNAL_BATCH_SCOPE_MISMATCH')
        if len({e.event_id for e in batch})!=len(batch):
            raise JournalOrderingError('JOURNAL_BATCH_DUPLICATE_EVENT_ID')
        if any(e.sequence>MAX_AUDIT_EVENTS_PER_SESSION for e in batch):
            raise JournalError('JOURNAL_SESSION_LIMIT')
        if any(batch[i].sequence!=batch[0].sequence+i for i in range(len(batch))):
            raise JournalOrderingError('JOURNAL_BATCH_SEQUENCE_GAP_OR_REORDER')
        raws=tuple(_encode(asdict(e)) for e in batch)
        if any(len(raw.encode())>MAX_EVENT_JSON for raw in raws):
            raise JournalError('JOURNAL_EVENT_TOO_LARGE')
        if envelope is not None and envelope.events!=batch:
            raise JournalOrderingError('JOURNAL_ENVELOPE_EVENT_MISMATCH')
        receipt_digest=None if envelope is None else _receipt_digest(envelope.batch_id,envelope.source_digest,raws)

        stage='begin'
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if envelope is not None:
                expected=(session,batch[0].sequence,batch[-1].sequence,len(batch),envelope.source_digest,receipt_digest)
                receipt=self.db.execute(
                    'SELECT session_id,first_sequence,last_sequence,event_count,source_digest,batch_digest FROM batch_receipts WHERE batch_id=?',
                    (envelope.batch_id,)).fetchone()
                if receipt is not None:
                    if receipt!=expected:
                        raise JournalOrderingError('JOURNAL_BATCH_RECEIPT_CONFLICT')
                    # Receipt existence means the events+projection were committed
                    # in the same transaction. Audit before acknowledging replay.
                    self.audit(session_id=session)
                    stage='commit'
                    self._commit_transaction()
                    if failure_injection=='commit_ack_lost':
                        raise JournalError('INJECTED_COMMIT_ACK_LOST')
                    return {'status':'IDEMPOTENT_RECEIPT','session_id':session,
                            'revision':batch[-1].sequence,'batch_size':len(batch),
                            'batch_receipt':True,'committed':False,'actionable':False}
                reused=self.db.execute('SELECT batch_id FROM batch_receipts WHERE source_digest=?',(envelope.source_digest,)).fetchone()
                if reused is not None:
                    raise JournalOrderingError('JOURNAL_SOURCE_RECEIPT_REUSED')
                overlap=self.db.execute(
                    'SELECT batch_id FROM batch_receipts WHERE session_id=? AND NOT(last_sequence<? OR first_sequence>?) LIMIT 1',
                    (session,batch[0].sequence,batch[-1].sequence)).fetchone()
                if overlap is not None:
                    raise JournalOrderingError('JOURNAL_BATCH_RECEIPT_RANGE_OVERLAP')
            # The whole batch must be either an exact replay or entirely new.
            existing=[]
            for event,raw in zip(batch,raws):
                row=self.db.execute('SELECT event_json FROM events WHERE event_id=?',(event.event_id,)).fetchone()
                if row is None:
                    existing.append(False)
                elif row[0]==raw:
                    existing.append(True)
                else:
                    raise JournalOrderingError('JOURNAL_EVENT_ID_CONFLICT')
            if any(existing):
                if not all(existing):
                    raise JournalOrderingError('JOURNAL_BATCH_PARTIAL_DUPLICATE')
                if envelope is not None:
                    raise JournalOrderingError('JOURNAL_UNRECEIPTED_EVENT_COLLISION')
                # Exact replay: additionally verify durable state before returning.
                self.audit(session_id=session)
                stage='commit'
                self._commit_transaction()
                if failure_injection=='commit_ack_lost':
                    raise JournalError('INJECTED_COMMIT_ACK_LOST')
                return {'status':'IDEMPOTENT_DUPLICATE','session_id':session,
                        'batch_size':len(batch),'committed':False,'actionable':False}

            row=self.db.execute('SELECT revision,state_json,state_hash,last_event_hash FROM projections WHERE session_id=?',(session,)).fetchone()
            if row:
                rev,old_raw,old_digest,prev_hash=row
                if _sha(old_raw)!=old_digest:raise JournalIntegrityError('JOURNAL_PROJECTION_TAMPERED')
                tip=self.db.execute('SELECT sequence,event_hash FROM events WHERE session_id=? ORDER BY sequence DESC LIMIT 1',(session,)).fetchone()
                if tip!=(rev,prev_hash):raise JournalIntegrityError('JOURNAL_TIP_PROJECTION_MISMATCH')
                prior=json.loads(old_raw)
                if batch[0].sequence!=rev+1:raise JournalOrderingError('JOURNAL_SEQUENCE_GAP_OR_REORDER')
            else:
                rev=0;prev_hash=GENESIS;prior=None
                if batch[0].sequence!=1:raise JournalOrderingError('JOURNAL_FIRST_SEQUENCE_INVALID')

            # Reduce the COMPLETE logical batch before inserting any durable row.
            projected=prior
            for event in batch:
                projected=self.reducer(projected,event)
                if not isinstance(projected,dict):
                    raise JournalIntegrityError('JOURNAL_REDUCER_PROJECTION_INVALID')
                if projected.get('actionable') is not False or projected.get('authority')!='SYNTHETIC_FIXTURE_ONLY':
                    raise JournalIntegrityError('JOURNAL_REDUCER_AUTHORITY_VIOLATION')
                if (projected.get('revision')!=event.sequence or projected.get('last_sequence')!=event.sequence or
                        (projected.get('session_id'),projected.get('account_id'),projected.get('account_generation'))!=
                        (event.session_id,event.account_id,event.account_generation) or
                        projected.get('fight_id')!=event.fight_id):
                    raise JournalIntegrityError('JOURNAL_REDUCER_SCOPE_OR_REVISION_VIOLATION')
            state_raw=_encode(projected)
            if len(state_raw.encode())>MAX_SNAPSHOT_JSON:raise JournalError('JOURNAL_SNAPSHOT_TOO_LARGE')
            if failure_injection=='after_reduction':raise JournalError('INJECTED_CRASH_AFTER_REDUCTION')

            stage='journal'
            chain=prev_hash
            for event,raw in zip(batch,raws):
                event_hash=_sha(chain+raw)
                self.db.execute('INSERT INTO events VALUES (?,?,?,?,?,?)',
                                (event.event_id,event.session_id,event.sequence,raw,chain,event_hash))
                chain=event_hash
            if failure_injection=='after_insert':raise JournalError('INJECTED_CRASH_BEFORE_PROJECTION')

            stage='projection'
            self.db.execute('''INSERT INTO projections VALUES (?,?,?,?,?)
              ON CONFLICT(session_id) DO UPDATE SET revision=excluded.revision,
              state_json=excluded.state_json,state_hash=excluded.state_hash,last_event_hash=excluded.last_event_hash''',
              (session,projected['revision'],state_raw,_sha(state_raw),chain))
            if failure_injection=='after_projection':raise JournalError('INJECTED_CRASH_BEFORE_COMMIT')

            if envelope is not None:
                stage='receipt'
                self.db.execute('INSERT INTO batch_receipts VALUES (?,?,?,?,?,?,?,?)',
                    (envelope.batch_id,session,batch[0].sequence,batch[-1].sequence,len(batch),
                     envelope.source_digest,receipt_digest,chain))
                if failure_injection=='after_receipt':raise JournalError('INJECTED_CRASH_AFTER_RECEIPT')

            stage='commit'
            self._commit_transaction()
            # Simulates "commit was durable but acknowledgement was lost".
            if failure_injection=='commit_ack_lost':raise JournalError('INJECTED_COMMIT_ACK_LOST')
            return {'status':'COMMITTED_SIMULATED','session_id':session,
                    'revision':projected['revision'],'batch_size':len(batch),
                    'batch_receipt':envelope is not None,'committed':True,'actionable':False}
        except BaseException as exc:
            rollback_succeeded=True
            try:
                if self.db.in_transaction:self._rollback_transaction()
                else:rollback_succeeded=False
            except BaseException:
                rollback_succeeded=False
            # Reducer/order/pre-commit injected failures are safe to retry only
            # when SQLite positively rolled back. Commit-stage ambiguity is never
            # guessed: fence and require reopen/replay.
            if stage=='commit' or not rollback_succeeded:
                self._write_health='FENCED'
                self._last_write_failure={
                    'stage':stage,'error_type':type(exc).__name__,
                    'rollback_succeeded':rollback_succeeded,
                    'batch_size':len(batch),'revision_before':batch[0].sequence-1,
                    'attempted_revision':batch[-1].sequence,
                }
                if isinstance(exc,JournalPersistenceError):raise
                raise JournalPersistenceError(
                    f'JOURNAL_PERSISTENCE_UNCERTAIN:{stage}:{type(exc).__name__}',
                    stage=stage,rollback_succeeded=rollback_succeeded) from exc
            raise

    def audit(self,*,session_id:str|None=None)->dict:
        # A multi-statement audit needs one SQLite snapshot; concurrent writers
        # must not make the journal appear corrupt halfway through verification.
        owns_transaction=not self.db.in_transaction
        if owns_transaction:self.db.execute('BEGIN')
        try:return self._audit_in_transaction(session_id=session_id)
        finally:
            if owns_transaction:self.db.execute('ROLLBACK')

    def _audit_in_transaction(self,*,session_id:str|None=None)->dict:
        """Recompute all event hashes/state transitions and compare projection."""
        if session_id is None:
            sessions={r[0] for r in self.db.execute('SELECT DISTINCT session_id FROM events')}
            sessions.update(r[0] for r in self.db.execute('SELECT session_id FROM projections'))
        else:sessions={session_id}
        total=0
        for session in sorted(sessions):
            old=None;prev=GENESIS;seq=0
            cursor=self.db.execute('SELECT event_json,prev_hash,event_hash,sequence FROM events WHERE session_id=? ORDER BY sequence',(session,))
            for raw,claimed_prev,claimed_hash,n in cursor:
                if seq>=MAX_AUDIT_EVENTS_PER_SESSION:raise JournalIntegrityError('JOURNAL_AUDIT_LIMIT_EXCEEDED')
                if n!=seq+1 or claimed_prev!=prev or _sha(prev+raw)!=claimed_hash:
                    raise JournalIntegrityError('JOURNAL_EVENT_CHAIN_INVALID')
                try:event=_deserialize(raw)
                except (ValueError,TypeError,KeyError,json.JSONDecodeError) as e:
                    raise JournalIntegrityError('JOURNAL_EVENT_PAYLOAD_INVALID') from e
                if event.sequence!=n or event.session_id!=session:
                    raise JournalIntegrityError('JOURNAL_EVENT_SCOPE_INVALID')
                try:old=self.reducer(old,event)
                except (ValueError,KeyError,TypeError) as e:
                    raise JournalIntegrityError('JOURNAL_REPLAY_TRANSITION_INVALID') from e
                prev=claimed_hash;seq=n;total+=1
            stored=self.db.execute('SELECT revision,state_json,state_hash,last_event_hash FROM projections WHERE session_id=?',(session,)).fetchone()
            if not seq and stored is not None:raise JournalIntegrityError('JOURNAL_ORPHANED_PROJECTION')
            if seq:
                if stored is None:raise JournalIntegrityError('JOURNAL_MISSING_PROJECTION')
                rev,raw,digest,last=stored
                expected=_encode(old)
                if rev!=seq or raw!=expected or digest!=_sha(raw) or last!=prev:
                    raise JournalIntegrityError('JOURNAL_PROJECTION_REPLAY_MISMATCH')
        receipt_rows=self.db.execute(
            'SELECT batch_id,session_id,first_sequence,last_sequence,event_count,source_digest,batch_digest,last_event_hash FROM batch_receipts ORDER BY session_id,first_sequence'
        ).fetchall()
        claimed:dict[str,set[int]]={}
        for batch_id,session,first,last,count,source_digest,batch_digest,last_hash in receipt_rows:
            if not isinstance(batch_id,str) or not batch_id or len(source_digest)!=64 or any(c not in '0123456789abcdef' for c in source_digest):
                raise JournalIntegrityError('JOURNAL_BATCH_RECEIPT_INVALID')
            if type(first) is not int or type(last) is not int or type(count) is not int or first<=0 or last<first or count!=last-first+1:
                raise JournalIntegrityError('JOURNAL_BATCH_RECEIPT_INVALID')
            rows=self.db.execute('SELECT event_json,event_hash FROM events WHERE session_id=? AND sequence BETWEEN ? AND ? ORDER BY sequence',
                                 (session,first,last)).fetchall()
            if len(rows)!=count or rows[-1][1]!=last_hash:
                raise JournalIntegrityError('JOURNAL_BATCH_RECEIPT_EVENT_MISMATCH')
            raws=tuple(row[0] for row in rows)
            if _receipt_digest(batch_id,source_digest,raws)!=batch_digest:
                raise JournalIntegrityError('JOURNAL_BATCH_RECEIPT_DIGEST_MISMATCH')
            used=claimed.setdefault(session,set())
            span=set(range(first,last+1))
            if used & span:raise JournalIntegrityError('JOURNAL_BATCH_RECEIPT_RANGE_OVERLAP')
            used.update(span)
        return {'status':'PASS','sessions':len(sessions),'events':total,'batch_receipts':len(receipt_rows),
                'authority':'SYNTHETIC_FIXTURE_ONLY','live_ready':False,'physical_input_sent':False}

    def batch_receipt_status(self,batch_id:str)->dict|None:
        """Return an opaque receipt status without event/account payloads."""
        if not isinstance(batch_id,str) or not batch_id:
            raise ValueError('JOURNAL_BATCH_ID_REQUIRED')
        row=self.db.execute('SELECT event_count,first_sequence,last_sequence,source_digest,batch_digest FROM batch_receipts WHERE batch_id=?',(batch_id,)).fetchone()
        if row is None:return None
        count,first,last,source_digest,batch_digest=row
        return {'status':'DURABLE_SYNTHETIC_RECEIPT','event_count':count,'first_sequence':first,'last_sequence':last,
                'source_digest':source_digest,'batch_digest':batch_digest,'authority':'SYNTHETIC_FIXTURE_ONLY',
                'live_ready':False,'actionable':False}

    def audited_evidence(self, session_ids:tuple[str,...], *, max_events_per_session:int=4096)->dict:
        """Atomically audit and read several sessions for diagnostic consumers."""
        if (not isinstance(session_ids,tuple) or not 1<=len(session_ids)<=16
            or any(not isinstance(s,str) or not 1<=len(s)<=100 for s in session_ids)
            or len(set(session_ids))!=len(session_ids)):
            raise ValueError('JOURNAL_SESSION_SET_INVALID')
        if type(max_events_per_session) is not int or not 1<=max_events_per_session<=MAX_AUDIT_EVENTS_PER_SESSION:
            raise ValueError('JOURNAL_EVIDENCE_LIMIT_INVALID')
        owns_transaction=not self.db.in_transaction
        if owns_transaction:self.db.execute('BEGIN')
        try:
            audit=self.audit()
            views={}
            for session in session_ids:
                count=self.db.execute('SELECT COUNT(*) FROM events WHERE session_id=?',(session,)).fetchone()[0]
                if count>max_events_per_session:
                    raise JournalError('JOURNAL_EVIDENCE_LIMIT_EXCEEDED')
                rows=self.db.execute('SELECT event_json FROM events WHERE session_id=? ORDER BY sequence',(session,)).fetchall()
                try:
                    evidence=tuple(_deserialize(row[0]) for row in rows)
                except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                    raise JournalIntegrityError('JOURNAL_EVENT_PAYLOAD_INVALID') from exc
                views[session]={'snapshot':self.snapshot(session),'events':evidence}
            return {'audit':audit,'views':views,'authority':'SYNTHETIC_FIXTURE_ONLY','actionable':False}
        finally:
            if owns_transaction:self.db.execute('ROLLBACK')
