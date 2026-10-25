"""P14 movement+cast candidate research driven entirely by the preserved Kernel.

Every hypothetical branch is built from caller-owned immutable snapshots and stays
NON-AUTHORITATIVE. This is not a tactical optimizer, action plan, or execution API.
"""
from __future__ import annotations
from anka_contracts.tactical_research import TacticalCandidate, TacticalResearchRequest, TacticalResearchReport
from anka_contracts.map_research import MapResearchRequest
from anka_decision.map_research import inspect_map_research
from anka_game_kernel.domain.ids import ActorId, CellId, SpellId
from anka_game_kernel.contexts.projection import FightProjection
from anka_game_kernel.mechanics.projection.service import FightProjectionService


def _blocked(status:str, *reasons:str, missing:tuple[str,...]=())->TacticalResearchReport:
    return TacticalResearchReport(status,tuple(reasons),missing,(),0)


def _sequence_cost(kernel, request:TacticalResearchRequest)->int | None:
    total=0
    for spell_id,grade in (request.spell_sequence or ((request.scope.spell_id,request.scope.grade),)):
        view=kernel.spell_mechanics_overlay.require_grade(SpellId(spell_id),grade)
        cost=view.effective_grade.ap_cost
        if type(cost) is not int or cost<0:
            return None
        total+=cost
    return total


