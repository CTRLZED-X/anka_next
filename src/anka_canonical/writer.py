"""Definitive M6 durable Canonical writer.

One SQLite writer serializes candidate admission, committed semantic events,
projected immutable state, batch receipts and decoder-checkpoint linkage.  It
imports contracts only; the pure StateProjector is injected by the composition root.
"""
from __future__ import annotations
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import json,sqlite3,time
from functools import wraps
from threading import RLock

from anka_contracts.canonical import CanonicalCandidate,CanonicalCommitReceipt,CanonicalEventEnvelope,CommittedBatch
from anka_contracts.evidence import EvidencePointer
from anka_contracts.protocol import CandidateCanonicalBatch
from anka_contracts.state import FieldValueProof,ActorLiveSnapshot,LiveStateSnapshot

SCHEMA=1
GENESIS='0'*64
MAX_BATCH_EVENTS=2048
MAX_EVENT_JSON=64*1024
MAX_SNAPSHOT_JSON=2*1024*1024

class CanonicalError(RuntimeError):pass
class CanonicalOrderingError(CanonicalError):pass
class CanonicalIntegrityError(CanonicalError):pass
class CanonicalAdmissionRejected(CanonicalError):pass
class CanonicalWriterFenced(CanonicalError):pass
class CanonicalCommitUncertain(CanonicalError):
    def __init__(self,receipt:CanonicalCommitReceipt):
        super().__init__('CANONICAL_COMMIT_UNCERTAIN');self.receipt=receipt

def _serialized(method):
    """Serialize one connection's public authority surface across threads."""
    @wraps(method)
    def wrapped(self,*args,**kwargs):
        with self._lock:
            if self._closed and method.__name__!='close':
                raise CanonicalWriterFenced('CANONICAL_WRITER_CLOSED')
            return method(self,*args,**kwargs)
    return wrapped

def _json(obj)->str:return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)
def _hash(text:str)->str:return sha256(text.encode('utf-8')).hexdigest()

def _source_digest(batch:CandidateCanonicalBatch)->str:
    # Stable upstream *source* identity excludes caller batch_id and decoded
    # semantic output. The same exact wire envelope set under one adapter/build
    # cannot be relabelled or reinterpreted as another durable batch.
    obj={
      'adapter_release_id':batch.adapter_release_id,'observed_client_build':batch.observed_client_build,
      'connection_id':batch.connection_id,'connection_generation':batch.connection_generation,
      'source_envelopes':[asdict(x) for x in batch.source_envelopes],
    }
    return _hash(_json(obj))

def _batch_digest(batch:CandidateCanonicalBatch,source_digest:str)->str:
    obj={
      'batch_id':batch.batch_id,'source_digest':source_digest,'decode_health':batch.decode_health,
      'candidates':[x.to_dict() for x in batch.candidates],
      'checkpoint':asdict(batch.candidate_checkpoint),'unknown_fingerprints':list(batch.unknown_fingerprints),'failure_codes':list(batch.failure_codes),
    }
    return _hash(_json(obj))

def _event_to_json(event:CanonicalEventEnvelope)->str:return _json(event.to_dict())
def _event_from_json(raw:str)->CanonicalEventEnvelope:
    obj=json.loads(raw);obj['evidence']=tuple(EvidencePointer(**x) for x in obj['evidence']);obj['payload']=tuple(tuple(x) for x in obj['payload']);return CanonicalEventEnvelope(**obj)

def _proof(obj:dict)->FieldValueProof:
    obj=dict(obj);obj['source_event_ids']=tuple(obj.get('source_event_ids',()));return FieldValueProof(**obj)
def _snapshot_from_json(raw:str)->LiveStateSnapshot:
    obj=json.loads(raw);actors=[]
    for row in obj['actors']:
        actors.append(ActorLiveSnapshot(row['actor_id'],*(_proof(row[n]) for n in ('cell','hp','max_hp','ap','mp','range','cooldowns','ready'))))
    return LiveStateSnapshot(obj['snapshot_id'],obj['account_id'],obj['client_instance_id'],obj['canonical_cursor'],obj['snapshot_revision'],obj['world_epoch'],obj['fight_epoch'],obj['turn_epoch'],
      _proof(obj['world_map']),_proof(obj['fight_id']),_proof(obj['fight_phase']),_proof(obj['turn_owner']),_proof(obj['fight_map']),tuple(actors),obj['semantic_sha256'])

