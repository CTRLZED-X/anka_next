"""Read-only Windows host observation for start/Q10-Q11 preparation.

Technical capture scope is discovered internally from Dofus executable/process
identity plus TCP ownership.  The report is privacy-safe and never grants
character identity, protocol authority, calibration authority, or input rights.
"""
from __future__ import annotations
from importlib.util import find_spec
import ntpath
import os
from typing import Callable

from anka_app.configuration import RunConfiguration
from anka_client.api import ClientInspection
from anka_client.discovery import SUPPORTED_EXECUTABLES
from anka_capture.windows_scope import derive_windows_capture_scope, resolve_scapy_interface


class _SnapshotInventory:
    def __init__(self, scan): self._scan=scan
    def scan(self): return self._scan


def probe_host(config: RunConfiguration, *, platform: str | None = None,
               inventory_factory: Callable | None = None,
               tcp_snapshot: Callable | None = None,
               scapy_available: Callable[[], bool] | None = None,
               bridge_probe: Callable | None = None, npcap_probe: Callable | None = None) -> dict:
    system=os.name if platform is None else platform
    issues=[]
    report={
        'status':'READ_ONLY_UNCERTIFIED',
        'platform':'WINDOWS' if system=='nt' else 'NON_WINDOWS',
        'account_count':len(config.players),'candidate_windows':0,
        'account_binding_states':[],'identity_issues':[],
        'geometry_reference_matches':0,'geometry_issues':[],
        'client_build':{'status':'NOT_CHECKED','version':None,'reported_clients':0},
        'tcp_ownership':'NOT_CHECKED','tcp_candidate_processes':0,
        'capture':{
            'scope_mode':'AUTO_PROCESS_TCP' if not config.capture.server_ports else 'EXPLICIT_OVERRIDE',
            'server_port_candidates':0,'endpoint_selector_candidates':0,'scope_status':'NOT_CHECKED',
            'interface_mode':'AUTO' if not config.capture.interface else 'EXPLICIT_OVERRIDE',
            'interface_resolution':'NOT_CHECKED',
            'scapy_installed':False,'npcap_driver':'NOT_VERIFIED','driver_loss_visibility':'UNKNOWN',
        },
        'bridge':{'status':'NOT_CHECKED','healthy_bridges':0,'process_generation_matches':0,
                  'projection_ready_matches':0,'character_identity_provided':False,
                  'physical_input_permitted':False},
        'live_certified':False,'account_binding_verified':False,
        'calibration_certified':False,'physical_input_permitted':False,
    }
    if system!='nt':
        issues.append('HOST_WINDOWS_ACCEPTANCE_NOT_PERFORMED');report['tcp_ownership']='WINDOWS_ONLY';report['issues']=issues;return report

    try:
        installed=scapy_available() if scapy_available is not None else find_spec('scapy') is not None
        report['capture']['scapy_installed']=installed is True
        if not installed: issues.append('CAPTURE_OPTIONAL_SCAPY_NOT_INSTALLED')
    except Exception:
        issues.append('CAPTURE_DEPENDENCY_PROBE_FAILED')

    try:
        if npcap_probe is None:
            from anka_capture.windows_backend import probe_npcap_presence
            npcap_probe=lambda:probe_npcap_presence(platform=system)
        backend=npcap_probe()
        if isinstance(backend,dict):
            report['capture']['npcap_driver']=backend.get('status','NOT_VERIFIED')
            if backend.get('status') in ('NOT_DETECTED','SERVICE_PRESENT_DLLS_MISSING','PROBE_INCOMPLETE'):
                issues.append('NPCAP_NOT_READY')
    except Exception:
        issues.append('NPCAP_PROBE_FAILED')

    scan=None
    trusted_windows=()
    try:
        if inventory_factory is None:
            from anka_client.win32_inventory import NativeWindowsInventory
            inventory_factory=NativeWindowsInventory
        inventory=inventory_factory(tuple(p.name for p in config.players))
        scan=inventory.scan()
        trusted_windows=tuple(w for w in scan.windows
            if ntpath.basename(w.executable_name).casefold() in SUPPORTED_EXECUTABLES)
        inspected=ClientInspection(_SnapshotInventory(scan)).inspect(tuple(p.name for p in config.players))
        report['candidate_windows']=len(trusted_windows)
        build_values=[w.build_version for w in trusted_windows if isinstance(w.build_version,str) and w.build_version]
        unique_builds=sorted(set(build_values))
        if trusted_windows and len(build_values)==len(trusted_windows) and len(unique_builds)==1:
            report['client_build']={'status':'CONSISTENT','version':unique_builds[0],'reported_clients':len(build_values)}
        elif len(unique_builds)>1:
            report['client_build']={'status':'MISMATCH','version':None,'reported_clients':len(build_values)}
            issues.append('CURRENT_CLIENT_BUILD_MISMATCH')
        elif build_values:
            report['client_build']={'status':'PARTIAL','version':unique_builds[0] if len(unique_builds)==1 else None,'reported_clients':len(build_values)}
            issues.append('CURRENT_CLIENT_BUILD_UNAVAILABLE')
        elif trusted_windows:
            report['client_build']={'status':'UNAVAILABLE','version':None,'reported_clients':0}
            issues.append('CURRENT_CLIENT_BUILD_UNAVAILABLE')
        report['account_binding_states']=[b['state'] for b in inspected['bindings']]
        report['identity_issues']=[b['reason'] for b in inspected['bindings']]
        geometries=inspected['geometry'].values()
        report['geometry_reference_matches']=sum(bool(g['observationally_matching_size']) for g in geometries)
        report['geometry_issues']=sorted({x for g in inspected['geometry'].values() for x in g['issues']})
        if scan.errors: issues.append('WINDOW_INVENTORY_INCOMPLETE')
        if not trusted_windows: issues.append('DOFUS_WINDOW_NOT_FOUND')
        elif len(trusted_windows) != len(config.players): issues.append('DOFUS_WINDOW_COUNT_AMBIGUOUS')
        if any(b['state']!='IDENTITY_MATCHED' for b in inspected['bindings']):
            issues.append('WINDOW_CHARACTER_IDENTITY_UNATTESTED')
        # No title-derived identity fallback: a player name is only a hint.
        issues.append('CURRENT_CHARACTER_IDENTITY_EVIDENCE_MISSING')
    except Exception:
        issues.append('WINDOW_INVENTORY_PROBE_FAILED')

    rows=()
    try:
        if tcp_snapshot is None:
            from anka_capture.windows_flows import WindowsTcpOwnership
            tcp_snapshot=WindowsTcpOwnership().snapshot
        rows=tuple(tcp_snapshot())
        trusted_pids={w.pid for w in trusted_windows}
        report['tcp_candidate_processes']=len({r.pid for r in rows if getattr(r,'state',None)==5 and r.pid in trusted_pids})
        report['tcp_ownership']='PROVISIONAL_PROCESS_HINT_ONLY'
        if scan is not None:
            # Never widen automatic passive capture to an ambiguous number of
            # game clients.  Until independent account identity exists, the only
            # safe automatic set is exactly the configured client count.
            eligible_pids={w.pid for w in trusted_windows} if len(trusted_windows)==len(config.players) else set()
            scope=derive_windows_capture_scope(eligible_pids,rows,
                                               override_ports=config.capture.server_ports,
                                               override_interface=config.capture.interface)
            safe=scope.safe_receipt()
            report['capture']['scope_mode']=safe['mode']
            report['capture']['scope_status']=safe['status']
            report['capture']['server_port_candidates']=safe['server_port_count']
            report['capture']['endpoint_selector_candidates']=safe['endpoint_selector_count']
            report['capture']['interface_mode']=safe['interface_mode']
            if scope.interface:
                report['capture']['interface_resolution']='EXPLICIT_OVERRIDE'
            elif scope.local_ips and report['capture']['scapy_installed']:
                resolved=resolve_scapy_interface(scope.local_ips)
                report['capture']['interface_resolution']='RESOLVED' if resolved else 'UNRESOLVED'
                if not resolved: issues.append('CAPTURE_INTERFACE_UNRESOLVED')
            elif scope.local_ips:
                report['capture']['interface_resolution']='DEPENDENCY_MISSING'
            else:
                report['capture']['interface_resolution']='NO_TCP_SCOPE'
            if safe['mode'] in ('TOO_MANY_SERVER_PORTS','TOO_MANY_ENDPOINT_SELECTORS'):
                issues.append('CAPTURE_SCOPE_TOO_BROAD')
            elif not scope.server_ports and trusted_windows and len(trusted_windows)==len(config.players):
                issues.append('DOFUS_TCP_FLOW_NOT_FOUND')
    except Exception:
        report['tcp_ownership']='UNAVAILABLE';issues.append('WINDOWS_TCP_OWNER_TABLE_UNAVAILABLE')

    if trusted_windows:
        try:
            if bridge_probe is None:
                from anka_client.bridge_discovery import probe_bridge_range
                bridge_probe=probe_bridge_range
            report['bridge']=bridge_probe(trusted_windows)
            bridge_status=report['bridge'].get('status')
            expected=len({(w.pid,w.process_created_100ns) for w in trusted_windows})
            matched=report['bridge'].get('matched_process_generations',report['bridge'].get('process_generation_matches',0))
            ready=report['bridge'].get('projection_ready_matches',0)
            if bridge_status=='AMBIGUOUS_PROCESS_MATCH':
                issues.append('UNITY_BRIDGE_PROCESS_MATCH_AMBIGUOUS')
            elif expected and matched==0:
                issues.append('UNITY_BRIDGE_PROCESS_MATCH_MISSING')
            elif expected and matched<expected:
                issues.append('UNITY_BRIDGE_PROCESS_MATCH_PARTIAL')
            elif expected and ready<expected:
                issues.append('UNITY_BRIDGE_PROJECTION_NOT_READY')
        except Exception:
            report['bridge']={'status':'UNAVAILABLE','healthy_bridges':0,'process_generation_matches':0,
                              'projection_ready_matches':0,'character_identity_provided':False,
                              'physical_input_permitted':False}
            issues.append('UNITY_BRIDGE_PROBE_FAILED')
    report['issues']=sorted(set(issues))
    return report
