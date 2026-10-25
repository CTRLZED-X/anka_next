"""Bounded read-only discovery of the optional local Unity projection bridge.

A listening localhost port never proves account identity. This module matches
bridge health to independently observed Windows process generations and exports
only aggregate diagnostics; ports/PIDs/window handles never enter incidents.
"""
from __future__ import annotations
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from anka_contracts.client import WindowObservation
from anka_client.discovery import client_instance_id
from anka_client.unity_bridge import (
    EXPECTED_BRIDGE_ADAPTER, EXPECTED_BRIDGE_VERSION, LocalLoopbackBridgeReader
)


def _projection_ready_for_window(health: dict, window: WindowObservation) -> bool:
    """Require an exact HWND-bound, generation-bearing projection health record."""
    if health.get('status') != 'MAP_COORDINATES_READY' or health.get('sourceVerified') is not True:
        return False
    for key in ('loadedMapId','mapGeneration','coordinateGeneration'):
        value=health.get(key)
        if type(value) is not int or value <= 0:
            return False
    if (health.get('sourceClientWidth'),health.get('sourceClientHeight')) != (
            window.client_width,window.client_height):
        return False
    for key in ('projectionSignature','cameraFingerprint','cellGeometryFingerprint'):
        value=health.get(key)
        if type(value) is not str or not value:
            return False
    if health.get('clientInstanceId') != client_instance_id(window):
        return False
    fingerprint=health.get('windowFingerprint')
    if type(fingerprint) is not str:
        return False
    parts=fingerprint.split(':')
    if len(parts)!=5:
        return False
    try:
        hwnd,_left,_top,width,height=(int(item,10) for item in parts)
    except (TypeError,ValueError):
        return False
    return hwnd==window.hwnd and (width,height)==(window.client_width,window.client_height)


def probe_bridge_range(windows: tuple[WindowObservation, ...], *,
                       port_start: int = 8765, port_count: int = 32,
                       reader_factory: Callable[[], object] | None = None,
                       listener_owner_resolver: Callable[[int], tuple[int,int] | None] | None = None) -> dict:
    if not (1 <= port_start <= 65535) or not (1 <= port_count <= 64) or port_start + port_count - 1 > 65535:
        raise ValueError('INVALID_BRIDGE_PORT_RANGE')
    windows_by_process={}
    for w in windows:
        if w.pid > 0 and w.process_created_100ns > 0 and w.hwnd > 0:
            windows_by_process.setdefault((w.pid,w.process_created_100ns),[]).append(w)
    generations=set(windows_by_process)
    factory=reader_factory or (lambda: LocalLoopbackBridgeReader(timeout_seconds=1.0))
    # An explicitly injected reader is a deterministic test/research dependency;
    # do not silently mix it with live OS listener ownership. Production uses the
    # default loopback reader and therefore gets automatic Windows owner proof.
    if listener_owner_resolver is None and reader_factory is None and os.name == 'nt':
        from anka_client.win32_bridge_ownership import loopback_listener_owner_generation
        listener_owner_resolver=loopback_listener_owner_generation
    owner_proof_active=listener_owner_resolver is not None

    def one(port: int):
        try:
            owner_before=None
            if listener_owner_resolver is not None:
                try:
                    owner_before=listener_owner_resolver(port)
                except Exception:
                    return ('OWNER_UNVERIFIED',None,False)
                if owner_before is None:
                    return None
                if owner_before not in generations:
                    return ('OWNER_MISMATCH',None,False)
            health=factory().get_json(port,'/health')
            if health.get('source') != 'unity_bridge' or health.get('available') is not True:
                return None
            if (health.get('bridgeVersion') != EXPECTED_BRIDGE_VERSION
                    or health.get('adapter') != EXPECTED_BRIDGE_ADAPTER):
                return ('STALE_OR_FOREIGN_BRIDGE',None,False)
            pid=health.get('processId'); created=health.get('processStartTime'); declared=health.get('bridgePort')
            if type(pid) is not int or type(created) is not int or type(declared) is not int or declared != port:
                return ('MALFORMED',None,False)
            generation=(pid,created)
            if listener_owner_resolver is not None:
                try:
                    owner_after=listener_owner_resolver(port)
                except Exception:
                    return ('OWNER_UNVERIFIED',None,False)
                if owner_before != generation or owner_after != generation:
                    return ('OWNER_MISMATCH',None,False)
            matched=generation if generation in generations else None
            if matched is None:
                return ('VALID',None,False)
            candidates=windows_by_process[matched]
            # One bridge instance is process-scoped. If the same process owns
            # multiple candidate game windows, process identity alone cannot say
            # which HWND the native projection selected.
            if len(candidates)!=1:
                return ('AMBIGUOUS_WINDOW',matched,False)
            projection=_projection_ready_for_window(health,candidates[0])
            return ('VALID',matched,projection)
        except Exception:
            return None

    valid=ready_count=unmatched=0
    matched=[];ready=[];ambiguous_window_generations=set()
    listener_owner_rejections=0
    bridge_identity_rejections=0
    workers=min(12,port_count)
    with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='anka-bridge-probe') as pool:
        futures=[pool.submit(one,p) for p in range(port_start,port_start+port_count)]
        for future in as_completed(futures):
            result=future.result()
            if result is None:continue
            status,generation,is_ready=result
            if status in ('OWNER_UNVERIFIED','OWNER_MISMATCH'):
                listener_owner_rejections+=1
                continue
            if status=='STALE_OR_FOREIGN_BRIDGE':
                bridge_identity_rejections+=1
                continue
            if status=='AMBIGUOUS_WINDOW':
                valid+=1
                ambiguous_window_generations.add(generation)
                continue
            if status!='VALID':continue
            valid+=1
            if generation is None:
                unmatched+=1
                continue
            matched.append(generation)
            if is_ready:
                ready.append(generation);ready_count+=1
    match_counts=Counter(matched)
    duplicates=sum(max(0,n-1) for n in match_counts.values())
    matched_unique=len(match_counts)
    ready_unique=len(set(ready))
    expected=len(generations)
    if duplicates or ambiguous_window_generations:
        status='AMBIGUOUS_PROCESS_MATCH'
    elif expected and matched_unique==expected:
        status='COMPLETE_PROCESS_MATCH'
    elif matched_unique:
        status='PARTIAL_PROCESS_MATCH'
    else:
        status='NOT_DETECTED'
    return {
        'status':status,
        'ports_probed':port_count,
        'healthy_bridges':valid,
        'expected_process_generations':expected,
        'matched_process_generations':matched_unique,
        # Backward-compatible aggregate name, now explicitly unique.
        'process_generation_matches':matched_unique,
        'duplicate_process_generation_matches':duplicates,
        'ambiguous_window_process_generations':len(ambiguous_window_generations),
        'unmatched_healthy_bridges':unmatched,
        'projection_ready_matches':ready_unique,
        'projection_ready_duplicate_responses':max(0,ready_count-ready_unique),
        'listener_owner_proof_active':owner_proof_active,
        'listener_owner_rejections':listener_owner_rejections,
        'bridge_identity_rejections':bridge_identity_rejections,
        'character_identity_provided':False,
        'physical_input_permitted':False,
    }
