"""Pure semantic-target to client-coordinate projection using proven M3 context.

A valid ProjectionEvidence means the coordinates are coherent with the supplied
proof generation.  It still cannot authorize physical input.
"""
from __future__ import annotations
from anka_contracts.bridge import BridgeMapReport
from anka_contracts.client import (CalibrationProfileEvidence, ClientContextProof,
    LoadoutEvidence, ProjectionEvidence)
from anka_client.context import MAX_LOADOUT_AGE_NS

def _window_generation(ctx:ClientContextProof)->int:
    return int(ctx.vector.window_generation_id[4:20],16)


def _invalid(ctx:ClientContextProof,kind:str,identity:str,now:int,*reasons:str)->ProjectionEvidence:
    why=tuple(dict.fromkeys(ctx.invalidators+tuple(reasons))) or ('CLIENT_CONTEXT_NOT_PROVEN',)
    return ProjectionEvidence('client-'+ctx.vector.window_generation_id[4:20],_window_generation(ctx),ctx.vector.bridge_coordinate_generation,
        ctx.vector.calibration_generation,kind,identity,-1,-1,now,False,why)


def project_spell(ctx:ClientContextProof, calibration:CalibrationProfileEvidence,
                  loadout:LoadoutEvidence, spell_id:int, observed_monotonic_ns:int)->ProjectionEvidence:
    if ctx.prerequisites_status!='PROVEN': return _invalid(ctx,'spell',str(spell_id),observed_monotonic_ns)
    if type(spell_id) is not int or spell_id<=0:
        return _invalid(ctx,'spell',str(spell_id),observed_monotonic_ns,'INVALID_SPELL_ID')
    if (calibration.generation!=ctx.vector.calibration_generation
            or (calibration.width,calibration.height)!=(ctx.vector.width,ctx.vector.height)
            or not calibration.current_client_certified):
        return _invalid(ctx,'spell',str(spell_id),observed_monotonic_ns,'CALIBRATION_GENERATION_CHANGED')
    if calibration.expected_dpi is not None and calibration.expected_dpi!=ctx.vector.dpi:
        return _invalid(ctx,'spell',str(spell_id),observed_monotonic_ns,'CALIBRATION_DPI_CHANGED')
    if (loadout.generation!=ctx.vector.loadout_generation
            or loadout.window_generation_id!=ctx.vector.window_generation_id):
        return _invalid(ctx,'spell',str(spell_id),observed_monotonic_ns,'LOADOUT_GENERATION_CHANGED')
    if loadout.proof_status!='PROVEN':
        return _invalid(ctx,'spell',str(spell_id),observed_monotonic_ns,'LOADOUT_NOT_PROVEN')
    if loadout.character_name.strip().casefold()!=ctx.character_name.strip().casefold():
        return _invalid(ctx,'spell',str(spell_id),observed_monotonic_ns,'LOADOUT_CHARACTER_CHANGED')
    if ctx.breed is None or loadout.breed.strip().upper()!=ctx.breed:
        return _invalid(ctx,'spell',str(spell_id),observed_monotonic_ns,'LOADOUT_CLASS_CHANGED')
    age=observed_monotonic_ns-loadout.observed_monotonic_ns
    if age<0 or age>MAX_LOADOUT_AGE_NS:
        return _invalid(ctx,'spell',str(spell_id),observed_monotonic_ns,'LOADOUT_STALE_OR_FUTURE')
    slots=[slot for slot,sid in loadout.slot_spells if sid==spell_id]
    if len(slots)!=1: return _invalid(ctx,'spell',str(spell_id),observed_monotonic_ns,'SPELL_SLOT_MISSING_OR_AMBIGUOUS')
    points={slot:(x,y) for slot,x,y in calibration.spell_slots}
    if slots[0] not in points: return _invalid(ctx,'spell',str(spell_id),observed_monotonic_ns,'SPELL_SLOT_NOT_CALIBRATED')
    x,y=points[slots[0]]
    if (type(x) is not int or type(y) is not int
            or not (0<=x<ctx.vector.width and 0<=y<ctx.vector.height)):
        return _invalid(ctx,'spell',str(spell_id),observed_monotonic_ns,'SPELL_COORDINATES_INVALID')
    return ProjectionEvidence('client-'+ctx.vector.window_generation_id[4:20],_window_generation(ctx),ctx.vector.bridge_coordinate_generation,
        calibration.generation,'spell',str(spell_id),x,y,observed_monotonic_ns,True,(),False)


def project_cell(ctx:ClientContextProof, bridge:BridgeMapReport, cell_id:int,
                 observed_monotonic_ns:int)->ProjectionEvidence:
    if ctx.prerequisites_status!='PROVEN': return _invalid(ctx,'cell',str(cell_id),observed_monotonic_ns)
    if type(cell_id) is not int or not 0<=cell_id<560:
        return _invalid(ctx,'cell',str(cell_id),observed_monotonic_ns,'INVALID_CELL_ID')
    if (bridge.status!='RESEARCH_PROJECTION_ONLY' or bridge.source_verified is not True
            or bridge.live_certified is not True
            or type(bridge.client_size) is not tuple or len(bridge.client_size)!=2
            or any(type(v) is not int or v<=0 for v in bridge.client_size)
            or bridge.client_size!=(ctx.vector.width,ctx.vector.height)):
        return _invalid(ctx,'cell',str(cell_id),observed_monotonic_ns,'BRIDGE_PROJECTION_UNPROVEN')
    generations=(bridge.map_id,bridge.map_generation,bridge.coordinate_generation)
    if (any(type(v) is not int or v<=0 for v in generations)
            or generations!=(ctx.vector.bridge_map_id,ctx.vector.bridge_map_generation,ctx.vector.bridge_coordinate_generation)):
        return _invalid(ctx,'cell',str(cell_id),observed_monotonic_ns,'BRIDGE_GENERATION_CHANGED')
    matches=[c for c in bridge.cells if type(c.cell_id) is int and c.cell_id==cell_id]
    if len(matches)!=1:
        return _invalid(ctx,'cell',str(cell_id),observed_monotonic_ns,'CELL_NOT_PROJECTABLE')
    c=matches[0]
    if (c.source_verified is not True or c.projectable is not True or c.inside_viewport is not True):
        return _invalid(ctx,'cell',str(cell_id),observed_monotonic_ns,'CELL_NOT_PROJECTABLE')
    if (type(c.client_x) is not int or type(c.client_y) is not int
            or not (0<=c.client_x<ctx.vector.width and 0<=c.client_y<ctx.vector.height)):
        return _invalid(ctx,'cell',str(cell_id),observed_monotonic_ns,'CELL_COORDINATES_OUT_OF_BOUNDS')
    return ProjectionEvidence('client-'+ctx.vector.window_generation_id[4:20],_window_generation(ctx),bridge.coordinate_generation,
        ctx.vector.calibration_generation,'cell',str(cell_id),c.client_x,c.client_y,observed_monotonic_ns,True,(),False)
