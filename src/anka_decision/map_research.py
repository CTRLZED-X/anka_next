"""Pure P13 research over explicitly synthetic, caller-owned fight/map fixtures.

The actual kernel is the only source of range, LoS, cast and pathfinding rules.
No state writes, window addresses, physical input, tactical ranking or executable plans.
"""
from __future__ import annotations

from anka_contracts.map_research import MapResearchRequest, MapResearchReport
from anka_decision.probe import inspect_cast_probe
from anka_game_kernel.contexts.fight import FightContext
from anka_game_kernel.domain.ids import ActorId, CellId, MapId, SpellId
from anka_game_kernel.domain.maps import MapDefinition
from anka_game_kernel.mechanics.geometry.grid import MAP_CELL_COUNT


def _blocked(reason: str, *, missing: tuple[str, ...] = ()) -> MapResearchReport:
    return MapResearchReport('BLOCKED_EVIDENCE', (reason,), missing, (), (), (), 'NOT_EVALUATED')


def inspect_map_research(snapshot: dict, request: MapResearchRequest, *,
                         map_definition: MapDefinition, fight_context: FightContext, kernel) -> MapResearchReport:
    """Evaluate bounded offline candidates; never turn a preview into an input permit."""
    if not isinstance(request, MapResearchRequest):
        raise TypeError('MAP_RESEARCH_REQUEST_REQUIRED')
    # Reuse the P12 guard, but never substitute it for the independent map/actor checks.
    gate = inspect_cast_probe(snapshot, request.scope, kernel=kernel)
    if gate.status in ('BLOCKED_EVIDENCE', 'BLOCKED_STATIC_DATA', 'BLOCKED_KERNEL'):
        return MapResearchReport(gate.status, gate.reasons, gate.missing_kernel_inputs,
                                 (), (), (), 'NOT_EVALUATED')
    if not isinstance(map_definition, MapDefinition) or not isinstance(fight_context, FightContext):
        return _blocked('MAP_OR_FIGHT_CONTEXT_INVALID')
    if map_definition.map_id != MapId(request.geometry_map_id):
        return _blocked('MAP_ID_MISMATCH')
    # Full 560-cell coverage is a deliberate conservative precondition: a partial map
    # can yield a plausible but false range/path/LoS result.
    map_ids=[int(x.cell_id) for x in map_definition.cells]
    if len(map_ids) != MAP_CELL_COUNT or set(map_ids) != set(range(MAP_CELL_COUNT)):
        return _blocked('MAP_COVERAGE_INCOMPLETE')
    try:
        if not fight_context.require_map(map_definition.map_id):
            return _blocked('FIGHT_MAP_ID_MISSING')
    except (ValueError, TypeError):
        return _blocked('FIGHT_MAP_ID_CONFLICT')
    if fight_context.geometry_live_walkable_cells:
        # R5.195 class of failures: the historical map may disagree with
        # authenticated fight-instance placement/movement overrides. Neither
        # blindly ignore them nor reinterpret them without the kernel's rules.
        return _blocked('LIVE_GEOMETRY_OVERRIDES_NOT_RECONCILED')
    if fight_context.active_actor_id != ActorId(request.scope.actor_id):
        return _blocked('FIGHT_TURN_ACTOR_MISMATCH')
    actor=fight_context.actor(ActorId(request.scope.actor_id))
    state_actor=snapshot['actors'][str(request.scope.actor_id)]
    if actor is None:
        return _blocked('FIGHT_ACTOR_MISSING')
    if (actor.cell_id != CellId(state_actor['cell_id'])
        or actor.current_ap != state_actor['AP']
        or actor.current_mp != state_actor['MP']
        or actor.current_hp != state_actor['hp']
        or actor.max_hp != state_actor['max_hp']):
        return _blocked('FIGHT_ACTOR_STATE_CONFLICT')
    origin_cell=map_definition.cells[int(actor.cell_id)]
    if not origin_cell.walkable or origin_cell.non_walkable_during_fight:
        return _blocked('ACTOR_ORIGIN_GEOMETRY_CONFLICT')
    if actor.cooldowns_complete is not True:
        return _blocked('FIGHT_COOLDOWN_EVIDENCE_INCOMPLETE')
    if sorted((int(cd.spell_id),cd.turns_remaining) for cd in actor.cooldowns) != sorted(map(tuple,state_actor['cooldowns'])):
        return _blocked('FIGHT_COOLDOWNS_CONFLICT')
    if fight_context.occupied_cells is None:
        return _blocked('FIGHT_OCCUPANCY_INCOMPLETE')
    # A context with no current-turn cast record could falsely allow exceeding
    # per-turn or per-target limits. Unknown histories must remain unknown.
    results=[];missing=[]
    for candidate in request.target_cells:
        try:
            result=kernel.spell_decisions.evaluate_cast_cell(
                spell_id=SpellId(request.scope.spell_id),grade=request.scope.grade,
                caster_id=actor.actor_id,target_cell=CellId(candidate),
                map_definition=map_definition,context=fight_context)
        except Exception:
            return MapResearchReport('BLOCKED_KERNEL',('KERNEL_TARGET_QUERY_FAILED',),
                                     tuple(missing),tuple(results),(),(),'NOT_EVALUATED')
        legality=('LEGAL_STATIC_ONLY' if result.legal is True else
                  'ILLEGAL' if result.legal is False else 'UNKNOWN')
        details=tuple(str(x) for x in result.failed_stages) if result.legal is False else tuple(result.missing_inputs)
        if result.legal is None:
            missing.extend(result.missing_inputs)
        results.append((candidate,legality,details))
    try:
        reachable=kernel.fight_queries.reachable_cells(map_definition,fight_context,actor.actor_id)
    except Exception:
        return MapResearchReport('BLOCKED_KERNEL',('KERNEL_REACHABILITY_FAILED',),
                                 tuple(dict.fromkeys(missing)),tuple(results),(),(),'NOT_EVALUATED')
    movement=tuple((int(x.cell_id),x.distance) for x in reachable.reachable)
    missing.extend(reachable.missing_inputs)
    path=();path_status='NOT_REQUESTED'
    if request.movement_target_cell is not None:
        destination=CellId(request.movement_target_cell)
        if reachable.missing_inputs:
            path_status='UNKNOWN'
        elif request.movement_target_cell not in dict(movement):
            # Still ask the kernel for the specific path: distinguishes blocked
            # from unreachable, never infers path legality from visual distance.
            try:
                shortest=kernel.fight_queries.shortest_path(map_definition,fight_context,actor.actor_id,destination)
            except Exception:
                return MapResearchReport('BLOCKED_KERNEL',('KERNEL_PATH_QUERY_FAILED',),
                        tuple(dict.fromkeys(missing)),tuple(results),movement,(),'NOT_EVALUATED')
            if shortest.reachable is False:
                path_status='ILLEGAL_OR_NOT_REACHABLE_WITH_MP'
            elif shortest.reachable is True:
                path_status='OUTSIDE_MP_BUDGET'
            else:
                path_status='UNKNOWN';missing.extend(shortest.missing_inputs)
        else:
            try:
                shortest=kernel.fight_queries.shortest_path(map_definition,fight_context,actor.actor_id,destination)
            except Exception:
                return MapResearchReport('BLOCKED_KERNEL',('KERNEL_PATH_QUERY_FAILED',),
                        tuple(dict.fromkeys(missing)),tuple(results),movement,(),'NOT_EVALUATED')
            if shortest.reachable is True and shortest.step_count == dict(movement)[request.movement_target_cell]:
                path=tuple(int(x) for x in shortest.path);path_status='REACHABLE_STATIC_ONLY'
            elif shortest.reachable is None:
                path_status='UNKNOWN';missing.extend(shortest.missing_inputs)
            else:
                path_status='KERNEL_PATH_CONTRADICTION'
                return MapResearchReport('BLOCKED_KERNEL',('KERNEL_PATH_CONTRADICTION',),
                       tuple(dict.fromkeys(missing)),tuple(results),movement,(),path_status)
    return MapResearchReport('RESEARCH_ONLY',
        ('SYNTHETIC_MAP_STATE_NON_AUTHORITATIVE','HISTORICAL_STATIC_GEOMETRY','CURRENT_CLIENT_BUILD_UNCERTIFIED',
         'SPELL_EQUIPMENT_AND_SLOT_UNPROVEN','PHYSICAL_MOVEMENT_COLLISION_UNVERIFIED'),
        tuple(dict.fromkeys(missing)),tuple(results),movement,path,path_status)
