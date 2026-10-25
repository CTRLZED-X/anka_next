"""Passive local observer. No game kernel, network or execution imports."""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty, Full
from threading import RLock, Thread, Event, current_thread
from time import monotonic, monotonic_ns
from uuid import uuid4
import json
import re

from anka_contracts.diagnostics import DiagnosticEvent, now_utc
from anka_observability.redaction import sanitize,has_diagnostic_truncation


DIAGNOSTIC_EVENT_ID_RE=re.compile(r'evt-[A-Za-z0-9][A-Za-z0-9_.-]{0,111}')
DIAGNOSTIC_INVOCATION_ID_RE=re.compile(r'inv-[A-Za-z0-9][A-Za-z0-9_.-]{0,95}')
DIAGNOSTIC_RUN_ID_RE=re.compile(r'run-[A-Za-z0-9][A-Za-z0-9_.-]{0,95}')


def is_priority_event(event:DiagnosticEvent)->bool:
    """Pure priority classification shared by recorder and bundle verifier.

    Keeping this predicate outside LocalDiagnostics prevents the exporter/verifier
    from silently drifting away from the recorder's retention policy.
    """
    if event.severity in frozenset({'ERROR','CRITICAL','SAFETY','SETTLEMENT'}):return True
    if event.evidence_class in frozenset({'AUTHORITY_COMMITTED','CONFLICTING','MISSING'}):return True
    if event.failure_code or event.physical_input_state:return True
    if event.event_name=='decision.plan_result':
        return event.payload.get('disposition') in ('WAIT','NO_ACTION','FAULT')
    return any(token in event.event_name for token in (
        '.requested','.admitted','.input_sent','.ready_observed','.committed',
        '.settled','.barrier_satisfied','.turn_owner_proved','.frame_created',
        '.phase_changed','.recovery_','.blocked','.failed','.rejected',
    ))


class NullDiagnostics:
    def emit(self,event:DiagnosticEvent)->str:
        return 'UNAVAILABLE'


@dataclass(frozen=True, slots=True)
class FrozenDiagnostics:
    """Immutable observer view used by incident export.

    Export/analysis must never hold the live recorder lock or read a half-mutated
    ring/snapshot set.  This object is observer evidence only.
    """
    folder: Path
    invocation_id: str
    run_id: str
    recent: tuple[dict, ...]
    priority: tuple[dict, ...]
    pinned: tuple[dict, ...]
    dropped: int
    recent_overwrites: int
    priority_overwrites: int
    pinned_context_omissions: int
    sanitization_truncations: int
    errors: tuple[str, ...]
    snapshots: dict
    available: bool
    max_recent: int
    max_priority: int
    max_pinned: int
    journal_queue_drops: int = 0
    priority_journal_queue_drops: int = 0
    journal_pending: int = 0
    priority_journal_pending: int = 0
    source_tail_uncertain: bool = False


