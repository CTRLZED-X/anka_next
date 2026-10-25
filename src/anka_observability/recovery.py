"""Bounded recovery of diagnostic evidence from externally interrupted runs.

This module never reconstructs gameplay authority.  It only turns already-durable,
validated observer rows into a shareable incident whose tail is explicitly marked
uncertain because a hard process exit can occur after an action but before logging.
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import json

from anka_contracts.diagnostics import DiagnosticEvent, now_utc
from anka_observability.api import (
    FrozenDiagnostics, is_priority_event,
    DIAGNOSTIC_EVENT_ID_RE, DIAGNOSTIC_INVOCATION_ID_RE, DIAGNOSTIC_RUN_ID_RE,
)
from anka_observability.bundle import export_incident, verify_incident
from anka_observability.redaction import has_diagnostic_truncation

_TERMINAL=frozenset({'CLOSED','BLOCKED','FAILED','INTERRUPTED'})
_MAX_RECOVERY_JOURNAL_BYTES=3*1024*1024
_MAX_RECENT=1000
_MAX_PRIORITY=256


def _safe_state(folder:Path)->dict:
    try:
        state_path=folder/'run_state.json'
        if state_path.is_symlink():return {}
        # Bound the read itself, not only the parsed result. A corrupted state
        # file must not allocate arbitrary memory during startup recovery.
        with state_path.open('rb') as handle:
            raw=handle.read(65537)
        if len(raw)>65536:return {}
        obj=json.loads(raw)
        return obj if isinstance(obj,dict) else {}
    except (OSError,UnicodeDecodeError,json.JSONDecodeError,ValueError):
        return {}


def _read_rows(path:Path,*,run_id:str,invocation_id:str|None,errors:list[str])->list[dict]:
    try:
        if path.is_symlink():
            errors.append('RECOVERY_JOURNAL_SYMLINK_REJECTED');return []
        # Read at most the configured recovery tail. Reading the whole file and
        # slicing afterwards would defeat the startup memory bound for a giant
        # corrupted or sparse journal.
        with path.open('rb') as handle:
            handle.seek(0,2)
            size=handle.tell()
            truncated=size>_MAX_RECOVERY_JOURNAL_BYTES
            if truncated:
                handle.seek(-_MAX_RECOVERY_JOURNAL_BYTES,2)
                raw=handle.read(_MAX_RECOVERY_JOURNAL_BYTES)
            else:
                handle.seek(0)
                raw=handle.read(size)
    except FileNotFoundError:return []
    except OSError:
        errors.append('RECOVERY_JOURNAL_UNREADABLE');return []
    if truncated:
        # Keep the newest bounded tail. A partial first line is discarded below.
        first=raw.find(b'\n')
        raw=raw[first+1:] if first>=0 else b''
        errors.append('RECOVERY_JOURNAL_TRUNCATED_TO_BOUND')
    rows=[]
    for line in raw.splitlines():
        if not line:continue
        if len(line)>8192:
            errors.append('RECOVERY_OVERSIZED_EVENT_SKIPPED');continue
        try:
            obj=json.loads(line);event=DiagnosticEvent.from_dict(obj)
        except (json.JSONDecodeError,UnicodeDecodeError,TypeError,ValueError):
            errors.append('RECOVERY_INVALID_EVENT_SKIPPED');continue
        if (DIAGNOSTIC_EVENT_ID_RE.fullmatch(event.event_id) is None
                or (event.parent_event_id is not None and DIAGNOSTIC_EVENT_ID_RE.fullmatch(event.parent_event_id) is None)
                or DIAGNOSTIC_INVOCATION_ID_RE.fullmatch(event.invocation_id) is None
                or event.run_id is None or DIAGNOSTIC_RUN_ID_RE.fullmatch(event.run_id) is None):
            errors.append('RECOVERY_EVENT_CONTRACT_INVALID_SKIPPED');continue
        if event.run_id!=run_id:
            errors.append('RECOVERY_FOREIGN_RUN_EVENT_SKIPPED');continue
        if invocation_id is not None and event.invocation_id!=invocation_id:
            errors.append('RECOVERY_FOREIGN_INVOCATION_EVENT_SKIPPED');continue
        rows.append(event.to_dict())
    return rows


def recover_unclean_run(folder:Path)->Path|None:
    """Export one idempotent crash-recovery incident for an unclean run folder."""
    folder=Path(folder)
    if folder.is_symlink() or not folder.is_dir():return None
    state=_safe_state(folder)
    if state.get('state') in _TERMINAL:return None
    marker=folder/'unclean_recovery.json'
    if marker.exists():return None
    state_run=state.get('run_id') if isinstance(state.get('run_id'),str) else None
    if state_run is not None and state_run!=folder.name:return None
    run_id=state_run or folder.name
    if not isinstance(run_id,str) or DIAGNOSTIC_RUN_ID_RE.fullmatch(run_id) is None:return None
    state_inv=state.get('invocation_id') if isinstance(state.get('invocation_id'),str) else None
    invocation_id=(state_inv if state_inv is not None and DIAGNOSTIC_INVOCATION_ID_RE.fullmatch(state_inv) is not None else None)
    errors=['UNCLEAN_RUN_RECOVERED_TAIL_MAY_BE_MISSING']
    if state_inv is not None and invocation_id is None:errors.append('RECOVERY_STATE_INVOCATION_ID_INVALID')
    rows=_read_rows(folder/'events.jsonl',run_id=run_id,invocation_id=invocation_id,errors=errors)
    rows+=_read_rows(folder/'priority_events.jsonl',run_id=run_id,invocation_id=invocation_id,errors=errors)
    by_id={}
    for row in rows:
        event_id=row.get('event_id')
        prior=by_id.get(event_id)
        if prior is None:by_id[event_id]=row
        elif prior!=row:errors.append('RECOVERY_DUPLICATE_EVENT_CONFLICT_SKIPPED')
    if invocation_id is None:
        # Resolve invocation identity before applying any global sequence/order
        # filtering. Otherwise two valid invocations that both start at sequence 1
        # can cause one namespace to be discarded first and the survivor to be
        # falsely inferred as the only invocation in the recovered run.
        valid_invocations={
            row.get('invocation_id') for row in by_id.values()
            if isinstance(row.get('invocation_id'),str)
            and DIAGNOSTIC_INVOCATION_ID_RE.fullmatch(row.get('invocation_id')) is not None
        }
        if len(valid_invocations)!=1:return None
        invocation_id=next(iter(valid_invocations))
        by_id={event_id:row for event_id,row in by_id.items() if row.get('invocation_id')==invocation_id}
    ordered=sorted(by_id.values(),key=lambda e:(int(e.get('producer_seq',0)),int(e.get('monotonic_ns',0)),str(e.get('event_id',''))))
    rows=[];seen_seq=set();last_seq=None;last_mono=None
    for row in ordered:
        seq=(row.get('invocation_id'),row.get('run_id'),row.get('producer_seq'))
        if seq in seen_seq:
            errors.append('RECOVERY_PRODUCER_SEQ_CONFLICT_SKIPPED');continue
        try:
            event=DiagnosticEvent.from_dict(row)
            if DIAGNOSTIC_EVENT_ID_RE.fullmatch(event.event_id) is None:
                raise ValueError('event-id')
            if event.parent_event_id is not None and DIAGNOSTIC_EVENT_ID_RE.fullmatch(event.parent_event_id) is None:
                raise ValueError('parent-event-id')
            if DIAGNOSTIC_INVOCATION_ID_RE.fullmatch(event.invocation_id) is None:
                raise ValueError('invocation-id')
            if event.run_id is None or DIAGNOSTIC_RUN_ID_RE.fullmatch(event.run_id) is None:
                raise ValueError('run-id')
            stamp=datetime.fromisoformat(event.occurred_utc.replace('Z','+00:00'))
            if stamp.tzinfo is None:raise ValueError('timestamp')
        except (TypeError,ValueError):
            errors.append('RECOVERY_EVENT_CONTRACT_INVALID_SKIPPED');continue
        if last_seq is not None and event.producer_seq<=last_seq:
            errors.append('RECOVERY_PRODUCER_ORDER_INVALID_SKIPPED');continue
        if last_mono is not None and event.monotonic_ns<last_mono:
            errors.append('RECOVERY_MONOTONIC_REGRESSION_SKIPPED');continue
        seen_seq.add(seq);rows.append(row);last_seq=event.producer_seq;last_mono=event.monotonic_ns
    recent=tuple(rows[-_MAX_RECENT:])
    priority_rows=[]
    for row in rows:
        try:event=DiagnosticEvent.from_dict(row)
        except (TypeError,ValueError):continue
        if is_priority_event(event):priority_rows.append(row)
    priority=tuple(priority_rows[-_MAX_PRIORITY:])
    frozen=FrozenDiagnostics(
        folder=folder,invocation_id=invocation_id,run_id=run_id,recent=recent,priority=priority,pinned=(),
        dropped=0,recent_overwrites=max(0,len(rows)-len(recent)),priority_overwrites=max(0,len(priority_rows)-len(priority)),
        pinned_context_omissions=0,sanitization_truncations=sum(1 for row in rows if has_diagnostic_truncation(row)),errors=tuple(dict.fromkeys(errors)),snapshots={},available=True,
        max_recent=_MAX_RECENT,max_priority=_MAX_PRIORITY,max_pinned=0,source_tail_uncertain=True,
    )
    path=export_incident(frozen,'UNCLEAN_PROCESS_EXIT',boundary='observability.unclean_recovery',
        detail='Recovered from durable observer journals after a prior run ended without a terminal run-state marker. The crash tail may be missing.',
        control_state='UNKNOWN')
    verification=verify_incident(path)
    if verification.get('status')!='PASS':
        try:path.unlink(missing_ok=True)
        except OSError:pass
        # Never mark an invalid reconstruction as handled.  A later version can
        # retry the durable evidence with a stronger recovery parser.
        return None
    try:
        marker.write_text(json.dumps({'schema_version':1,'recovered_utc':now_utc(),'incident':path.name},sort_keys=True,indent=2)+'\n',encoding='utf8')
    except OSError:
        # Idempotence marker loss can cause a duplicate recovery next launch, but
        # must never make diagnostic recovery authoritative or block startup.
        pass
    return path


def recover_unclean_runs(runtime_root:Path,*,current_run_id:str,max_runs:int=4)->list[Path]:
    """Recover newest previous unclean runs with a strict scan bound."""
    runs=Path(runtime_root)/'runs'
    try:candidates=[p for p in runs.iterdir() if p.is_dir() and not p.is_symlink() and p.name!=current_run_id]
    except OSError:return []
    try:candidates.sort(key=lambda p:p.stat().st_mtime,reverse=True)
    except OSError:candidates=sorted(candidates,key=lambda p:p.name,reverse=True)
    out=[]
    # Scan more folders than we export so recent clean/already-recovered runs do
    # not permanently starve an older unclean run.  The scan itself stays bounded.
    scan_limit=max(8,min(32,max_runs*8))
    for folder in candidates[:scan_limit]:
        if len(out)>=max_runs:break
        state=_safe_state(folder)
        if state.get('state') in _TERMINAL or (folder/'unclean_recovery.json').exists():continue
        try:path=recover_unclean_run(folder)
        except Exception:continue
        if path is not None:out.append(path)
    return out
