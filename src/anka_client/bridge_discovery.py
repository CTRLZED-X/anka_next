"""Bounded read-only discovery of the optional local Unity projection bridge.

A listening localhost port never proves account identity. This module matches
bridge health to independently observed Windows process generations and exports
only aggregate diagnostics; ports/PIDs/window handles never enter incidents.
"""
from __future__ import annotations
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from anka_contracts.client import WindowObservation
from anka_client.unity_bridge import LocalLoopbackBridgeReader


def probe_bridge_range(windows: tuple[WindowObservation, ...], *,
                       port_start: int = 8765, port_count: int = 32,
                       reader_factory: Callable[[], object] | None = None) -> dict:
    if not (1 <= port_start <= 65535) or not (1 <= port_count <= 64) or port_start + port_count - 1 > 65535:
        raise ValueError('INVALID_BRIDGE_PORT_RANGE')
    generations={(w.pid,w.process_created_100ns) for w in windows
                 if w.pid > 0 and w.process_created_100ns > 0}
    factory=reader_factory or (lambda: LocalLoopbackBridgeReader(timeout_seconds=.20))

    def one(port: int):
        try:
            health=factory().get_json(port,'/health')
            if health.get('source') != 'unity_bridge' or health.get('available') is not True:
                return None
            pid=health.get('processId'); created=health.get('processStartTime'); declared=health.get('bridgePort')
            if type(pid) is not int or type(created) is not int or type(declared) is not int or declared != port:
                return ('MALFORMED',None,False)
            generation=(pid,created)
            matched=generation if generation in generations else None
            projection=(matched is not None and health.get('status') == 'MAP_COORDINATES_READY'
                        and health.get('sourceVerified') is True
                        and type(health.get('loadedMapId')) is int)
            return ('VALID',matched,projection)
        except Exception:
            return None

    valid=ready_count=unmatched=0
    matched=[];ready=[]
    workers=min(12,port_count)
    with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='anka-bridge-probe') as pool:
        futures=[pool.submit(one,p) for p in range(port_start,port_start+port_count)]
        for future in as_completed(futures):
            result=future.result()
            if result is None:continue
            status,generation,is_ready=result
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
    if duplicates:
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
        'unmatched_healthy_bridges':unmatched,
        'projection_ready_matches':ready_unique,
        'projection_ready_duplicate_responses':max(0,ready_count-ready_unique),
        'character_identity_provided':False,
        'physical_input_permitted':False,
    }