def inspect_tactical_research(snapshot:dict, request:TacticalResearchRequest, *, map_definition, fight_context, kernel)->TacticalResearchReport:
    """Evaluate at most 144 move+cast pairs, with bounded deterministic ordering.

    Kernel's shortest-path, reachability, projection and cast evaluation are
    authoritative *only for the supplied synthetic snapshot*. Never act on output.
    """
    if not isinstance(request,TacticalResearchRequest):
        raise TypeError('TACTICAL_RESEARCH_REQUEST_REQUIRED')
    base=inspect_map_research(snapshot,MapResearchRequest(request.scope,request.geometry_map_id,
        request.target_cells),map_definition=map_definition,fight_context=fight_context,kernel=kernel)
    if base.status!='RESEARCH_ONLY':
        return _blocked(base.status,*base.reasons,missing=base.missing_inputs)
    try:
        cost=_sequence_cost(kernel,request)
    except Exception:
        return _blocked('BLOCKED_STATIC_DATA','TACTICAL_SEQUENCE_STATIC_DATA_INVALID')
    if cost is None:
        return _blocked('BLOCKED_STATIC_DATA','TACTICAL_SEQUENCE_COST_UNRESOLVED')
    aid=ActorId(request.scope.actor_id)
    actor=fight_context.actor(aid)
    if actor is None or actor.cell_id is None or actor.current_ap is None or actor.current_mp is None:
        return _blocked('BLOCKED_EVIDENCE','TACTICAL_ACTOR_RESOURCES_MISSING')
    # Initial AP/MP budgets are from two independently matched snapshots (P13).
    origin=int(actor.cell_id); available=dict(base.reachable_cells)
    available[origin]=0  # standing still is always an option for this actor
    service=FightProjectionService()
    results=[]; aggregate_missing=list(base.missing_inputs)
    for cell in request.movement_cells:
        mp_cost=available.get(cell)
        path=()
        move_reasons=[]
        projection=None
        if mp_cost is None:
            move_reasons.append('CELL_NOT_REACHABLE_WITH_MP')
        else:
            if cell==origin:
                path=(origin,)
            else:
                try:
                    shortest=kernel.fight_queries.shortest_path(map_definition,fight_context,aid,CellId(cell))
                    if shortest.reachable is None:
                        move_reasons.append('KERNEL_PATH_EVIDENCE_MISSING')
                        aggregate_missing.extend(shortest.missing_inputs)
                    elif shortest.reachable is not True or shortest.step_count!=mp_cost or not shortest.path or int(shortest.path[0])!=origin or int(shortest.path[-1])!=cell:
                        move_reasons.append('KERNEL_PATH_CONTRADICTION')
                    else:
                        path=tuple(int(x) for x in shortest.path)
                except Exception:
                    move_reasons.append('KERNEL_PATH_QUERY_FAILED')
            if path:
                try:
                    projection=FightProjection.from_context(fight_context)
                    projection=service.move_actor(projection,aid,CellId(cell))
                    projection=service.spend_mp(projection,aid,mp_cost)
                except Exception:
                    move_reasons.append('KERNEL_MOVEMENT_PROJECTION_FAILED')
                    projection=None
        for target in request.target_cells:
            missing=[]; reasons=list(move_reasons)
            remaining_mp=actor.current_mp-mp_cost if mp_cost is not None and projection is not None else None
            remaining_ap=None
            first_cost=None
            legality='NOT_EVALUATED'
            sequence_status='NOT_EVALUATED'
            if projection is not None:
                try:
                    result=kernel.spell_decisions.evaluate_cast_cell(
                        spell_id=SpellId(request.scope.spell_id),grade=request.scope.grade,
                        caster_id=aid,target_cell=CellId(target),
                        map_definition=map_definition,context=projection.context)
                    first_cost=kernel.spell_mechanics_overlay.require_grade(
                        SpellId(request.scope.spell_id),request.scope.grade).effective_grade.ap_cost
                    if type(first_cost) is not int or first_cost<0:
                        reasons.append('FIRST_CAST_COST_UNRESOLVED')
                    elif first_cost<=actor.current_ap:
                        # AP projection is used only for bookkeeping. Not a prediction
                        # of cooldown, damage, movement triggers, or server acceptance.
                        projected=service.spend_ap(projection,aid,first_cost)
                        remaining_ap=projected.context.actor(aid).current_ap
                    else:
                        remaining_ap=None
                    legality=('LEGAL_STATIC_ONLY' if result.legal is True else
                              'ILLEGAL' if result.legal is False else 'UNKNOWN')
                    missing.extend(str(x) for x in result.missing_inputs)
                    if result.legal is False:
                        reasons.extend('KERNEL_'+str(x) for x in result.failed_stages)
                    if cell!=origin:
                        missing.extend(('MOVEMENT_SERVER_OUTCOME_UNCONFIRMED',
                                        'MOVEMENT_TACKLE_AND_REACTIVE_EFFECTS_UNVERIFIED'))
                    if cell!=origin and fight_context.per_mp_used_modifiers:
                        # Movement-dependent effects require an effect-resolved
                        # projection; position and MP alone cannot prove legality.
                        legality='UNKNOWN'; missing.append('MOVEMENT_DEPENDENT_EFFECTS_UNPROJECTED')
                    if len(request.spell_sequence)>1:
                        if cost>actor.current_ap:
                            sequence_status='OVER_AP_BUDGET'
                        else:
                            sequence_status='WITHIN_AP_BUDGET_COST_ONLY'
                        missing.append('MULTI_CAST_EFFECTS_AND_CAST_HISTORY_NOT_SIMULATED')
                    else:
                        sequence_status='WITHIN_AP_BUDGET_COST_ONLY' if cost<=actor.current_ap else 'OVER_AP_BUDGET'
                except Exception:
                    legality='NOT_EVALUATED'; reasons.append('KERNEL_CAST_QUERY_FAILED')
            aggregate_missing.extend(missing)
            results.append(TacticalCandidate(cell,target,path,mp_cost if projection is not None else None,
                first_cost,remaining_mp,remaining_ap,legality,tuple(dict.fromkeys(missing)),
                tuple(dict.fromkeys(reasons)),cost,sequence_status))
    # Reproducible ordering; *not* strategic ranking, nor evidence of live viability.
    priority={'LEGAL_STATIC_ONLY':0,'UNKNOWN':1,'ILLEGAL':2,'NOT_EVALUATED':3}
    results.sort(key=lambda r:(priority.get(r.kernel_legality,4),
        r.mp_cost if r.mp_cost is not None else 1_000_000,r.movement_cell,r.target_cell))
    return TacticalResearchReport('RESEARCH_ONLY',
        ('SYNTHETIC_FIXTURE_ONLY','NO_GAMEPLAY_EXECUTION_AUTHORITY',
         'CURRENT_CLIENT_BUILD_UNCERTIFIED','SEQUENCE_BUDGET_NOT_SEQUENCE_LEGALITY'),
        tuple(dict.fromkeys(aggregate_missing)),tuple(results),len(results))
