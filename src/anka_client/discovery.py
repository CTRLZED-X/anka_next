"""Pure client discovery and identity joins; no Windows input or imports.

Inspired by R5.198/client_inventory, with stricter anti-false-positive and
anti-PID-reuse requirements. Never derives class from the configured name.
"""
from __future__ import annotations
import hashlib
import ntpath
import re
from dataclasses import dataclass
from anka_contracts.client import AccountBinding, CharacterEvidence, WindowObservation, WindowScan

SUPPORTED_EXECUTABLES = frozenset({'dofus.exe', 'dofus unity.exe', 'dofus-dofus3.exe'})
SUPPORTED_BREEDS = frozenset({'CRA', 'ENUTROF'})
SUPPORTED_EVIDENCE_SOURCES = frozenset({'LIVE_PROTOCOL', 'UNITY_BRIDGE'})
MAX_IDENTITY_AGE_NS = 3_000_000_000


def _name_hit(name: str, title: str) -> bool:
    # Full character token, not substring ("Enu" must not match "Menu").
    return bool(re.search(r'(?<!\w)' + re.escape(name.strip()) + r'(?!\w)', title, re.IGNORECASE))


def _dofus_title(title: str) -> bool:
    return bool(re.search(r'\bdofus\b', title, re.IGNORECASE))


def _trusted_exe(window: WindowObservation) -> bool:
    return ntpath.basename(window.executable_name).casefold() in SUPPORTED_EXECUTABLES


def generation_id(window: WindowObservation) -> str:
    if min(window.hwnd, window.pid, window.process_created_100ns) <= 0:
        raise ValueError('INVALID_PROCESS_GENERATION')
    value=f'{window.hwnd}:{window.pid}:{window.process_created_100ns}'.encode('ascii')
    return 'win-' + hashlib.sha256(value).hexdigest()[:32]


def client_instance_id(window: WindowObservation) -> str:
    """Stable physical-client ID derived from the exact Windows generation."""
    gid=generation_id(window)
    return 'client-'+gid[4:20]


def _matches_generation(window: WindowObservation, identity: CharacterEvidence) -> bool:
    return (window.hwnd == identity.hwnd and window.pid == identity.pid
            and window.process_created_100ns == identity.process_created_100ns)


def _evidence_current(e: CharacterEvidence, scan: WindowScan) -> bool:
    age=scan.observed_monotonic_ns - e.observed_monotonic_ns
    return 0 <= age <= MAX_IDENTITY_AGE_NS


def bind_accounts(names: tuple[str, ...], scan: WindowScan,
                  evidence: tuple[CharacterEvidence, ...] = ()) -> tuple[AccountBinding, ...]:
    """Deterministic, read-only identity diagnosis. Zero input authorization.

    Conservative on inventory errors, ambiguous accounts, forged/stale evidence,
    window reuse, class conflicts and unexpected process images.
    """
    if len(set(n.strip().casefold() for n in names)) != len(names):
        raise ValueError('DUPLICATE_CONFIGURED_CHARACTER')
    if scan.observed_monotonic_ns <= 0:
        raise ValueError('INVALID_SCAN_CLOCK')
    windows=scan.windows
    if len({w.hwnd for w in windows}) != len(windows):
        return tuple(AccountBinding(name, 'BLOCKED', 'DUPLICATE_HWND_IN_SCAN') for name in names)
    results=[]
    for name in names:
        # An independently attested identity can bind a window without its
        # name being present in the title (some client builds omit the name).
        # Evidence alone never bypasses the trusted executable requirement.
        hints=[w for w in windows if _name_hit(name,w.title) or any(
            e.character_name.strip().casefold()==name.strip().casefold() and
            _matches_generation(w,e) and e.source in SUPPORTED_EVIDENCE_SOURCES
            for e in evidence)]
        if scan.errors:
            results.append(AccountBinding(name,'BLOCKED','INCOMPLETE_WINDOW_INVENTORY'))
            continue
        untrusted=[w for w in hints if not _trusted_exe(w)]
        if untrusted:
            results.append(AccountBinding(name,'BLOCKED','UNTRUSTED_PROCESS_IMAGE'))
            continue
        candidates=[w for w in hints if _trusted_exe(w)]
        if not candidates:
            results.append(AccountBinding(name,'BLOCKED','NO_CANDIDATE_WINDOW'))
            continue
        if len(candidates)!=1:
            results.append(AccountBinding(name,'BLOCKED','AMBIGUOUS_WINDOWS'))
            continue
        w=candidates[0]
        if min(w.hwnd,w.pid,w.process_created_100ns,w.client_width,w.client_height)<=0:
            results.append(AccountBinding(name,'BLOCKED','INVALID_WINDOW_GEOMETRY_OR_GENERATION'))
            continue
        gid=generation_id(w)
        common=dict(generation_id=gid,hwnd=w.hwnd,pid=w.pid)
        if w.minimized:
            results.append(AccountBinding(name,'BLOCKED','WINDOW_MINIMIZED',**common))
            continue
        scoped=[e for e in evidence if e.character_name.strip().casefold()==name.strip().casefold() and
                e.hwnd == w.hwnd and e.pid == w.pid]
        if not scoped:
            results.append(AccountBinding(name,'PENDING','NO_AUTHORITATIVE_CHARACTER_EVIDENCE',**common))
            continue
        exact=[e for e in scoped if _matches_generation(w,e)]
        if not exact:
            results.append(AccountBinding(name,'BLOCKED','PROCESS_GENERATION_CHANGED',**common))
            continue
        trusted=[e for e in exact if e.source in SUPPORTED_EVIDENCE_SOURCES]
        if not trusted:
            results.append(AccountBinding(name,'BLOCKED','UNTRUSTED_EVIDENCE_SOURCE',**common))
            continue
        current=[e for e in trusted if _evidence_current(e,scan)]
        if not current:
            results.append(AccountBinding(name,'BLOCKED','STALE_OR_FUTURE_IDENTITY_EVIDENCE',**common))
            continue
        if len(current) != 1:
            results.append(AccountBinding(name,'BLOCKED','AMBIGUOUS_CHARACTER_EVIDENCE',**common))
            continue
        e=current[0]
        if e.breed.strip().upper() not in SUPPORTED_BREEDS:
            results.append(AccountBinding(name,'BLOCKED','UNSUPPORTED_BREED',**common))
            continue
        results.append(AccountBinding(name,'IDENTITY_MATCHED','INDEPENDENT_IDENTITY_MATCH',
                   breed=e.breed.strip().upper(),evidence_source=e.source,**common))
    # Even apparently distinct names must never control the same physical client.
    groups={}
    for i,b in enumerate(results):
        if b.generation_id and b.state in ('IDENTITY_MATCHED','PENDING'):
            groups.setdefault(b.generation_id,[]).append(i)
    for indices in groups.values():
        if len(indices)>1:
            for i in indices:
                b=results[i]
                results[i]=AccountBinding(b.name,'BLOCKED','SHARED_WINDOW_ACROSS_ACCOUNTS',b.generation_id,b.hwnd,b.pid)
    return tuple(results)