class LocalDiagnostics:
    """Best-effort bounded recorder; NEVER an authoritative gameplay ledger.

    The in-memory flight recorder is deliberately independent from journal
    persistence.  A disk/path failure degrades shareability, but it must not erase
    the evidence already needed to explain the failure that caused the export.

    Persistent journals are written by a bounded background writer.  Runtime
    producers only sanitize, retain bounded memory evidence and attempt a
    non-blocking enqueue; a slow filesystem therefore cannot stall Capture,
    Protocol, Canonical, Workflow, Decision or Execution.  The independent
    priority queue gives safety/settlement evidence reserved persistence capacity.
    """
    _PRIORITY_SEVERITIES=frozenset({'ERROR','CRITICAL','SAFETY','SETTLEMENT'})
    _PRIORITY_EVIDENCE=frozenset({'AUTHORITY_COMMITTED','CONFLICTING','MISSING'})
    _WRITER_IDLE_SECONDS=0.20

    def __init__(self,root:Path,*,run_id:str|None=None,invocation_id:str|None=None,
                 max_recent:int=1000,max_priority:int=256,max_pinned:int=256,pin_window:int=32,
                 max_journal_bytes:int=2097152,max_priority_journal_bytes:int=262144,journal_queue_capacity:int=2048):
        if type(max_recent) is not int or max_recent < 1: raise ValueError('INVALID_DIAGNOSTIC_RECENT_CAPACITY')
        if type(max_priority) is not int or max_priority < 1: raise ValueError('INVALID_DIAGNOSTIC_PRIORITY_CAPACITY')
        if type(max_pinned) is not int or max_pinned < 1: raise ValueError('INVALID_DIAGNOSTIC_PINNED_CAPACITY')
        if type(pin_window) is not int or pin_window < 1 or pin_window > max_pinned:
            raise ValueError('INVALID_DIAGNOSTIC_PIN_WINDOW')
        if type(journal_queue_capacity) is not int or journal_queue_capacity < 1:
            raise ValueError('INVALID_DIAGNOSTIC_JOURNAL_QUEUE_CAPACITY')
        if type(max_journal_bytes) is not int or max_journal_bytes < 1:
            raise ValueError('INVALID_DIAGNOSTIC_JOURNAL_LIMIT')
        if type(max_priority_journal_bytes) is not int or max_priority_journal_bytes < 1:
            raise ValueError('INVALID_DIAGNOSTIC_PRIORITY_JOURNAL_LIMIT')
        self.root=Path(root)
        self.invocation_id=invocation_id or 'inv-'+uuid4().hex
        self.run_id=run_id or 'run-'+uuid4().hex
        if DIAGNOSTIC_INVOCATION_ID_RE.fullmatch(self.invocation_id) is None:
            raise ValueError('INVALID_DIAGNOSTIC_INVOCATION_ID')
        if DIAGNOSTIC_RUN_ID_RE.fullmatch(self.run_id) is None:
            raise ValueError('INVALID_DIAGNOSTIC_RUN_ID')
        self.folder=self.root/'runs'/self.run_id
        self.max_journal_bytes=max_journal_bytes
        self.max_priority_journal_bytes=max_priority_journal_bytes
        self.recent=deque(maxlen=max_recent)
        self.priority=deque(maxlen=max_priority)
        # Incident pins preserve the context immediately before the first
        # occurrence of a distinct anomaly signature. Unlike rings, pins never
        # overwrite older context; exhaustion is explicit evidence loss.
        self.pinned=deque(maxlen=max_pinned)
        self._pin_window=pin_window
        self._pinned_trigger_keys:set[tuple[object,...]]=set()
        # This is only a diagnostic dedup index, not gameplay state. Keep it
        # bounded independently of the pinned evidence reserve so a very long run
        # with many unique anomaly signatures cannot grow observer memory forever.
        self._pinned_trigger_key_order=deque(maxlen=max(64,max_pinned*4))
        self._seq=0
        self._last_monotonic_ns=0
        self.dropped=0
        self.recent_overwrites=0
        self.priority_overwrites=0
        self.pinned_context_omissions=0
        self.sanitization_truncations=0
        self.journal_queue_drops=0
        self.priority_journal_queue_drops=0
        self.errors=[]
        self._lock=RLock()
        self.snapshots={}
        self._journal_queue:Queue[tuple[Path,str]]=Queue(maxsize=journal_queue_capacity)
        self._priority_journal_queue:Queue[tuple[Path,str]]=Queue(maxsize=max(1,journal_queue_capacity//4))
        self._journal_reserved_bytes=0
        self._priority_journal_reserved_bytes=0
        self._writer:Thread|None=None
        # `available` means persistent run storage is writable.  Memory evidence
        # may still be retained when this is false.
        self.available=True
        self._finished_state: str | None = None
        try:
            self.folder.mkdir(parents=True,exist_ok=False)
            (self.folder/'run_state.json').write_text(json.dumps({'run_id':self.run_id,'invocation_id':self.invocation_id,'state':'RUNNING','started_utc':now_utc()},indent=2)+'\n',encoding='utf8')
        except OSError as exc:
            self.available=False
            self.errors.append('RUN_STORAGE_UNAVAILABLE:'+type(exc).__name__)

    @staticmethod
    def _is_priority(event:DiagnosticEvent)->bool:
        return is_priority_event(event)

    def _append_memory_unlocked(self,obj:dict,*,priority:bool)->None:
        if len(self.recent)==self.recent.maxlen:self.recent_overwrites+=1
        self.recent.append(obj)
        if priority:
            if len(self.priority)==self.priority.maxlen:self.priority_overwrites+=1
            self.priority.append(obj)

    @staticmethod
    def _is_incident_trigger(event:DiagnosticEvent)->bool:
        if event.severity in ('ERROR','CRITICAL'):return True
        if event.failure_code:return True
        if event.physical_input_state=='MAY_HAVE_SENT':return True
        if event.evidence_class in ('MISSING','CONFLICTING'):return True
        return any(token in event.event_name for token in ('.blocked','.failed','.rejected','.outcome_missing'))

    def _pin_context_unlocked(self,event:DiagnosticEvent)->None:
        """Pin a bounded pre-failure window once per anomaly signature.

        Repeated heartbeats of the same failure class do not consume the reserve.
        The key intentionally excludes action_id so one noisy action family cannot
        crowd out every other failure class in a long-running mission.
        """
        key=(event.failure_code or event.event_name,event.boundary,event.account_id,event.fight_epoch)
        if key in self._pinned_trigger_keys:return
        if len(self._pinned_trigger_key_order)==self._pinned_trigger_key_order.maxlen:
            expired=self._pinned_trigger_key_order.popleft()
            self._pinned_trigger_keys.discard(expired)
        self._pinned_trigger_key_order.append(key)
        self._pinned_trigger_keys.add(key)
        existing={row.get('event_id') for row in self.pinned}
        for row in list(self.recent)[-self._pin_window:]:
            event_id=row.get('event_id')
            if event_id in existing:continue
            if len(self.pinned)>=self.pinned.maxlen:
                self.pinned_context_omissions+=1
                continue
            self.pinned.append(row);existing.add(event_id)

    @staticmethod
    def _line(obj:dict)->str:
        return json.dumps(obj,sort_keys=True,ensure_ascii=True,separators=(',',':'))+'\n'

    def _note_writer_error(self,code:str)->None:
        with self._lock:
            self.available=False
            if code not in self.errors:
                self.errors.append(code)
                if len(self.errors)>64:del self.errors[:-64]

    def _write_journal_task(self,path:Path,encoded:str)->None:
        try:
            with path.open('a',encoding='utf8') as out:out.write(encoded)
        except Exception as exc:
            # The observer must absorb filesystem/codec/runtime faults.  Gameplay
            # authority cannot depend on whether a diagnostic journal succeeded.
            self._note_writer_error('JOURNAL_WRITE_FAILED:'+type(exc).__name__)

    def _writer_loop(self)->None:
        """Drain priority evidence first; exit after a short idle period.

        The worker never calls gameplay code and never owns gameplay authority.
        It is a daemon so pathological filesystem shutdown cannot prevent process
        termination.  `finish()` performs only a bounded drain wait.
        """
        while True:
            task=None;queue=None
            try:
                task=self._priority_journal_queue.get_nowait();queue=self._priority_journal_queue
            except Empty:
                try:
                    task=self._journal_queue.get(timeout=self._WRITER_IDLE_SECONDS);queue=self._journal_queue
                except Empty:
                    # Coordinate the idle-exit decision with producers.  If a
                    # producer queued work while this thread was waiting, it is
                    # visible under the same lock and we continue draining.
                    with self._lock:
                        if self._priority_journal_queue.empty() and self._journal_queue.empty():
                            self._writer=None
                            return
                    continue
            try:
                if self.available and task is not None:
                    self._write_journal_task(*task)
            except Exception as exc:
                # Defensive second line: even a monkey-patched or future writer
                # implementation may fail outside `_write_journal_task`.
                self._note_writer_error('JOURNAL_WORKER_FAILED:'+type(exc).__name__)
            finally:
                if queue is not None:queue.task_done()

    @staticmethod
    def _drain_queue_without_writing(queue:Queue)->None:
        while True:
            try:queue.get_nowait()
            except Empty:return
            else:queue.task_done()

    def _ensure_writer_unlocked(self)->None:
        if not self.available:return
        writer=self._writer
        if writer is not None and writer.is_alive():return
        try:
            writer=Thread(target=self._writer_loop,name='anka-diagnostics-journal',daemon=True)
            self._writer=writer
            writer.start()
        except Exception as exc:
            self._writer=None;self.available=False
            code='JOURNAL_WRITER_START_FAILED:'+type(exc).__name__
            if code not in self.errors:self.errors.append(code)
            # No writer exists to acknowledge queued tasks. Discard only the
            # persistent copies; bounded in-memory evidence is already retained.
            self._drain_queue_without_writing(self._priority_journal_queue)
            self._drain_queue_without_writing(self._journal_queue)

    def _enqueue_journal_unlocked(self,encoded:str,*,priority:bool)->tuple[bool,bool]:
        """Non-blocking journal admission.

        Returns `(general_accepted, priority_accepted)`.  Reserved byte counters
        are advanced at enqueue time, so journal size limits remain deterministic
        even when the writer is behind.
        """
        if not self.available:return False,False
        raw_bytes=len(encoded.encode('utf8'))
        general=False;priority_ok=not priority
        if self._journal_reserved_bytes+raw_bytes<=self.max_journal_bytes:
            try:
                self._journal_queue.put_nowait((self.folder/'events.jsonl',encoded))
                self._journal_reserved_bytes+=raw_bytes;general=True
            except Full:
                self.journal_queue_drops+=1
        else:
            self.journal_queue_drops+=1
        if priority:
            if self._priority_journal_reserved_bytes+raw_bytes<=self.max_priority_journal_bytes:
                try:
                    self._priority_journal_queue.put_nowait((self.folder/'priority_events.jsonl',encoded))
                    self._priority_journal_reserved_bytes+=raw_bytes;priority_ok=True
                except Full:
                    self.priority_journal_queue_drops+=1
            else:
                self.priority_journal_queue_drops+=1
        if general or (priority and priority_ok):
            self._ensure_writer_unlocked()
            if not self.available:return False,False
        return general,priority_ok

    def record(self,name:str,severity:str='INFO',*,boundary:str|None=None,failure_code:str|None=None,
               payload:dict|None=None,**ids)->str:
        """Application convenience facade; all events still use versioned DTOs.

        Callers may repeat run/invocation correlation IDs only if they exactly
        match this recorder.  This prevents a helpful caller from accidentally
        causing a duplicate-key TypeError and silently losing the event.
        """
        with self._lock:
            if self._finished_state is not None:return 'DROPPED'
            supplied_run=ids.pop('run_id',self.run_id)
            supplied_invocation=ids.pop('invocation_id',self.invocation_id)
            if supplied_run!=self.run_id or supplied_invocation!=self.invocation_id:
                self.dropped+=1
                return 'DROPPED'
            self._seq+=1;seq=self._seq
            try:
                event=DiagnosticEvent(1,'evt-'+uuid4().hex,name,severity,now_utc(),monotonic_ns(),seq,
                    self.invocation_id,self.run_id,failure_code=failure_code,boundary=boundary,
                    payload=sanitize(payload or {}),**ids)
            except ValueError as exc:
                self.dropped+=1
                # Contract ValueErrors use stable non-secret reason codes. Keep
                # the reason so a silently malformed producer is diagnosable.
                code='EVENT_CONSTRUCTION_REJECTED:'+re.sub(r'[^A-Z0-9_:.-]','_',str(exc).upper())[:96]
                if code not in self.errors:self.errors.append(code)
                return 'DROPPED'
            except TypeError:
                self.dropped+=1
                if 'EVENT_CONSTRUCTION_TYPE_REJECTED' not in self.errors:self.errors.append('EVENT_CONSTRUCTION_TYPE_REJECTED')
                return 'DROPPED'
            except Exception as exc:
                # `record()` is the convenience boundary used by startup and
                # several subsystem facades.  Even a pathological mapping/object
                # passed as diagnostic payload must not acquire control authority
                # by throwing out of sanitization or DTO construction.
                self.dropped+=1
                code='OBSERVER_RECORD_FAILED:'+type(exc).__name__.upper()
                if code not in self.errors:
                    self.errors.append(code)
                    if len(self.errors)>64:del self.errors[:-64]
                return 'UNAVAILABLE'
            return self._emit_unlocked(event)

    def emit(self,event:DiagnosticEvent)->str:
        """Accept an already-built event without surrendering producer ordering.

        `LocalDiagnostics` is the sole ordering authority for one run.  External
        events therefore have to advance its producer sequence monotonically and
        cannot reuse an event id that is still present in the bounded recorder.
        A malformed external producer is diagnostic evidence corruption, not a
        reason to perturb gameplay.
        """
        with self._lock:
            if self._finished_state is not None:return 'DROPPED'
            if not isinstance(event,DiagnosticEvent):
                self.dropped+=1;return 'DROPPED'
            # Reject malformed external evidence before it can poison an otherwise
            # verifier-clean incident. Locally-recorded events use generated IDs
            # and now_utc(), so this only constrains foreign producers.
            if DIAGNOSTIC_EVENT_ID_RE.fullmatch(event.event_id) is None:
                self.dropped+=1
                if 'EXTERNAL_EVENT_ID_INVALID' not in self.errors:self.errors.append('EXTERNAL_EVENT_ID_INVALID')
                return 'DROPPED'
            if event.parent_event_id is not None and DIAGNOSTIC_EVENT_ID_RE.fullmatch(event.parent_event_id) is None:
                self.dropped+=1
                if 'EXTERNAL_PARENT_EVENT_ID_INVALID' not in self.errors:self.errors.append('EXTERNAL_PARENT_EVENT_ID_INVALID')
                return 'DROPPED'
            try:
                stamp=datetime.fromisoformat(event.occurred_utc.replace('Z','+00:00'))
                if stamp.tzinfo is None:raise ValueError('naive')
            except (AttributeError,TypeError,ValueError):
                self.dropped+=1
                if 'EXTERNAL_EVENT_TIMESTAMP_INVALID' not in self.errors:self.errors.append('EXTERNAL_EVENT_TIMESTAMP_INVALID')
                return 'DROPPED'
            if event.producer_seq<=self._seq:
                self.dropped+=1
                if 'EXTERNAL_EVENT_SEQUENCE_STALE' not in self.errors:self.errors.append('EXTERNAL_EVENT_SEQUENCE_STALE')
                return 'DROPPED'
            if (any(row.get('event_id')==event.event_id for row in self.recent)
                    or any(row.get('event_id')==event.event_id for row in self.priority)
                    or any(row.get('event_id')==event.event_id for row in self.pinned)):
                self.dropped+=1
                if 'EXTERNAL_EVENT_ID_DUPLICATE' not in self.errors:self.errors.append('EXTERNAL_EVENT_ID_DUPLICATE')
                return 'DROPPED'
            previous_seq=self._seq
            self._seq=event.producer_seq
            status=self._emit_unlocked(event)
            retained=bool(self.recent and self.recent[-1].get('event_id')==event.event_id)
            if not retained:self._seq=previous_seq
            return status

    def _emit_unlocked(self,event:DiagnosticEvent)->str:
        if not isinstance(event,DiagnosticEvent):
            self.dropped+=1;return 'DROPPED'
        # A per-run recorder must not accept foreign-run evidence.  Mixing two
        # invocations can manufacture a false causal chain in postmortem analysis.
        if event.invocation_id!=self.invocation_id or event.run_id!=self.run_id:
            self.dropped+=1;return 'DROPPED'
        if event.monotonic_ns < self._last_monotonic_ns:
            self.dropped+=1
            if 'EVENT_MONOTONIC_REGRESSION' not in self.errors:self.errors.append('EVENT_MONOTONIC_REGRESSION')
            return 'DROPPED'
        try:
            obj=sanitize(event.to_dict())
            if has_diagnostic_truncation(obj):self.sanitization_truncations+=1
            encoded=self._line(obj)
            if len(encoded.encode('utf8'))>8192:
                self.dropped+=1;return 'DROPPED'
            self._last_monotonic_ns=event.monotonic_ns
            priority=self._is_priority(event)
            self._append_memory_unlocked(obj,priority=priority)
            if self._is_incident_trigger(event):self._pin_context_unlocked(event)
            if not self.available:
                return 'UNAVAILABLE'
            general_ok,priority_ok=self._enqueue_journal_unlocked(encoded,priority=priority)
            if general_ok:return 'RECORDED'
            # Ordinary persistence could not accept this event.  The event still
            # exists in bounded memory and, for priority evidence, may also be in
            # the independent priority lane.  Mark completeness loss explicitly.
            self.dropped+=1
            return 'DROPPED' if priority_ok or self.available else 'UNAVAILABLE'
        except Exception as exc:
            self.dropped+=1
            code='OBSERVER_EMIT_FAILED:'+type(exc).__name__
            if code not in self.errors:self.errors.append(code)
            return 'UNAVAILABLE'

    def register_snapshot(self,name:str,value:dict) -> str:
        """Retain one bounded sanitized diagnostic snapshot for incident export."""
        with self._lock:
            if self._finished_state is not None:return 'DROPPED'
            if not isinstance(name,str) or not re.fullmatch(r'[a-z][a-z0-9_]{1,47}',name):return 'DROPPED'
            try:
                clean=sanitize(value)
                encoded=json.dumps(clean,sort_keys=True,ensure_ascii=True,separators=(',',':')).encode('utf8')
                if len(encoded)>32768 or len(self.snapshots)>=16 and name not in self.snapshots:
                    self.dropped+=1;return 'DROPPED'
                self.snapshots[name]=clean
                return 'RECORDED' if self.available else 'UNAVAILABLE'
            except Exception:
                self.dropped+=1;return 'DROPPED'

    def note_error(self,code:str)->None:
        """Bounded observer-internal error note; never accepts raw exception text."""
        if not isinstance(code,str):return
        clean=re.sub(r'[^A-Z0-9_:.-]','_',code.upper())[:120]
        with self._lock:
            if clean and clean not in self.errors:
                self.errors.append(clean)
                if len(self.errors)>64:del self.errors[:-64]

    @staticmethod
    def _queue_idle(queue:Queue,deadline:float)->bool:
        # `all_tasks_done` + `unfinished_tasks` are the synchronization mechanism
        # used by Queue.join(), but with a bounded timeout so diagnostics can never
        # hang application shutdown.
        with queue.all_tasks_done:
            while queue.unfinished_tasks:
                remaining=deadline-monotonic()
                if remaining<=0:return False
                queue.all_tasks_done.wait(timeout=remaining)
        return True

    @staticmethod
    def _queue_unfinished(queue:Queue)->int:
        """Return queued + currently-writing tasks, not only Queue.qsize().

        A writer removes a task before filesystem I/O begins, so qsize() can be
        zero while one event is still unpersisted.  Incident metadata must report
        that state honestly.
        """
        with queue.all_tasks_done:
            return int(queue.unfinished_tasks)

    def flush_journals(self,timeout_seconds:float=2.0)->bool:
        if not isinstance(timeout_seconds,(int,float)) or timeout_seconds<=0:
            raise ValueError('INVALID_DIAGNOSTIC_FLUSH_TIMEOUT')
        with self._lock:
            if self.available and (not self._journal_queue.empty() or not self._priority_journal_queue.empty()):
                self._ensure_writer_unlocked()
            if not self.available:
                # If writer creation failed, `_ensure_writer_unlocked` already
                # drained queued persistence tasks. A prior writer failure will
                # drain them on its next loop; do not let observer shutdown become
                # an arbitrary multi-second delay.
                if self._writer is None:
                    self._drain_queue_without_writing(self._priority_journal_queue)
                    self._drain_queue_without_writing(self._journal_queue)
                return False
        deadline=monotonic()+float(timeout_seconds)
        priority_ok=self._queue_idle(self._priority_journal_queue,deadline)
        general_ok=self._queue_idle(self._journal_queue,deadline)
        ok=priority_ok and general_ok
        if not ok:
            self.note_error('JOURNAL_FLUSH_TIMEOUT')
        else:
            # A drained queue can leave the daemon briefly sleeping in its idle
            # receive. Join only after every task is acknowledged, and only for a
            # small bounded interval, so normal cleanup cannot race a late writer
            # while a pathological filesystem can never hang application exit.
            with self._lock:
                writer=self._writer
            if writer is not None and writer is not current_thread():
                writer.join(timeout=self._WRITER_IDLE_SECONDS+0.05)
        return ok

    def freeze(self)->FrozenDiagnostics:
        """Atomically copy the bounded observer state, then release the lock."""
        with self._lock:
            return FrozenDiagnostics(
                self.folder,self.invocation_id,self.run_id,tuple(self.recent),tuple(self.priority),tuple(self.pinned),
                self.dropped,self.recent_overwrites,self.priority_overwrites,self.pinned_context_omissions,self.sanitization_truncations,tuple(self.errors),
                dict(self.snapshots),self.available,self.recent.maxlen or 0,self.priority.maxlen or 0,self.pinned.maxlen or 0,
                self.journal_queue_drops,self.priority_journal_queue_drops,
                self._queue_unfinished(self._journal_queue),self._queue_unfinished(self._priority_journal_queue),False,
            )

    def finish(self,state:str='CLOSED') -> None:
        if state not in ('CLOSED','BLOCKED','FAILED','INTERRUPTED'):raise ValueError('INVALID_FINAL_STATE')
        with self._lock:
            if self._finished_state is not None:return
            self._finished_state=state
        # Never keep the live recorder lock while waiting for filesystem work.
        # A bounded wait preserves shutdown progress even if the disk stalls.
        flush_ok=self.flush_journals(timeout_seconds=2.0)
        with self._lock:
            if not self.available:return
            payload=json.dumps({
                'run_id':self.run_id,'invocation_id':self.invocation_id,'state':state,'finished_utc':now_utc(),
                'dropped_events':self.dropped,'recent_overwrites':self.recent_overwrites,
                'priority_overwrites':self.priority_overwrites,
                'pinned_context_omissions':self.pinned_context_omissions,
                'sanitization_truncations':self.sanitization_truncations,
                'journal_queue_drops':self.journal_queue_drops,
                'priority_journal_queue_drops':self.priority_journal_queue_drops,
                'journal_flush_complete':flush_ok,
            },indent=2)+'\n'
            path=self.folder/'run_state.json'

        # The final state marker is useful evidence, but it is still passive
        # observability. A pathological filesystem must not gain the power to
        # hang application shutdown. Perform the overwrite on a daemon and wait
        # only a short bounded interval. Normal local filesystems complete before
        # this returns, preserving the existing immediate-state behavior.
        outcome:list[str]=[]
        cancel_final=Event()
        temp_path=self.folder/('.run_state.final-'+uuid4().hex+'.tmp')
        def write_final_state()->None:
            try:
                temp_path.write_text(payload,encoding='utf8')
                # If the bounded caller already timed out, a late filesystem
                # completion must not mutate run truth after `finish()` returned.
                if cancel_final.is_set():
                    try:temp_path.unlink(missing_ok=True)
                    except OSError:pass
                    return
                temp_path.replace(path)
            except Exception as exc:
                outcome.append('RUN_STATE_WRITE_FAILED:'+type(exc).__name__)
                try:temp_path.unlink(missing_ok=True)
                except OSError:pass
        try:
            writer=Thread(target=write_final_state,name='anka-diagnostics-final-state',daemon=True)
            self._final_state_writer=writer
            writer.start();writer.join(timeout=0.25)
            if writer.is_alive():
                cancel_final.set()
                outcome.append('RUN_STATE_WRITE_TIMEOUT')
        except Exception as exc:
            cancel_final.set()
            outcome.append('RUN_STATE_WRITER_FAILED:'+type(exc).__name__)
        if outcome:
            with self._lock:
                self.available=False
                for code in outcome:
                    if code not in self.errors:self.errors.append(code)
                if len(self.errors)>64:del self.errors[:-64]

    def export_incident(self,code:str,*,boundary:str,detail:str='',trace_spec=None,control_state:str='UNKNOWN') -> Path:
        from anka_observability.bundle import export_incident
        # The expensive analyzer + ZIP I/O operates on a coherent frozen view and
        # therefore cannot hold the live recorder lock or delay another producer.
        frozen=self.freeze()
        try:
            return export_incident(frozen,code,boundary=boundary,detail=detail,trace_spec=trace_spec,control_state=control_state)
        except Exception as exc:
            self.note_error('INCIDENT_EXPORT_FAILED:'+type(exc).__name__)
            raise
