"""Q10/Q11 observe-only startup diagnosis. Never grants physical input."""
from __future__ import annotations
from anka_contracts.diagnostics import BoundaryExpectation,OperationTraceSpec

STARTUP_TRACE=OperationTraceSpec('START_OBSERVE_ONLY',(
    BoundaryExpectation('start.static_preflight_passed','startup.static_preflight','anka_app','bootstrap'),
    BoundaryExpectation('client.windows_candidate_accepted','client.host_observation','anka_client','identity'),
    BoundaryExpectation('capture.ingress_evidence_collected','capture.observe_only','anka_capture','capture'),
    BoundaryExpectation('protocol.current_build_observation_completed','protocol.current_build_observation','anka_protocol','protocol'),
    BoundaryExpectation('protocol.current_build_semantics_certified','protocol.current_build_semantics','anka_protocol','protocol'),
))


def blockers_for(host:dict, ingress:dict, *, capture_setup:dict|None=None,
                 bridge_setup:dict|None=None) -> tuple[str,...]:
    """Return all evidence-supported concrete startup blockers in causal order.

    The first item is the earliest safe stop boundary. Later items are retained
    for the incident package so one Windows run can expose several independent
    prerequisites without pretending downstream gameplay was exercised.
    """
    out=[]
    def add(code:str):
        if code not in out:out.append(code)
    if host.get('platform')!='WINDOWS':
        add('START_WINDOWS_REQUIRED')
        return tuple(out)
    issues=set(host.get('issues',()))
    if 'WINDOW_INVENTORY_INCOMPLETE' in issues:add('START_WINDOW_INVENTORY_INCOMPLETE')
    if host.get('candidate_windows',0)<=0:add('START_DOFUS_WINDOW_NOT_FOUND')
    if 'DOFUS_WINDOW_COUNT_AMBIGUOUS' in issues:add('START_DOFUS_WINDOW_COUNT_AMBIGUOUS')

    capture=host.get('capture',{}) if isinstance(host.get('capture'),dict) else {}
    if capture.get('scapy_installed') is not True:add('START_CAPTURE_DEPENDENCY_MISSING')
    if capture.get('npcap_driver') in ('NOT_DETECTED','SERVICE_PRESENT_DLLS_MISSING','PROBE_INCOMPLETE'):
        add('START_NPCAP_NOT_READY')
    if capture.get('scope_status')=='NO_TCP_SCOPE' and capture.get('scope_mode') in ('TOO_MANY_SERVER_PORTS','TOO_MANY_ENDPOINT_SELECTORS'):
        add('START_CAPTURE_SCOPE_TOO_BROAD')
    if capture.get('server_port_candidates',0)<=0:add('START_DOFUS_TCP_FLOW_NOT_FOUND')
    if capture.get('interface_resolution')=='UNRESOLVED':add('START_CAPTURE_INTERFACE_UNRESOLVED')

    status=ingress.get('status')
    if status=='SKIPPED':
        reason=ingress.get('reason')
        mapped={
            'NPCAP_NOT_READY':'START_NPCAP_NOT_READY',
            'CAPTURE_INTERFACE_UNRESOLVED':'START_CAPTURE_INTERFACE_UNRESOLVED',
            'DOFUS_TCP_FLOW_CANDIDATE_MISSING':'START_DOFUS_TCP_FLOW_NOT_FOUND',
            'OPTIONAL_CAPTURE_DEPENDENCY_MISSING':'START_CAPTURE_DEPENDENCY_MISSING',
            'DOFUS_WINDOW_COUNT_AMBIGUOUS':'START_DOFUS_WINDOW_COUNT_AMBIGUOUS',
        }.get(reason)
        if mapped:add(mapped)
        elif not out:add('START_CAPTURE_EVIDENCE_MISSING')
    elif status=='FAILED':
        code=ingress.get('error_code')
        mapped={
            'WINDOW_INVENTORY_INCOMPLETE':'START_WINDOW_INVENTORY_INCOMPLETE',
            'DOFUS_WINDOW_COUNT_AMBIGUOUS':'START_DOFUS_WINDOW_COUNT_AMBIGUOUS',
            'SCAPY_NOT_INSTALLED_OPTIONAL_CAPTURE_DEPENDENCY':'START_CAPTURE_DEPENDENCY_MISSING',
            'NPCAP_NOT_READY':'START_NPCAP_NOT_READY',
            'CAPTURE_INTERFACE_UNRESOLVED':'START_CAPTURE_INTERFACE_UNRESOLVED',
            'LIVE_CAPTURE_START_FAILED':'START_CAPTURE_BACKEND_START_FAILED',
            'AUTO_CAPTURE_SCOPE_UNAVAILABLE':'START_DOFUS_TCP_FLOW_NOT_FOUND',
            'CAPTURE_SCOPE_TOO_BROAD':'START_CAPTURE_SCOPE_TOO_BROAD',
            'PROCESS_GENERATION_CHANGED_BEFORE_CAPTURE':'START_CLIENT_PROCESS_GENERATION_DRIFT',
        }.get(code,'START_CAPTURE_SAMPLE_FAILED')
        add(mapped)
    elif status!='CAPTURED_UNCERTIFIED':
        add('START_CAPTURE_EVIDENCE_MISSING')
    else:
        receipt=ingress.get('receipt',{})
        if not isinstance(receipt,dict):
            add('START_CAPTURE_EVIDENCE_MISSING')
            receipt={}
        if ((receipt.get('capture_scope_stability_observed') is True and receipt.get('capture_scope_stable') is not True) or
            (receipt.get('process_generation_stability_observed') is True and receipt.get('process_generation_stable') is not True)):
            add('START_CAPTURE_SCOPE_DRIFT')

        # Transport integrity is an upstream prerequisite of Protocol semantics.
        # Do not hide known queue loss/transport uncertainty behind the later
        # expected "semantic adapter uncertified" blocker. One observe-only
        # run should report every independently known prerequisite.
        capture_status=receipt.get('status')
        queue_dropped=receipt.get('queue_dropped',0)
        if capture_status=='LOSS_DETECTED' or (type(queue_dropped) is int and queue_dropped>0):
            add('START_CAPTURE_QUEUE_LOSS_DETECTED')
        elif capture_status=='TRANSPORT_UNCERTAIN':
            add('START_CAPTURE_TRANSPORT_UNCERTAIN')

        wire=receipt.get('protocol_wire')
        if not isinstance(wire,dict) or wire.get('status') in (None,'NOT_OBSERVED'):
            add('START_PROTOCOL_WIRE_EVIDENCE_MISSING')
        elif wire.get('selected_segments',0)<=0:
            add('START_GAME_TRAFFIC_NOT_OBSERVED')
        elif wire.get('quarantined_streams',0)>0 or wire.get('unanchored_streams',0)>0:
            add('START_PROTOCOL_STREAM_INCOMPLETE')
        elif wire.get('framed_messages',0)<=0:
            add('START_PROTOCOL_FRAMING_NOT_OBSERVED')
        else:
            # A clean in-process queue is not proof that Npcap/the kernel dropped
            # no packets. Surface the evidence limitation independently whenever
            # the backend explicitly reports it. Missing legacy fields are not
            # retroactively interpreted as loss.
            visibility=receipt.get('driver_loss_visibility')
            if visibility is not None and visibility!='AVAILABLE_CLEAN':
                add('START_CAPTURE_DRIVER_LOSS_VISIBILITY_UNAVAILABLE')
            add('CURRENT_CLIENT_SEMANTIC_ADAPTER_UNCERTIFIED')

    # Setup receipts are release-bound provenance, not substitutes for the live
    # host probes above. Stale/invalid records are therefore supplemental gaps:
    # they never erase stronger current observations, but they must not silently
    # disappear from the consolidated Q10/Q11 diagnosis either.
    if isinstance(capture_setup,dict) and capture_setup.get('status') in ('STALE_SETUP_RECORD','RECORD_INVALID'):
        add('START_CAPTURE_SETUP_EVIDENCE_STALE')
    if isinstance(bridge_setup,dict) and bridge_setup.get('status') in ('STALE_SETUP_RECORD','RECORD_INVALID'):
        add('START_BRIDGE_SETUP_EVIDENCE_STALE')

    # These are independent Q10/Q11 evidence gaps. They are deliberately added
    # after acquisition/Protocol so they enrich one incident without preventing
    # observe-only capture that may itself provide identity evidence later.
    build=host.get('client_build',{}) if isinstance(host.get('client_build'),dict) else {}
    if build.get('status')=='MISMATCH' or 'CURRENT_CLIENT_BUILD_MISMATCH' in issues:
        add('START_CLIENT_BUILD_MISMATCH')
    elif host.get('candidate_windows',0)>0 and build.get('status') in ('UNAVAILABLE','PARTIAL'):
        add('START_CLIENT_BUILD_UNAVAILABLE')
    bridge=host.get('bridge',{}) if isinstance(host.get('bridge'),dict) else {}
    bridge_status=bridge.get('status')
    if bridge_status=='AMBIGUOUS_PROCESS_MATCH' or 'UNITY_BRIDGE_PROCESS_MATCH_AMBIGUOUS' in issues:
        add('START_UNITY_BRIDGE_PROCESS_MATCH_AMBIGUOUS')
    elif 'UNITY_BRIDGE_PROCESS_MATCH_PARTIAL' in issues or bridge_status=='PARTIAL_PROCESS_MATCH':
        add('START_UNITY_BRIDGE_PROCESS_MATCH_PARTIAL')
    elif host.get('candidate_windows',0)>0 and bridge.get('process_generation_matches',0)<=0:
        add('START_UNITY_BRIDGE_PROCESS_MATCH_MISSING')
    elif 'UNITY_BRIDGE_PROJECTION_NOT_READY' in issues:
        add('START_UNITY_BRIDGE_PROJECTION_NOT_READY')
    if 'CURRENT_CHARACTER_IDENTITY_EVIDENCE_MISSING' in issues:
        add('START_CHARACTER_IDENTITY_EVIDENCE_MISSING')
    return tuple(out) or ('CURRENT_CLIENT_SEMANTIC_ADAPTER_UNCERTIFIED',)