def _snapshot_json(snapshot:LiveStateSnapshot)->str:
    raw=_json(snapshot.to_dict())
    if len(raw.encode())>MAX_SNAPSHOT_JSON:raise CanonicalIntegrityError('CANONICAL_SNAPSHOT_TOO_LARGE')
    return raw

class ExactReleaseAdmissionPolicy:
    """Small exact allow-list policy for qualification/composition.

    Empty by default.  Merely possessing a historical adapter never admits it.
    """
    def __init__(self,allowed=()):self.allowed=frozenset(tuple(x) for x in allowed)
    def assess(self,batch:CandidateCanonicalBatch)->tuple[bool,str]:
        if (batch.adapter_release_id,batch.observed_client_build) not in self.allowed:return False,'CANONICAL_ADAPTER_NOT_ADMITTED'
        # FRAMING_IN_PROGRESS advances only Protocol's exact decoder checkpoint;
        # it carries zero semantic candidates and therefore grants no game-state
        # fact. Rejecting it would discard TCP-fragmented framing state and make
        # ordinary split messages undecodable on the next envelope.
        if batch.decode_health not in ('SEMANTIC_CANDIDATES','FRAMING_IN_PROGRESS','OPAQUE_CERTIFIED_ZERO_SEMANTIC'):return False,'CANONICAL_PROTOCOL_HEALTH_UNSAFE'
        return True,'OK'

