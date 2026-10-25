"""Pure Client proof composition and invalidation logic.

This module deliberately has no OS calls and no input driver.  It composes
already-observed evidence into a generation-fenced prerequisite proof.
"""
from __future__ import annotations
from anka_contracts.bridge import BridgeMapReport
from anka_contracts.client import (AccountBinding, CalibrationProfileEvidence,
    ClientContextProof, ClientGenerationVector, LoadoutEvidence, WindowObservation)
from anka_client.discovery import client_instance_id, generation_id

BREED_CLASS_IDS={'CRA':9,'ENUTROF':3}
MAX_LOADOUT_AGE_NS=3_000_000_000


def build_client_context(*, character_name: str, binding: AccountBinding,
                         window: WindowObservation, calibration: CalibrationProfileEvidence,
                         bridge: BridgeMapReport | None, loadout: LoadoutEvidence | None,
                         observed_monotonic_ns: int, expected_map_id: int | None=None) -> ClientContextProof:
    reasons=[]
    gid=generation_id(window)
    if binding.state!='IDENTITY_MATCHED': reasons.append('IDENTITY_NOT_PROVEN')
    if binding.generation_id!=gid or binding.hwnd!=window.hwnd or binding.pid!=window.pid:
        reasons.append('WINDOW_GENERATION_MISMATCH')
    breed=(binding.breed or '').upper() or None
    class_id=BREED_CLASS_IDS.get(breed) if breed else None
    if class_id is None: reasons.append('CLASS_NOT_PROVEN')
    if window.minimized: reasons.append('WINDOW_MINIMIZED')
    if window.foreground is not True: reasons.append('WINDOW_FOREGROUND_UNKNOWN' if window.foreground is None else 'WINDOW_NOT_FOREGROUND')
    if window.occluded is not False: reasons.append('WINDOW_OCCLUSION_UNKNOWN' if window.occluded is None else 'WINDOW_OCCLUDED')
    if (window.client_width,window.client_height)!=(calibration.width,calibration.height): reasons.append('CALIBRATION_WINDOW_SIZE_MISMATCH')
    if calibration.expected_dpi is not None and window.dpi!=calibration.expected_dpi: reasons.append('CALIBRATION_DPI_MISMATCH')
    if window.dpi is None: reasons.append('WINDOW_DPI_UNKNOWN')
    if not calibration.current_client_certified: reasons.append('CALIBRATION_NOT_CURRENT_CERTIFIED')
    map_id=map_gen=coord_gen=None
    if bridge is None:
        reasons.append('BRIDGE_PROJECTION_MISSING')
    elif bridge.status!='RESEARCH_PROJECTION_ONLY' or not bridge.source_verified:
        reasons.append('BRIDGE_PROJECTION_UNPROVEN')
    else:
        if not bridge.live_certified: reasons.append('BRIDGE_NOT_CURRENT_CERTIFIED')
        map_id=bridge.map_id;map_gen=bridge.map_generation;coord_gen=bridge.coordinate_generation
        if bridge.client_size!=(window.client_width,window.client_height): reasons.append('BRIDGE_WINDOW_SIZE_MISMATCH')
        if expected_map_id is not None and map_id!=expected_map_id: reasons.append('BRIDGE_MAP_MISMATCH')
        if not all(type(v) is int and v>0 for v in (map_id,map_gen,coord_gen)): reasons.append('BRIDGE_GENERATION_MISSING')
    loadout_gen=None
    if loadout is None:
        reasons.append('LOADOUT_EVIDENCE_MISSING')
    else:
        loadout_gen=loadout.generation
        if loadout.proof_status!='PROVEN': reasons.append('LOADOUT_NOT_PROVEN')
        if loadout.window_generation_id!=gid: reasons.append('LOADOUT_WINDOW_GENERATION_MISMATCH')
        if loadout.character_name.strip().casefold()!=character_name.strip().casefold(): reasons.append('LOADOUT_CHARACTER_MISMATCH')
        if breed is None or loadout.breed.strip().upper()!=breed: reasons.append('LOADOUT_CLASS_MISMATCH')
        age=observed_monotonic_ns-loadout.observed_monotonic_ns
        if age<0 or age>MAX_LOADOUT_AGE_NS: reasons.append('LOADOUT_STALE_OR_FUTURE')
    # Stable order + no duplicate reasons makes receipts/replay deterministic.
    reasons=tuple(dict.fromkeys(reasons))
    vector=ClientGenerationVector(gid,window.client_width,window.client_height,window.dpi,
        window.foreground,window.occluded,map_id,map_gen,coord_gen,calibration.generation,loadout_gen)
    status='PROVEN' if not reasons else ('BLOCKED' if any(x.endswith('MISMATCH') or x in {
        'IDENTITY_NOT_PROVEN','CLASS_NOT_PROVEN','WINDOW_MINIMIZED','WINDOW_NOT_FOREGROUND','WINDOW_OCCLUDED','LOADOUT_NOT_PROVEN'} for x in reasons) else 'INCOMPLETE')
    return ClientContextProof(character_name,breed,class_id,vector,status,reasons,False)


def generation_invalidators(previous: ClientGenerationVector, current: ClientGenerationVector) -> tuple[str,...]:
    checks=(
        ('WINDOW_GENERATION_CHANGED',previous.window_generation_id,current.window_generation_id),
        ('WINDOW_SIZE_CHANGED',(previous.width,previous.height),(current.width,current.height)),
        ('WINDOW_DPI_CHANGED',previous.dpi,current.dpi),
        ('BRIDGE_MAP_CHANGED',previous.bridge_map_id,current.bridge_map_id),
        ('BRIDGE_MAP_GENERATION_CHANGED',previous.bridge_map_generation,current.bridge_map_generation),
        ('BRIDGE_COORDINATE_GENERATION_CHANGED',previous.bridge_coordinate_generation,current.bridge_coordinate_generation),
        ('CALIBRATION_GENERATION_CHANGED',previous.calibration_generation,current.calibration_generation),
        ('LOADOUT_GENERATION_CHANGED',previous.loadout_generation,current.loadout_generation),
    )
    result=[code for code,a,b in checks if a!=b]
    if current.foreground is not True: result.append('FOCUS_NOT_PROVEN')
    if current.occluded is not False: result.append('VISIBILITY_NOT_PROVEN')
    return tuple(result)


def identity_from_binding(*, account_id: str, binding: AccountBinding, window: WindowObservation,
                          bridge_generation: int | None=None):
    """Build the stable ClientIdentity DTO from independently matched evidence."""
    from anka_contracts.client import ClientIdentity
    if binding.state!='IDENTITY_MATCHED' or binding.generation_id!=generation_id(window):
        raise ValueError('CLIENT_IDENTITY_NOT_PROVEN')
    breed=(binding.breed or '').upper(); class_id=BREED_CLASS_IDS.get(breed)
    if class_id is None: raise ValueError('CLIENT_CLASS_NOT_PROVEN')
    account_token=account_id if account_id.startswith('acct-') else 'acct-'+account_id
    gid=binding.generation_id
    return ClientIdentity(client_instance_id(window),account_token,window.pid,window.process_created_100ns,window.hwnd,
        int(gid[4:20],16),'PROVEN',class_id,'PROVEN',bridge_generation,
        window.client_width,window.client_height,window.dpi)