def blocker_for(host:dict, ingress:dict) -> str:
    return blockers_for(host,ingress)[0]


def boundary_for(code:str)->str:
    if code in ('RELEASE_INTEGRITY_FAILED','START_RELEASE_CHANGED_DURING_OBSERVATION'):return 'startup.release_integrity'
    if code in ('START_RUN_AUTHORITY_ALREADY_HELD','START_RUN_AUTHORITY_ACQUIRE_FAILED'):return 'startup.run_authority'
    if code=='START_CONFIG_CHANGED_DURING_OBSERVATION':return 'configuration.validation'
    if code in ('START_WINDOWS_REQUIRED','START_WINDOW_INVENTORY_INCOMPLETE','START_DOFUS_WINDOW_NOT_FOUND',
                'START_DOFUS_WINDOW_COUNT_AMBIGUOUS','START_CHARACTER_IDENTITY_EVIDENCE_MISSING',
                'START_CLIENT_PROCESS_GENERATION_DRIFT',
                'START_CLIENT_BUILD_MISMATCH','START_CLIENT_BUILD_UNAVAILABLE',
                'START_UNITY_BRIDGE_PROCESS_MATCH_MISSING','START_UNITY_BRIDGE_PROCESS_MATCH_PARTIAL',
                'START_UNITY_BRIDGE_PROCESS_MATCH_AMBIGUOUS','START_UNITY_BRIDGE_PROJECTION_NOT_READY',
                'START_BRIDGE_SETUP_EVIDENCE_STALE'):
        return 'client.host_observation'
    if code.startswith('START_CAPTURE_') or code in ('START_DOFUS_TCP_FLOW_NOT_FOUND','START_GAME_TRAFFIC_NOT_OBSERVED','START_NPCAP_NOT_READY'):
        return 'capture.observe_only'
    return 'protocol.current_build_observation'