class CanonicalWriter:
    def __init__(self,path:Path,*,projector,admission_policy,read_only:bool=False):
        self.path=Path(path);self.projector=projector;self.admission_policy=admission_policy;self.read_only=read_only
        self._lock=RLock();self._closed=False
        self._health='READ_ONLY' if read_only else 'HEALTHY';self._last_failure=None
        if read_only:self.db=sqlite3.connect(f'file:{self.path.resolve().as_posix()}?mode=ro',uri=True,timeout=5,isolation_level=None,check_same_thread=False)
        else:
            self.path.parent.mkdir(parents=True,exist_ok=True);self.db=sqlite3.connect(str(self.path),timeout=5,isolation_level=None,check_same_thread=False)
        try:
            self.db.execute('PRAGMA busy_timeout=5000')
            if not read_only:
                for attempt in range(12):
                    try:
                        if self.db.execute('PRAGMA journal_mode=WAL').fetchone()!=('wal',):raise CanonicalIntegrityError('CANONICAL_WAL_REQUIRED')
                        break
                    except sqlite3.OperationalError as exc:
                        if 'locked' not in str(exc).lower() or attempt==11:raise
                        time.sleep(min(.01*(attempt+1),.05))
                self.db.execute('PRAGMA synchronous=FULL');self._create_schema()
            self._check_schema();self.audit()
        except BaseException:
            self.db.close();raise
    @_serialized
    def close(self):
        if not self._closed:
            self.db.close();self._closed=True
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
    def _create_schema(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute('CREATE TABLE IF NOT EXISTS canonical_version (schema INTEGER NOT NULL)')
            rows=self.db.execute('SELECT schema FROM canonical_version').fetchall()
            if not rows:
                existing={x[0] for x in self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('canonical_events','canonical_batches','canonical_snapshots')")}
                if existing:raise CanonicalIntegrityError('CANONICAL_SCHEMA_INCOMPLETE_UNVERSIONED')
                self.db.execute('''CREATE TABLE canonical_events (
                  cursor INTEGER PRIMARY KEY,event_id TEXT NOT NULL UNIQUE,account_id TEXT NOT NULL,client_instance_id TEXT NOT NULL,
                  event_json TEXT NOT NULL,prev_hash TEXT NOT NULL,event_hash TEXT NOT NULL)''')
                self.db.execute('''CREATE TABLE canonical_batches (
                  batch_id TEXT PRIMARY KEY,source_digest TEXT NOT NULL UNIQUE,adapter_release_id TEXT NOT NULL,observed_client_build TEXT NOT NULL,
                  connection_id TEXT NOT NULL,connection_generation INTEGER NOT NULL,decoder_checkpoint_sha256 TEXT NOT NULL,
                  first_cursor INTEGER,last_cursor INTEGER NOT NULL,event_count INTEGER NOT NULL,batch_digest TEXT NOT NULL)''')
                self.db.execute('''CREATE TABLE canonical_snapshots (
                  account_id TEXT PRIMARY KEY,client_instance_id TEXT NOT NULL,canonical_cursor INTEGER NOT NULL,snapshot_revision INTEGER NOT NULL,
                  snapshot_json TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL)''')
                self.db.execute('INSERT INTO canonical_version(schema) VALUES (?)',(SCHEMA,))
            if self.db.in_transaction:self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise
    def _check_schema(self):
        if self.db.execute('SELECT schema FROM canonical_version').fetchall()!=[(SCHEMA,)]:raise CanonicalIntegrityError('CANONICAL_SCHEMA_VERSION_UNSUPPORTED')
        required={'canonical_events','canonical_batches','canonical_snapshots','canonical_version'}
        got={x[0] for x in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required.issubset(got):raise CanonicalIntegrityError('CANONICAL_SCHEMA_TABLE_MISSING')
    def _rollback(self)->bool:
        try:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            return True
        except BaseException:return False
    def _ensure_write(self):
        if self.read_only:raise CanonicalWriterFenced('CANONICAL_READ_ONLY')
        if self._health!='HEALTHY':raise CanonicalWriterFenced('CANONICAL_WRITER_FENCED')
    @_serialized
    def runtime_status(self)->dict:return {'schema':SCHEMA,'write_health':self._health,'last_failure':self._last_failure,'authority':'CANONICAL_DURABLE'}
    @_serialized
    def health(self)->dict:
        """Public fail-closed health surface; never grants gameplay authority."""
        status=self.runtime_status();status.update(self.audit());return status
    @_serialized
    def current_cursor(self,account_id:str|None=None)->int:
        if account_id is None:row=self.db.execute('SELECT COALESCE(MAX(cursor),0) FROM canonical_events').fetchone()
        else:row=self.db.execute('SELECT COALESCE(MAX(cursor),0) FROM canonical_events WHERE account_id=?',(account_id,)).fetchone()
        return int(row[0])
    @_serialized
    def snapshot(self,account_id:str)->LiveStateSnapshot|None:
        row=self.db.execute('SELECT snapshot_json,snapshot_sha256 FROM canonical_snapshots WHERE account_id=?',(account_id,)).fetchone()
        if row is None:return None
        if _hash(row[0])!=row[1]:raise CanonicalIntegrityError('CANONICAL_SNAPSHOT_HASH_MISMATCH')
        snap=_snapshot_from_json(row[0])
        validator=getattr(self.projector,'validate_snapshot',None)
        if not callable(validator):
            raise CanonicalIntegrityError('CANONICAL_PROJECTOR_SNAPSHOT_VALIDATOR_REQUIRED')
        try:
            validator(snap)
        except Exception as exc:
            raise CanonicalIntegrityError('CANONICAL_SNAPSHOT_SEMANTIC_HASH_MISMATCH') from exc
        return snap
    @_serialized
    def events_after(self,cursor:int,limit:int=512)->CommittedBatch:
        if type(cursor) is not int or cursor<0 or type(limit) is not int or not 1<=limit<=4096:raise ValueError('CANONICAL_READ_RANGE_INVALID')
        rows=self.db.execute('SELECT cursor,event_json FROM canonical_events WHERE cursor>? ORDER BY cursor LIMIT ?',(cursor,limit)).fetchall()
        events=tuple(_event_from_json(raw) for _,raw in rows);through=events[-1].canonical_cursor if events else cursor
        return CommittedBatch(events,cursor,through)
    def _existing_batch(self,batch:CandidateCanonicalBatch,source_digest:str,batch_digest:str):
        row=self.db.execute('SELECT source_digest,first_cursor,last_cursor,event_count,batch_digest,decoder_checkpoint_sha256 FROM canonical_batches WHERE batch_id=?',(batch.batch_id,)).fetchone()
        if row is None:
            source=self.db.execute('SELECT batch_id FROM canonical_batches WHERE source_digest=?',(source_digest,)).fetchone()
            if source is not None:raise CanonicalOrderingError('CANONICAL_SOURCE_RELABELED')
            return None
        if row[0]!=source_digest or row[4]!=batch_digest or row[5]!=batch.candidate_checkpoint.context_sha256:raise CanonicalOrderingError('CANONICAL_BATCH_ID_CONFLICT')
        return CanonicalCommitReceipt('IDEMPOTENT_DUPLICATE',batch.batch_id,row[3],row[1],row[2],False,row[5])
    def _candidate_event(self,c:CanonicalCandidate,batch:CandidateCanonicalBatch,cursor:int)->CanonicalEventEnvelope:
        eid='canonical-'+sha256(f'{batch.batch_id}:{c.candidate_id}'.encode()).hexdigest()[:32]
        return CanonicalEventEnvelope(eid,1,0,c.semantic_kind,c.account_id,c.client_instance_id,cursor,batch.adapter_release_id,batch.observed_client_build,c.evidence,c.payload,c.world_epoch,c.fight_epoch,c.turn_epoch)
    def _validate_source_scope(self,batch:CandidateCanonicalBatch)->None:
        refs=batch.source_envelopes
        if any(r.connection_id!=batch.connection_id or r.connection_generation!=batch.connection_generation for r in refs):
            raise CanonicalOrderingError('CANONICAL_SOURCE_SCOPE_MISMATCH')
        if len({r.capture_session_id for r in refs})!=1 or len({r.direction for r in refs})!=1:
            raise CanonicalOrderingError('CANONICAL_SOURCE_CAUSAL_SCOPE_MISMATCH')
        seqs=[r.producer_sequence for r in refs]
        if len(set(seqs))!=len(seqs) or seqs!=sorted(seqs):
            raise CanonicalOrderingError('CANONICAL_SOURCE_SEQUENCE_INVALID')
        if len({c.candidate_id for c in batch.candidates})!=len(batch.candidates):
            raise CanonicalOrderingError('CANONICAL_CANDIDATE_ID_DUPLICATE')

    @_serialized
    def replay(self,account_id:str)->LiveStateSnapshot|None:
        """Rebuild one account snapshot from durable committed history only."""
        if type(account_id) is not str or not account_id.startswith('acct-'):
            raise ValueError('CANONICAL_ACCOUNT_INVALID')
        rows=self.db.execute('SELECT event_json FROM canonical_events WHERE account_id=? ORDER BY cursor',(account_id,)).fetchall()
        projected=None
        for (raw,) in rows:
            projected=self.projector.prepare(projected,(_event_from_json(raw),))
        return projected

    @_serialized
    def commit_candidate_batch(self,batch:CandidateCanonicalBatch,*,failure_injection:str|None=None)->CanonicalCommitReceipt:
        self._ensure_write()
        if not isinstance(batch,CandidateCanonicalBatch):raise TypeError('CANONICAL_CANDIDATE_BATCH_REQUIRED')
        self._validate_source_scope(batch)
        valid_faults={None,'before_begin','after_begin','after_events','after_snapshot','before_commit','commit_ack_lost','after_commit_before_publish'}
        if failure_injection not in valid_faults:raise ValueError('CANONICAL_FAULT_STAGE_INVALID')
        allowed,reason=self.admission_policy.assess(batch)
        if not allowed:raise CanonicalAdmissionRejected(reason)
        if len(batch.candidates)>MAX_BATCH_EVENTS:raise CanonicalIntegrityError('CANONICAL_BATCH_TOO_LARGE')
        if batch.candidates:
            scope={(x.account_id,x.client_instance_id) for x in batch.candidates}
            if len(scope)!=1:raise CanonicalOrderingError('CANONICAL_BATCH_SCOPE_MISMATCH')
        source_digest=_source_digest(batch);batch_digest=_batch_digest(batch,source_digest);existing=self._existing_batch(batch,source_digest,batch_digest)
        if existing is not None:return existing
        if failure_injection=='before_begin':raise CanonicalError('CANONICAL_INJECTED_BEFORE_BEGIN')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if failure_injection=='after_begin':raise CanonicalError('CANONICAL_INJECTED_AFTER_BEGIN')
            start=self.current_cursor()+1;events=tuple(self._candidate_event(c,batch,start+i) for i,c in enumerate(batch.candidates))
            prev=self.db.execute('SELECT event_hash FROM canonical_events ORDER BY cursor DESC LIMIT 1').fetchone();prev_hash=prev[0] if prev else GENESIS
            for event in events:
                raw=_event_to_json(event)
                if len(raw.encode())>MAX_EVENT_JSON:raise CanonicalIntegrityError('CANONICAL_EVENT_TOO_LARGE')
                event_hash=_hash(prev_hash+'|'+raw)
                self.db.execute('INSERT INTO canonical_events(cursor,event_id,account_id,client_instance_id,event_json,prev_hash,event_hash) VALUES (?,?,?,?,?,?,?)',
                                (event.canonical_cursor,event.event_id,event.account_id,event.client_instance_id,raw,prev_hash,event_hash));prev_hash=event_hash
            if failure_injection=='after_events':raise CanonicalError('CANONICAL_INJECTED_AFTER_EVENTS')
            if events:
                account=events[0].account_id;previous=self.snapshot(account);projected=self.projector.prepare(previous,events);rawsnap=_snapshot_json(projected);snap_hash=_hash(rawsnap)
                self.db.execute('''INSERT INTO canonical_snapshots(account_id,client_instance_id,canonical_cursor,snapshot_revision,snapshot_json,snapshot_sha256)
                  VALUES (?,?,?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET client_instance_id=excluded.client_instance_id,canonical_cursor=excluded.canonical_cursor,
                  snapshot_revision=excluded.snapshot_revision,snapshot_json=excluded.snapshot_json,snapshot_sha256=excluded.snapshot_sha256''',
                  (account,projected.client_instance_id,projected.canonical_cursor,projected.snapshot_revision,rawsnap,snap_hash))
            if failure_injection=='after_snapshot':raise CanonicalError('CANONICAL_INJECTED_AFTER_SNAPSHOT')
            first=events[0].canonical_cursor if events else None;last=events[-1].canonical_cursor if events else self.current_cursor()
            self.db.execute('INSERT INTO canonical_batches(batch_id,source_digest,adapter_release_id,observed_client_build,connection_id,connection_generation,decoder_checkpoint_sha256,first_cursor,last_cursor,event_count,batch_digest) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                            (batch.batch_id,source_digest,batch.adapter_release_id,batch.observed_client_build,batch.connection_id,batch.connection_generation,batch.candidate_checkpoint.context_sha256,first,last,len(events),batch_digest))
            if failure_injection=='before_commit':raise CanonicalError('CANONICAL_INJECTED_BEFORE_COMMIT')
            if failure_injection in ('commit_ack_lost','after_commit_before_publish'):
                self.db.execute('COMMIT');self._health='FENCED';self._last_failure='CANONICAL_COMMIT_UNCERTAIN'
                receipt=CanonicalCommitReceipt('COMMIT_UNCERTAIN',batch.batch_id,len(events),first,last,True,batch.candidate_checkpoint.context_sha256,'CANONICAL_COMMIT_UNCERTAIN')
                raise CanonicalCommitUncertain(receipt)
            self.db.execute('COMMIT')
            return CanonicalCommitReceipt('COMMITTED',batch.batch_id,len(events),first,last,True,batch.candidate_checkpoint.context_sha256)
        except CanonicalCommitUncertain:raise
        except BaseException:
            if not self._rollback():self._health='FENCED';self._last_failure='CANONICAL_ROLLBACK_FAILED'
            raise
    @_serialized
    def audit(self)->dict:
        prev=GENESIS;count=0;events=[]
        for cursor,event_id,raw,stored_prev,stored_hash in self.db.execute('SELECT cursor,event_id,event_json,prev_hash,event_hash FROM canonical_events ORDER BY cursor'):
            count+=1
            if cursor!=count or stored_prev!=prev or _hash(prev+'|'+raw)!=stored_hash:raise CanonicalIntegrityError('CANONICAL_EVENT_CHAIN_INVALID')
            ev=_event_from_json(raw)
            if ev.canonical_cursor!=cursor or ev.event_id!=event_id:raise CanonicalIntegrityError('CANONICAL_EVENT_CONTRACT_MISMATCH')
            events.append(ev);prev=stored_hash
        # Batch receipts must reference only durable cursor ranges and exact counts.
        for batch_id,first,last,n in self.db.execute('SELECT batch_id,first_cursor,last_cursor,event_count FROM canonical_batches'):
            if n==0:
                if first is not None or last>count:raise CanonicalIntegrityError('CANONICAL_EMPTY_BATCH_RANGE_INVALID')
            else:
                if first is None or last-first+1!=n or not (1<=first<=last<=count):raise CanonicalIntegrityError('CANONICAL_BATCH_RANGE_INVALID')
        # Re-project each account from durable history and compare the latest stored snapshot.
        by_account={}
        for ev in events:by_account.setdefault(ev.account_id,[]).append(ev)
        stored_accounts={r[0] for r in self.db.execute('SELECT account_id FROM canonical_snapshots')}
        if stored_accounts!=set(by_account):raise CanonicalIntegrityError('CANONICAL_SNAPSHOT_ACCOUNT_SET_MISMATCH')
        for account in by_account:
            projected=self.replay(account)
            stored=self.snapshot(account)
            if stored is None or projected is None or projected.to_dict()!=stored.to_dict():raise CanonicalIntegrityError('CANONICAL_SNAPSHOT_REPLAY_MISMATCH')
        return {'status':'PASS','schema':SCHEMA,'events':count,'batches':self.db.execute('SELECT COUNT(*) FROM canonical_batches').fetchone()[0],
                'snapshots':self.db.execute('SELECT COUNT(*) FROM canonical_snapshots').fetchone()[0],'cursor':count,'write_health':self._health}
