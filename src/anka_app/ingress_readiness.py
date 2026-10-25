"""P26: privacy-preserving, opt-in passive ingress diagnostics at start.

Composition root only: no current-build semantics, canonical admission, window
binding, packets-on-disk, input driver, or authority promotion.  On Windows,
explicit interface/port configuration and a candidate window are mandatory.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from anka_app.configuration import RunConfiguration

# Only these categories/counters may leave the capture system. Neither packet
# payloads, endpoint tuples, HWNDs, PIDs nor character names are serialized.
_COUNT_FIELDS = ('selected_segments', 'queue_dropped', 'invalid_frames',
                 'rejected_frames', 'unsupported_frames')
_TRANSPORT_FIELDS = ('unanchored_directions', 'unresolved_gap_directions',
                     'observed_generations', 'reconnections',
                     'duplicate_segments', 'reordered_segments')

# Exact internal failure tokens that are safe to expose in a diagnostic receipt.
# Arbitrary exception text is never serialized.
_CAPTURE_ERROR_CODES = frozenset({
    'WINDOW_INVENTORY_INCOMPLETE',
    'DOFUS_WINDOW_COUNT_AMBIGUOUS',
    'AUTO_CAPTURE_SCOPE_UNAVAILABLE',
    'CAPTURE_SCOPE_TOO_BROAD',
    'SCAPY_NOT_INSTALLED_OPTIONAL_CAPTURE_DEPENDENCY',
    'LIVE_CAPTURE_START_FAILED',
    'NPCAP_NOT_READY',
    'CAPTURE_INTERFACE_UNRESOLVED',
    'PROCESS_GENERATION_CHANGED_BEFORE_CAPTURE',
})


def _counter(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= 10**12:
        raise ValueError('CAPTURE_RECEIPT_INVALID_COUNTER')
    return value


def _same_process_generations(before, after, *, expected_clients:int) -> bool:
    """Pure race fence for the exact Dofus window/process generations."""
    from anka_client.discovery import SUPPORTED_EXECUTABLES
    import ntpath
    try:
        def trusted(scan):
            return tuple(w for w in scan.windows
                         if ntpath.basename(w.executable_name).casefold() in SUPPORTED_EXECUTABLES)
        left=trusted(before);right=trusted(after)
        if before.errors or after.errors or len(left)!=expected_clients or len(right)!=expected_clients:
            return False
        def identity(items):
            return {(w.hwnd,w.pid,w.process_created_100ns,ntpath.basename(w.executable_name).casefold()) for w in items}
        return identity(left)==identity(right)
    except (AttributeError,TypeError,ValueError):
        return False


def _safe_receipt(raw: dict) -> dict:
    """Allowlist the entire outgoing receipt; never forward arbitrary metadata."""
    if not isinstance(raw, dict) or not isinstance(raw.get('transport'), dict):
        raise ValueError('CAPTURE_RECEIPT_INVALID')
    status = raw.get('status')
    if status not in ('UNCERTIFIED', 'TRANSPORT_UNCERTAIN', 'LOSS_DETECTED'):
        raise ValueError('CAPTURE_RECEIPT_INVALID_STATUS')
    transport = raw['transport']
    result = {field: _counter(raw[field]) for field in _COUNT_FIELDS}
    if (result['queue_dropped'] > 0) != (status == 'LOSS_DETECTED'):
        raise ValueError('CAPTURE_RECEIPT_LOSS_STATUS_CONFLICT')
    result['transport'] = {field: _counter(transport[field]) for field in _TRANSPORT_FIELDS}
    for field in ('metadata_limit_reached', 'packet_order_uncertain'):
        if type(transport.get(field)) is not bool:
            raise ValueError('CAPTURE_RECEIPT_INVALID_TRANSPORT')
        result['transport'][field] = transport[field]
    # A device reporting clean queue counts cannot prove driver or network
    # completeness. No path here returns a PASS or readiness certificate.
    result['status'] = status
    result['driver_loss_visibility'] = 'UNKNOWN'
    result['capture_source'] = 'WINDOWS_NPCAP_EXPERIMENTAL'
    result['capture_scope'] = _safe_capture_scope(raw.get('capture_scope'))
    scope_observed='capture_scope_stable' in raw
    generation_observed='process_generation_stable' in raw
    stable=raw.get('capture_scope_stable',True)
    generation_stable=raw.get('process_generation_stable',True)
    if type(stable) is not bool or type(generation_stable) is not bool:
        raise ValueError('CAPTURE_SCOPE_STABILITY_INVALID')
    result['capture_scope_stable']=stable
    result['process_generation_stable']=generation_stable
    result['capture_scope_stability_observed']=scope_observed
    result['process_generation_stability_observed']=generation_observed
    result['flow_attribution'] = _safe_attribution(raw.get('flow_attribution'))
    result['raw_evidence'] = _safe_raw_evidence(raw.get('raw_evidence'))
    result['protocol_wire'] = _safe_protocol_observation(raw.get('protocol_wire'), result['selected_segments'])
    return result



def _safe_capture_scope(value: Any) -> dict:
    if value is None:
        return {'status':'NOT_REPORTED','mode':'UNKNOWN','server_port_count':0,
                'endpoint_selector_count':0,'endpoint_values_exposed':False}
    if not isinstance(value,dict) or value.get('status') not in ('READY','NO_TCP_SCOPE'):
        raise ValueError('CAPTURE_SCOPE_RECEIPT_INVALID')
    mode=value.get('mode')
    if mode not in ('AUTO_PROCESS_TCP','EXPLICIT_OVERRIDE','TOO_MANY_SERVER_PORTS','TOO_MANY_ENDPOINT_SELECTORS'):
        raise ValueError('CAPTURE_SCOPE_RECEIPT_INVALID')
    exposed=value.get('endpoint_values_exposed')
    if exposed is not False: raise ValueError('CAPTURE_SCOPE_ENDPOINT_EXPOSURE')
    return {'status':value['status'],'mode':mode,
            'server_port_count':_counter(value.get('server_port_count',0)),
            'endpoint_selector_count':_counter(value.get('endpoint_selector_count',0)),
            'stable_processes':_counter(value.get('stable_processes',0)),
            'interface_mode':value.get('interface_mode') if value.get('interface_mode') in ('EXPLICIT_OVERRIDE','AUTO_RESOLUTION_REQUIRED') else 'UNKNOWN',
            'endpoint_values_exposed':False}


def _safe_protocol_observation(value: Any, captured_segments: int) -> dict:
    """Enforce the only safe cross-boundary protocol receipt: counters, never bytes.

    Missing observation remains visible for legacy or failed capture probes.
    All results are explicitly unverified and cannot produce gameplay authority.
    """
    base = {'status': 'NOT_OBSERVED', 'wire_only': True,
            'current_build_certified': False, 'canonical_events_emitted': 0,
            'physical_input_permitted': False}
    if value is None:
        return base
    if not isinstance(value, dict) or value.get('status') not in (
            'UNSUPPORTED_BUILD_OBSERVATION_ONLY', 'INCOMPLETE_EVIDENCE_OBSERVATION_ONLY'):
        raise ValueError('PROTOCOL_WIRE_RECEIPT_INVALID')
    keys = ('selected_segments', 'framed_messages', 'classified_observations',
            'unknown_messages', 'direction_mismatches', 'invalid_frames',
            'quarantined_streams', 'unanchored_streams')
    counters = {name: _counter(value[name]) for name in keys}
    if counters['selected_segments'] != captured_segments:
        raise ValueError('PROTOCOL_WIRE_CAPTURE_COUNT_MISMATCH')
    if (counters['classified_observations'] + counters['unknown_messages'] +
            counters['direction_mismatches'] > counters['framed_messages']):
        raise ValueError('PROTOCOL_WIRE_COUNT_CONFLICT')
    if type(value.get('packet_loss_reported')) is not bool or not value['packet_loss_reported']:
        # Scapy driver loss counters are unavailable. No live probe can
        # claim packet-loss visibility complete on the current backend.
        raise ValueError('PROTOCOL_WIRE_DRIVER_VISIBILITY_UNPROVEN')
    return {**base, 'status': 'OBSERVED_UNCERTIFIED', **counters,
            'incomplete_capture_evidence': True,
            'difference_from_historical_catalog_is_not_certified_drift': True}




def _safe_raw_evidence(value: Any) -> dict:
    # No filename/path, endpoint, character or bytes can escape this allowlist.
    if value is None:
        return {'status': 'DISABLED', 'raw_capture_saved': False}
    if not isinstance(value, dict) or value.get('status') not in (
            'RECORDED_UNCERTIFIED', 'INCOMPLETE_RECORDED'):
        raise ValueError('RAW_EVIDENCE_RECEIPT_INVALID')
    frames = _counter(value.get('frames'))
    gaps = _counter(value.get('known_recording_gaps'))
    digest = value.get('sha256')
    if (type(digest) is not str or len(digest) != 64 or
            any(c not in '0123456789abcdef' for c in digest) or
            (gaps == 0) != (value['status'] == 'RECORDED_UNCERTIFIED') or
            value.get('driver_loss_visibility') != 'UNKNOWN' or
            value.get('live_certified') is not False or
            value.get('physical_input_sent') is not False):
        raise ValueError('RAW_EVIDENCE_RECEIPT_INVALID')
    return {'status': value['status'], 'frames': frames,
            'known_recording_gaps': gaps, 'sha256': digest,
            'raw_capture_saved': True,
            'current_build_certified': False, 'driver_loss_visibility': 'UNKNOWN'}

def _safe_attribution(value: Any) -> dict:
    if value is None:
        return {'status': 'NOT_CHECKED', 'counts': {'PROVISIONAL': 0, 'AMBIGUOUS': 0, 'UNMATCHED': 0}}
    if not isinstance(value, dict) or value.get('status') not in ('NOT_ATTESTED', 'UNAVAILABLE'):
        raise ValueError('FLOW_ATTRIBUTION_INVALID')
    if value['status'] == 'UNAVAILABLE':
        return {'status': 'UNAVAILABLE', 'counts': {'PROVISIONAL': 0, 'AMBIGUOUS': 0, 'UNMATCHED': 0}}
    counts = value.get('counts')
    if not isinstance(counts, dict):
        raise ValueError('FLOW_ATTRIBUTION_INVALID')
    return {'status': 'NOT_ATTESTED', 'counts': {key: _counter(counts[key])
                                             for key in ('PROVISIONAL', 'AMBIGUOUS', 'UNMATCHED')}}


def _stable_flow_evaluation(before_windows, after_windows, before_tcp, after_tcp, flow_keys: dict) -> tuple[dict, dict]:
    """P51/P52: private candidate owners and safe aggregate count.

    P51: lossless, read-only two-boundary host/flow consistency check.

    The two non-atomic OS tables must each be individually unambiguous.  It is
    unsound to intersect the tables *first*: a duplicate or contradictory owner
    can disappear from the intersection and manufacture a unique process hint.
    Counts alone cross the diagnostics boundary; no endpoint, PID, character,
    HWND, process path, flow key, or raw evidence is returned.

    PROVISIONAL means only a stable OS process/endpoint hint, NEVER an account
    or character binding, current-build certification, or click authorization.
    """
    from anka_client.discovery import SUPPORTED_EXECUTABLES
    import ntpath

    unavailable = {'status': 'UNAVAILABLE'}
    empty_owners = {}
    if not isinstance(flow_keys, dict) or len(flow_keys) > 4096:
        return unavailable, empty_owners
    try:
        if (before_windows.errors or after_windows.errors or
                type(before_windows.observed_monotonic_ns) is not int or
                type(after_windows.observed_monotonic_ns) is not int or
                before_windows.observed_monotonic_ns <= 0 or
                not 0 <= after_windows.observed_monotonic_ns - before_windows.observed_monotonic_ns <= 30_000_000_000):
            return unavailable, empty_owners
        # Reject duplicates *before* building maps: a set would conceal them.
        def windows_by_pid(scan):
            by_pid = {}
            ambiguous_pids = set()
            seen_hwnds = set()
            for w in scan.windows:
                if (type(w.hwnd) is not int or type(w.pid) is not int or
                        type(w.process_created_100ns) is not int or
                        min(w.hwnd, w.pid, w.process_created_100ns) <= 0 or
                        w.hwnd in seen_hwnds):
                    return None
                seen_hwnds.add(w.hwnd)
                if w.pid in by_pid:
                    ambiguous_pids.add(w.pid)
                else:
                    by_pid[w.pid] = w
            for pid in ambiguous_pids:
                del by_pid[pid]
            return by_pid
        before_pids = windows_by_pid(before_windows)
        after_pids = windows_by_pid(after_windows)
        if before_pids is None or after_pids is None:
            return unavailable, empty_owners

        def window_fingerprint(w):
            return (w.hwnd, w.pid, w.process_created_100ns,
                    ntpath.basename(w.executable_name).casefold(),
                    w.client_width, w.client_height, w.dpi, w.minimized)

        stable_pids = set()
        for pid, before in before_pids.items():
            after = after_pids.get(pid)
            if after is None or window_fingerprint(before) != window_fingerprint(after):
                continue
            if (ntpath.basename(before.executable_name).casefold() not in SUPPORTED_EXECUTABLES or
                    type(before.client_width) is not int or type(before.client_height) is not int or
                    min(before.client_width, before.client_height) <= 0 or before.minimized):
                continue
            stable_pids.add(pid)

        def tcp_index(rows):
            result = {}
            for r in rows:
                endpoint = (r.local_ip, r.local_port, r.remote_ip, r.remote_port)
                result.setdefault(endpoint, []).append((r.pid, r.state))
            return result
        old = tcp_index(before_tcp)
        new = tcp_index(after_tcp)
        counts = {'PROVISIONAL': 0, 'AMBIGUOUS': 0, 'UNMATCHED': 0}
        # Private mapping consumed *only* by the P52 topology audit. No PID,
        # endpoint, flow label, or character name escapes its aggregate report.
        candidate_owners = {}
        for token, key in flow_keys.items():
            if (not isinstance(key, tuple) or len(key) != 4 or
                    type(key[0]) is not str or type(key[2]) is not str or
                    type(key[1]) is not int or type(key[3]) is not int or
                    not 0 <= key[1] <= 65535 or not 0 <= key[3] <= 65535):
                return unavailable, empty_owners
            earlier = old.get(key, ())
            later = new.get(key, ())
            # Count owner conflicts *in each original table*; never suppress a
            # conflicting PID or duplicate row merely because it disappeared.
            if len(earlier) > 1 or len(later) > 1:
                status = 'AMBIGUOUS'
            elif not earlier or not later:
                status = 'UNMATCHED'
            elif earlier[0] != later[0]:
                status = 'AMBIGUOUS' if earlier[0][0] != later[0][0] else 'UNMATCHED'
            elif earlier[0][1] != 5:
                status = 'UNMATCHED'
            elif earlier[0][0] not in stable_pids:
                status = 'UNMATCHED'
            else:
                status = 'PROVISIONAL'
            counts[status] += 1
            if status == 'PROVISIONAL':
                candidate_owners[token] = earlier[0][0]
        return {'status': 'NOT_ATTESTED', 'counts': counts}, candidate_owners
    except (AttributeError, TypeError, ValueError, OverflowError):
        return unavailable, empty_owners


def stable_flow_hints(before_windows, after_windows, before_tcp, after_tcp, flow_keys: dict) -> dict:
    """Existing P51 privacy-safe receipt; never returns candidate identities."""
    safe, _private = _stable_flow_evaluation(
        before_windows, after_windows, before_tcp, after_tcp, flow_keys)
    return safe


def stable_multi_account_topology(before_windows, after_windows, before_tcp, after_tcp,
                                  flow_keys: dict, *, expected_clients: int) -> dict:
    """P52: research-only process/socket topology, not a character identifier.

    Validates the raw two-boundary snapshots via the existing P51 path and
    preserves duplicate endpoint aliases before computing candidate counts.
    PIDs and flow keys remain internal; output is a fixed allowlist of counts.
    Multiple TCP sockets per process are normal, not separate accounts.
    """
    unavailable = {'status': 'UNAVAILABLE', 'reason': 'P52_HOST_EVIDENCE_INVALID',
                   'account_binding_verified': False, 'actionable': False}
    if type(expected_clients) is not int or not 1 <= expected_clients <= 8:
        return unavailable
    if not isinstance(flow_keys, dict) or any(
            type(token) is not str or not 1 <= len(token) <= 128
            for token in flow_keys):
        return unavailable
    receipt, candidates = _stable_flow_evaluation(
        before_windows, after_windows, before_tcp, after_tcp, flow_keys)
    if receipt.get('status') != 'NOT_ATTESTED':
        return unavailable
    # Different captured tokens pointing to the same endpoint do not represent
    # two independent process/socket witnesses. Do not count either twice.
    keys = list(flow_keys.values())
    try:
        aliases = len(keys) - len(set(keys))
    except (TypeError, ValueError):
        return unavailable
    if aliases:
        return {'status': 'BLOCKED_AMBIGUOUS', 'reason': 'P52_DUPLICATE_SOCKET_SELECTORS',
                'candidate_flows': len(keys), 'duplicate_socket_selectors': aliases,
                'account_binding_verified': False, 'actionable': False}
    per_pid = {}
    for pid in candidates.values():
        per_pid[pid] = per_pid.get(pid, 0) + 1
    distinct = len(per_pid)
    multiple = sum(n > 1 for n in per_pid.values())
    # An apparently perfect one-PID-per-flow partition remains a *process* hint
    # because titles, account names, current-client semantics, and source loss
    # have not been independently attested.
    reason = ('P52_FLOW_OWNERSHIP_AMBIGUOUS' if receipt['counts']['AMBIGUOUS'] else
              'P52_INCOMPLETE_PROCESS_CANDIDATES' if distinct < expected_clients else
              'P52_EXTRA_PROCESS_CANDIDATES' if distinct > expected_clients else
              'P52_PROCESS_TOPOLOGY_ONLY')
    return {'status': 'CANDIDATES_ONLY', 'reason': reason,
            'expected_clients': expected_clients, 'candidate_flows': len(keys),
            'provisional_flows': receipt['counts']['PROVISIONAL'],
            'ambiguous_flows': receipt['counts']['AMBIGUOUS'],
            'unmatched_flows': receipt['counts']['UNMATCHED'],
            'distinct_candidate_processes': distinct,
            'multi_socket_candidate_processes': multiple,
            'independent_character_witnesses': 0,
            'account_binding_verified': False, 'current_build_certified': False,
            'canonical_commits': 0, 'actionable': False, 'physical_input_sent': False}



def historical_character_process_topology(before_windows, after_windows, before_tcp, after_tcp,
                                          flow_keys: dict, identity_witnesses: dict,
                                          *, expected_character_names: tuple[str, ...]) -> dict:
    """P53 compose stable process/socket hints with historical character witnesses.

    This is deliberately *not* a CharacterEvidenceProvider.  It can show that a
    pinned Dofus 3.7.10.10 `jnj` observation naming a configured character was
    carried on a flow that had a stable Windows PID candidate at two host
    snapshots.  It cannot prove current-client identity, breed, capture
    completeness, or permission to act.

    The output is an allowlisted aggregate: no character names, PIDs, HWNDs,
    endpoints, flow tokens, or packet coordinates leave this boundary.
    """
    from hashlib import sha256
    from anka_contracts.historical_identity import HistoricalIdentityObservation
    from anka_protocol.adapters.historical_identity import BUILD as HISTORICAL_IDENTITY_BUILD

    unavailable = {'status':'UNAVAILABLE','reason':'P53_HOST_OR_IDENTITY_EVIDENCE_INVALID',
                   'historical_build_verified':False,'account_binding_verified':False,
                   'current_build_certified':False,'actionable':False}
    if (not isinstance(expected_character_names, tuple) or
            not 1 <= len(expected_character_names) <= 8 or
            any(type(name) is not str or not 2 <= len(name.strip()) <= 40 or name != name.strip()
                for name in expected_character_names)):
        return unavailable
    normalized=[name.casefold() for name in expected_character_names]
    if len(set(normalized)) != len(normalized):
        return unavailable
    if (not isinstance(flow_keys, dict) or not isinstance(identity_witnesses, dict) or
            len(flow_keys) > 4096 or len(identity_witnesses) > 4096):
        return unavailable
    receipt, candidates = _stable_flow_evaluation(
        before_windows, after_windows, before_tcp, after_tcp, flow_keys)
    if receipt.get('status') != 'NOT_ATTESTED':
        return unavailable
    try:
        endpoints=list(flow_keys.values())
        duplicate_selectors=len(endpoints)-len(set(endpoints))
    except (TypeError,ValueError):
        return unavailable
    if duplicate_selectors:
        return {'status':'BLOCKED_AMBIGUOUS','reason':'P53_DUPLICATE_SOCKET_SELECTORS',
                'expected_characters':len(normalized),'historical_identity_witnesses':0,
                'matched_process_character_candidates':0,'distinct_candidate_processes':0,
                'duplicate_socket_selectors':duplicate_selectors,
                'historical_build_verified':False,'account_binding_verified':False,
                'current_build_certified':False,'canonical_commits':0,
                'actionable':False,'physical_input_sent':False}

    by_expected={name.casefold():name for name in expected_character_names}
    accepted=[]
    invalid=unexpected=unowned=0
    for token,witness in identity_witnesses.items():
        if (type(token) is not str or not 1 <= len(token) <= 128 or token not in flow_keys or
                not isinstance(witness,HistoricalIdentityObservation)):
            invalid+=1; continue
        try:
            expected_digest=sha256(token.encode('utf8',errors='strict')).hexdigest()
        except UnicodeError:
            invalid+=1; continue
        ev=witness.evidence
        if (ev.protocol_build != HISTORICAL_IDENTITY_BUILD or
                ev.flow_digest != expected_digest or ev.wire_name != 'jnj' or
                witness.identity_source != 'JNJ_CHARACTER_NAME'):
            invalid+=1; continue
        norm=witness.character_name.casefold()
        if norm not in by_expected:
            unexpected+=1; continue
        pid=candidates.get(token)
        if pid is None:
            unowned+=1; continue
        accepted.append((norm,pid,token))

    # One configured character may not be claimed by two simultaneous flows;
    # one process may not be claimed by two different configured characters.
    name_counts={}
    pid_names={}
    for name,pid,_token in accepted:
        name_counts[name]=name_counts.get(name,0)+1
        pid_names.setdefault(pid,set()).add(name)
    duplicate_character_claims=sum(max(0,n-1) for n in name_counts.values())
    shared_process_claims=sum(len(names)>1 for names in pid_names.values())
    matched_names=len(name_counts)
    distinct_pids=len(pid_names)
    missing=max(0,len(normalized)-matched_names)
    if invalid or unexpected or duplicate_character_claims or shared_process_claims:
        status='BLOCKED_AMBIGUOUS';reason='P53_CHARACTER_FLOW_PROCESS_CONFLICT'
    elif unowned or missing:
        status='PARTIAL_CANDIDATES';reason='P53_HISTORICAL_IDENTITY_INCOMPLETE'
    elif receipt['counts']['AMBIGUOUS'] or receipt['counts']['UNMATCHED']:
        status='PARTIAL_CANDIDATES';reason='P53_HOST_FLOW_OWNERSHIP_INCOMPLETE'
    else:
        status='HISTORICAL_CANDIDATES_ONLY';reason='P53_HISTORICAL_IDENTITY_TOPOLOGY_ONLY'
    return {
        'status':status,'reason':reason,
        'expected_characters':len(normalized),
        'historical_identity_witnesses':len(accepted),
        'matched_process_character_candidates':matched_names,
        'distinct_candidate_processes':distinct_pids,
        'missing_character_witnesses':missing,
        'invalid_identity_witnesses':invalid,
        'unexpected_character_witnesses':unexpected,
        'unowned_identity_witnesses':unowned,
        'duplicate_character_claims':duplicate_character_claims,
        'shared_process_character_conflicts':shared_process_claims,
        'host_ambiguous_flows':receipt['counts']['AMBIGUOUS'],
        'host_unmatched_flows':receipt['counts']['UNMATCHED'],
        'historical_build_verified':True,
        'historical_identity_only':True,
        'independent_current_character_witnesses':0,
        'account_binding_verified':False,
        'current_build_certified':False,
        'canonical_commits':0,'actionable':False,'physical_input_sent':False,
    }

def _windows_sample(config: RunConfiguration) -> dict:
    """Bounded read-only live sample with internally discovered capture scope."""
    from anka_capture.windows_live import WindowsLiveCapture, capture_bounded_sample
    from anka_capture.windows_flows import WindowsTcpOwnership
    from anka_capture.windows_scope import derive_windows_capture_scope, resolve_scapy_interface
    from anka_client.win32_inventory import NativeWindowsInventory
    from anka_client.discovery import SUPPORTED_EXECUTABLES
    import ntpath

    inventory=NativeWindowsInventory(tuple(p.name for p in config.players))
    owner=WindowsTcpOwnership()
    # Capture scope is derived from a non-atomic Windows window/TCP snapshot.
    # Fence the TCP table between two exact process-generation scans before the
    # sniffer starts.  This prevents a recycled PID from widening capture to an
    # unrelated process and turns the race into an explicit diagnostic instead.
    before=inventory.scan()
    before_tcp=owner.snapshot()
    pre_capture=inventory.scan()
    if before.errors or pre_capture.errors:
        raise RuntimeError('WINDOW_INVENTORY_INCOMPLETE')
    if not _same_process_generations(before,pre_capture,expected_clients=len(config.players)):
        raise RuntimeError('PROCESS_GENERATION_CHANGED_BEFORE_CAPTURE')
    trusted_before=tuple(w for w in pre_capture.windows
                    if ntpath.basename(w.executable_name).casefold() in SUPPORTED_EXECUTABLES)
    candidate_pids={w.pid for w in trusted_before}
    if len(trusted_before) != len(config.players):
        raise RuntimeError('DOFUS_WINDOW_COUNT_AMBIGUOUS')
    scope=derive_windows_capture_scope(candidate_pids,before_tcp,override_ports=config.capture.server_ports,
                                       override_interface=config.capture.interface)
    if scope.mode in ('TOO_MANY_SERVER_PORTS','TOO_MANY_ENDPOINT_SELECTORS'):
        raise RuntimeError('CAPTURE_SCOPE_TOO_BROAD')
    if not scope.server_ports:
        raise RuntimeError('AUTO_CAPTURE_SCOPE_UNAVAILABLE')
    interface=resolve_scapy_interface(scope.local_ips,scope.interface)
    if interface is None and scope.interface is None:
        raise RuntimeError('CAPTURE_INTERFACE_UNRESOLVED')

    from anka_protocol.api import ProtocolInspector
    from anka_protocol.adapters.historical import load_reference
    build_values=[w.build_version for w in trusted_before if isinstance(w.build_version,str) and w.build_version]
    requested_build=(build_values[0] if len(build_values)==len(trusted_before) and len(set(build_values))==1
                     else 'UNVERIFIED_CURRENT_CLIENT')
    inspector=ProtocolInspector(load_reference(Path(__file__).resolve().parents[2]),
                                requested_build=requested_build)
    recorder=None
    if config.capture.save_raw_evidence:
        from anka_capture.evidence_recording import ConsentedPcapngRecorder
        recorder=ConsentedPcapngRecorder(Path(__file__).resolve().parents[2]/'runtime/evidence',
                                         server_ports=scope.server_ports)
    live=WindowsLiveCapture(interface=interface,server_ports=scope.server_ports,allowed_flows=scope.allowed_flows,evidence_recorder=recorder)
    receipt=capture_bounded_sample(interface=interface,server_ports=scope.server_ports,allowed_flows=scope.allowed_flows,
                                   duration_seconds=min(config.capture.duration_seconds,10),
                                   source=live,on_poll=inspector.consume_poll)
    receipt['capture_scope']=scope.safe_receipt()
    receipt['client_build']={'status':'CONSISTENT' if requested_build!='UNVERIFIED_CURRENT_CLIENT' else 'UNVERIFIED',
                             'version':requested_build if requested_build!='UNVERIFIED_CURRENT_CLIENT' else None}
    wire=inspector.finish()
    incomplete_wire_callback=wire.selected_segments != receipt.get('selected_segments')
    if not incomplete_wire_callback:
        receipt['protocol_wire']={key:getattr(wire,key) for key in (
            'status','requested_build','adapter_build','selected_segments','framed_messages','classified_observations','unknown_messages',
            'direction_mismatches','invalid_frames','quarantined_streams','unanchored_streams','packet_loss_reported')}
    else:
        receipt['protocol_wire']=None
    try:
        after=inventory.scan();after_tcp=owner.snapshot()
        trusted_after=tuple(w for w in after.windows
                    if ntpath.basename(w.executable_name).casefold() in SUPPORTED_EXECUTABLES)
        after_pids={w.pid for w in trusted_after}
        after_scope=derive_windows_capture_scope(after_pids,after_tcp,override_ports=config.capture.server_ports,
                                                 override_interface=config.capture.interface)
        generation_stable=_same_process_generations(before,after,expected_clients=len(config.players))
        stable_scope=(generation_stable and set(scope.allowed_flows)==set(after_scope.allowed_flows))
        receipt['process_generation_stable']=generation_stable
        receipt['capture_scope_stable']=stable_scope
        if not stable_scope:
            # A connection appeared/disappeared during the bounded window; the
            # fixed exact-flow BPF may have omitted traffic. Do not export wire
            # classification as coherent current-build evidence.
            receipt['protocol_wire']=None
        receipt['flow_attribution']=stable_flow_hints(before,after,before_tcp,after_tcp,
                                                      live.flow_keys_for_attribution())
    except Exception:
        receipt['process_generation_stable']=False
        receipt['capture_scope_stable']=False
        receipt['protocol_wire']=None
        receipt['flow_attribution']={'status':'UNAVAILABLE'}
    return receipt


def probe_start_ingress(config: RunConfiguration, host: dict, *, platform: str | None = None,
                        sample: Callable[[RunConfiguration], dict] | None = None,
                        observer=None) -> dict:
    """Run one automatic, bounded, read-only ingress observation.

    Character/account identity is intentionally not required to begin capture;
    otherwise Protocol evidence needed to establish identity could never be
    collected. Executable/process generation constrains the candidate TCP scope,
    while the resulting observations remain uncertified and non-actionable.
    """
    system=os.name if platform is None else platform
    reason=None
    if system!='nt': reason='WINDOWS_ONLY'
    elif not isinstance(host,dict) or host.get('platform')!='WINDOWS': reason='HOST_SNAPSHOT_NOT_WINDOWS'
    elif type(host.get('candidate_windows')) is not int or host['candidate_windows']<=0: reason='GAME_WINDOW_CANDIDATE_MISSING'
    elif host['candidate_windows'] != len(config.players): reason='DOFUS_WINDOW_COUNT_AMBIGUOUS'
    elif not isinstance(host.get('capture'),dict) or host['capture'].get('scapy_installed') is not True: reason='OPTIONAL_CAPTURE_DEPENDENCY_MISSING'
    elif host['capture'].get('npcap_driver') in ('NOT_DETECTED','SERVICE_PRESENT_DLLS_MISSING','PROBE_INCOMPLETE'): reason='NPCAP_NOT_READY'
    elif host['capture'].get('server_port_candidates',0)<=0 and not config.capture.server_ports: reason='DOFUS_TCP_FLOW_CANDIDATE_MISSING'
    elif host['capture'].get('interface_resolution')=='UNRESOLVED' and not config.capture.interface: reason='CAPTURE_INTERFACE_UNRESOLVED'
    if reason:
        report={'status':'SKIPPED','reason':reason,'capture_attempted':False}
    else:
        try:
            raw=(sample or _windows_sample)(config)
            receipt=_safe_receipt(raw)
            report={'status':'CAPTURED_UNCERTIFIED','reason':'CURRENT_BUILD_SEMANTICS_UNVERIFIED',
                    'capture_attempted':True,'receipt':receipt}
        except Exception as exc:
            token=str(exc) if isinstance(exc,RuntimeError) else ''
            error_code=token if token in _CAPTURE_ERROR_CODES else 'UNCLASSIFIED_CAPTURE_FAILURE'
            report={'status':'FAILED','reason':'CAPTURE_SAMPLE_FAILED',
                    'error_code':error_code,
                    'error_type':type(exc).__name__.upper(),'capture_attempted':True}
    persisted=(report.get('status')=='CAPTURED_UNCERTIFIED' and
               report.get('receipt',{}).get('raw_evidence',{}).get('raw_capture_saved') is True)
    report.update({'live_certified':False,'account_binding_verified':False,
                   'physical_input_permitted':False,'packet_payload_persisted':persisted})
    if observer is not None:
        try:
            observer.record('readiness.passive_ingress_probe',boundary='readiness.read_only_capture',
                            severity='WARNING' if report['status']=='FAILED' else 'INFO',
                            failure_code='CAPTURE_SAMPLE_FAILED' if report['status']=='FAILED' else None,
                            payload=report)
        except Exception:
            # A diagnostic sink failure cannot rewrite the result of the
            # read-only ingress probe or turn evidence collection into a crash.
            pass
    return report


def host_flow_stability_smoke() -> dict:
    """Small offline P51 regression at ordinary setup/check (no Win32 calls)."""
    from anka_contracts.client import WindowScan, WindowObservation
    from anka_capture.windows_flows import TcpEndpoint

    w = WindowObservation(51, 72, 1001, 'Dofus.exe', 'Dofus', 1280, 649, 96, False)
    before = WindowScan(10_000, (w,))
    after = WindowScan(20_000, (w,))
    endpoint = TcpEndpoint('127.0.0.1', 41234, '198.51.100.1', 40400, 72, 5)
    competing = TcpEndpoint('127.0.0.1', 41234, '198.51.100.1', 40400, 91, 5)
    flows = {'opaque': ('127.0.0.1', 41234, '198.51.100.1', 40400)}
    stable = stable_flow_hints(before, after, (endpoint,), (endpoint,), flows)
    disappeared = stable_flow_hints(before, after, (endpoint, competing), (endpoint,), flows)
    reused = stable_flow_hints(before, WindowScan(20_000, (
        WindowObservation(51, 72, 1002, 'Dofus.exe', 'Dofus', 1280, 649, 96, False),
    )), (endpoint,), (endpoint,), flows)
    if (stable.get('status') != 'NOT_ATTESTED' or stable['counts']['PROVISIONAL'] != 1 or
            disappeared.get('status') != 'NOT_ATTESTED' or disappeared['counts']['AMBIGUOUS'] != 1 or
            reused.get('status') != 'NOT_ATTESTED' or reused['counts']['UNMATCHED'] != 1):
        raise RuntimeError('P51_FLOW_STABILITY_REGRESSION')
    return {'status':'PASS_RESEARCH_ONLY', 'scenarios_checked':3,
            'ambiguous_owner_guarded':True, 'pid_reuse_guarded':True,
            'account_binding_verified':False, 'live_certified':False,
            'canonical_commits':0, 'physical_input_sent':False}


def host_topology_smoke() -> dict:
    """Synthetic falsification matrix for P52; always research-only."""
    from anka_contracts.client import WindowScan, WindowObservation
    from anka_capture.windows_flows import TcpEndpoint
    w1 = WindowObservation(501, 101, 1000, 'Dofus.exe', 'Dofus', 1280, 649, 96, False)
    w2 = WindowObservation(502, 102, 1001, 'Dofus.exe', 'Dofus', 1280, 649, 96, False)
    before = WindowScan(10_000, (w1,w2))
    after = WindowScan(20_000, (w1,w2))
    k1 = ('127.0.0.1',45000,'198.51.100.7',40400)
    k2 = ('127.0.0.1',45001,'198.51.100.7',40400)
    t1,t2 = TcpEndpoint(*k1,101,5), TcpEndpoint(*k2,102,5)
    good = stable_multi_account_topology(before,after,(t1,t2),(t1,t2),
        {'a':k1,'b':k2},expected_clients=2)
    alias = stable_multi_account_topology(before,after,(t1,t2),(t1,t2),
        {'a':k1,'b':k1},expected_clients=2)
    disputed = stable_multi_account_topology(before,after,(t1,t2,TcpEndpoint(*k1,999,5)),
        (t1,t2), {'a':k1,'b':k2},expected_clients=2)
    if (good.get('status')!='CANDIDATES_ONLY' or
            good.get('distinct_candidate_processes')!=2 or
            good.get('account_binding_verified') is not False or
            alias.get('reason')!='P52_DUPLICATE_SOCKET_SELECTORS' or
            disputed.get('ambiguous_flows')!=1):
        raise RuntimeError('P52_MULTI_ACCOUNT_TOPOLOGY_REGRESSION')
    return {'status':'PASS_RESEARCH_ONLY', 'scenarios_checked':3,
            'alias_blocked':True, 'contradictory_owner_detected':True,
            'account_binding_verified':False, 'canonical_commits':0,
            'physical_input_sent':False}


def historical_process_character_actor_topology(before_windows, after_windows, before_tcp, after_tcp,
                                                  flow_keys: dict, identity_witnesses: dict,
                                                  fight_observations: dict, *,
                                                  expected_character_names: tuple[str, ...]) -> dict:
    """P54 aggregate process -> flow -> historical character -> fight actor continuity.

    Reuses the P53 host/identity topology and independently audits each selected
    flow's actor continuity.  No raw character name, PID, HWND, endpoint, flow
    token, actor id, packet number or fight id is exported.  Cross-flow ordering
    is explicitly out of scope.
    """
    from anka_contracts.historical_identity import HistoricalIdentityObservation
    from anka_protocol.historical_actor_continuity import audit_historical_actor_continuity

    base=historical_character_process_topology(before_windows,after_windows,before_tcp,after_tcp,
                                                flow_keys,identity_witnesses,
                                                expected_character_names=expected_character_names)
    if not isinstance(fight_observations,dict) or len(fight_observations)>4096:
        return {'status':'UNAVAILABLE','reason':'P54_FIGHT_EVIDENCE_INVALID',
                'expected_characters':len(expected_character_names) if isinstance(expected_character_names,tuple) else 0,
                'host_character_topology_status':str(base.get('status','UNAVAILABLE'))[:64],
                'actor_continuity_verified':0,'actor_continuity_partial':0,'actor_continuity_blocked':0,
                'account_binding_verified':False,'current_build_certified':False,
                'canonical_commits':0,'actionable':False,'physical_input_sent':False}
    if base.get('status') in ('UNAVAILABLE','BLOCKED_AMBIGUOUS'):
        return {'status':'BLOCKED_AMBIGUOUS','reason':'P54_P53_TOPOLOGY_NOT_CLEAN',
                'expected_characters':base.get('expected_characters',0),
                'host_character_topology_status':base.get('status'),
                'actor_continuity_verified':0,'actor_continuity_partial':0,'actor_continuity_blocked':0,
                'account_binding_verified':False,'current_build_certified':False,
                'canonical_commits':0,'actionable':False,'physical_input_sent':False}

    expected={name.casefold() for name in expected_character_names}
    valid=partial=blocked=missing=invalid=unexpected=0
    seen_names=set()
    for token,witness in identity_witnesses.items():
        if (type(token) is not str or token not in flow_keys or
                not isinstance(witness,HistoricalIdentityObservation)):
            invalid+=1;continue
        name=witness.character_name.casefold()
        if name not in expected:
            unexpected+=1;continue
        if name in seen_names:
            blocked+=1;continue
        seen_names.add(name)
        observations=fight_observations.get(token)
        if observations is None:
            missing+=1;partial+=1;continue
        audit=audit_historical_actor_continuity(witness,observations)
        if audit.status=='RESEARCH_ACTOR_CONTINUITY_ONLY':valid+=1
        elif audit.status=='PARTIAL_EVIDENCE':partial+=1
        else:blocked+=1
    missing += max(0,len(expected)-len(seen_names))
    if invalid or unexpected or blocked:
        status='BLOCKED_AMBIGUOUS';reason='P54_PROCESS_CHARACTER_ACTOR_CONFLICT'
    elif base.get('status')!='HISTORICAL_CANDIDATES_ONLY' or partial or missing or valid<len(expected):
        status='PARTIAL_CANDIDATES';reason='P54_PROCESS_CHARACTER_ACTOR_INCOMPLETE'
    else:
        status='HISTORICAL_ACTOR_CANDIDATES_ONLY';reason='P54_HISTORICAL_PROCESS_FLOW_CHARACTER_ACTOR_ONLY'
    return {
        'status':status,'reason':reason,
        'expected_characters':len(expected),
        'host_character_topology_status':base.get('status'),
        'historical_process_character_candidates':base.get('matched_process_character_candidates',0),
        'actor_continuity_verified':valid,
        'actor_continuity_partial':partial,
        'actor_continuity_blocked':blocked,
        'missing_fight_witnesses':missing,
        'invalid_identity_witnesses':invalid,
        'unexpected_character_witnesses':unexpected,
        'historical_build_verified':bool(base.get('historical_build_verified',False)),
        'cross_flow_ordering_verified':False,
        'independent_current_character_witnesses':0,
        'account_binding_verified':False,'current_build_certified':False,
        'canonical_commits':0,'actionable':False,'physical_input_sent':False,
    }
