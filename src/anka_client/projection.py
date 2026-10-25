"""Pure semantic-target to client-coordinate projection using proven M3 context.

A valid ProjectionEvidence means the coordinates are coherent with the supplied
proof generation.  It still cannot authorize physical input.
"""
from __future__ import annotations
from anka_contracts.bridge import BridgeMapReport
from anka_contracts.client import (CalibrationProfileEvidence, ClientContextProof,
    LoadoutEvidence, ProjectionEvidence)

def _window_generation(ctx:ClientContextProof)->int:
    return int(ctx.vector.window_generation_id[4:20],16)


def _invalid(ctx:ClientContextProof,kind:str,identity:str,now:int,*reasons:str)->ProjectionEvidence:
    why=tuple(dict.fromkeys(ctx.invalidators+tuple(reasons))) or ('CLIENT_CONTEXT_NOT_PROVEN',)
    return ProjectionEvidence('client-'+ctx.vector.window_generation_id[4:20],_window_generation(ctx),ctx.vector.bridge_coordinate_generation,
        ctx.vector.calibration_generation,kind,identity,-1,-1,now,False,why)


def project_spell(ctx:ClientContextProof, calibration:CalibrationProfileEvidence,
                  loadout:LoadoutEvidence, spell_id:int, observed_monotonic_ns:int)->ProjectionEvidence:
    if ctx.prerequisites_status!='PROVEN': return _invalid(ctx,'spell',str(spell_id),observed_monotonic_ns)
    if loadout.generation!=ctx.vector.loadout_generation or loadout.window_generation_id!=ctx.vector.window_generation_id:
        return _invalid(ctx,'spell',str(spell_id),observed_monotonic_ns,'LOADOUT_GENERATION_CHANGED')
    slots=[slot for slot,sid in loadout.slot_spells if sid==spell_id]
    if len(slots)!=1: return _invalid(ctx,'spell',str(spell_id),observed_monotonic_ns,'SPELL_SLOT_MISSING_OR_AMBIGUOUS')
    points={slot:(x,y) for slot,x,y in calibration.spell_slots}
    if slots[0] not in points: return _invalid(ctx,'spell',str(spell_id),observed_monotonic_ns,'SPELL_SLOT_NOT_CALIBRATED')
    x,y=points[slots[0]]
    return ProjectionEvidence('client-'+ctx.vector.window_generation_id[4:20],_window_generation(ctx),ctx.vector.bridge_coordinate_generation,
        calibration.generation,'spell',str(spell_id),x,y,observed_monotonic_ns,True,(),False)


def project_cell(ctx:ClientContextProof, bridge:BridgeMapReport, cell_id:int,
                 observed_monotonic_ns:int)->ProjectionEvidence:
    if ctx.prerequisites_status!='PROVEN': return _invalid(ctx,'cell',str(cell_id),observed_monotonic_ns)
    if (bridge.map_id,bridge.map_generation,bridge.coordinate_generation)!=(ctx.vector.bridge_map_id,ctx.vector.bridge_map_generation,ctx.vector.bridge_coordinate_generation):
        return _invalid(ctx,'cell',str(cell_id),observed_monotonic_ns,'BRIDGE_GENERATION_CHANGED')
    matches=[c for c in bridge.cells if c.cell_id==cell_id]
    if len(matches)!=1 or not (matches[0].source_verified and matches[0].projectable and matches[0].inside_viewport):
        return _invalid(ctx,'cell',str(cell_id),observed_monotonic_ns,'CELL_NOT_PROJECTABLE')
    c=matches[0]
    return ProjectionEvidence('client-'+ctx.vector.window_generation_id[4:20],_window_generation(ctx),bridge.coordinate_generation,
        ctx.vector.calibration_generation,'cell',str(cell_id),c.client_x,c.client_y,observed_monotonic_ns,True,(),False)
