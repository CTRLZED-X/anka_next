"""Read-only Windows capture prerequisite probe; never a capture authority."""
from __future__ import annotations
from pathlib import Path
import os, subprocess


def probe_npcap_presence(*, platform:str|None=None, runner=None, system_root:str|None=None)->dict:
    system=os.name if platform is None else platform
    if system!='nt':return {'status':'NOT_WINDOWS','service_detected':False,'dlls_detected':False,'capture_verified':False}
    # Tests may inject platform='nt' on a non-Windows host. Do not fabricate a
    # Windows result from that environment.
    if os.name!='nt' and platform is not None and (runner is None or system_root is None):
        return {'status':'NOT_VERIFIED_INJECTED_PLATFORM','service_detected':False,'dlls_detected':False,'capture_verified':False}
    root=Path(system_root or os.environ.get('SystemRoot','C:/Windows'))
    npcap=root/'System32'/'Npcap'
    dlls=(npcap/'wpcap.dll').is_file() and (npcap/'Packet.dll').is_file()
    service=False;probe_error=False
    try:
        call=runner or subprocess.run
        result=call(['sc','query','npcap'],capture_output=True,text=True,timeout=8,check=False)
        service=(getattr(result,'returncode',1)==0 and 'SERVICE_NAME' in getattr(result,'stdout',''))
    except Exception:probe_error=True
    if service and dlls:status='DETECTED_UNVERIFIED'
    elif dlls:status='DLLS_PRESENT_SERVICE_UNCONFIRMED'
    elif service:status='SERVICE_PRESENT_DLLS_MISSING'
    elif probe_error:status='PROBE_INCOMPLETE'
    else:status='NOT_DETECTED'
    return {'status':status,'service_detected':service,'dlls_detected':dlls,'capture_verified':False}
