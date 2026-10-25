"""P16 offline stateful kernel previews; never a live action plan.

Use the real Kernel's projection as the sole hypothetical state transition.
Stop at any live-authoritative, partial, or contradictory step rather than
continuing on guessed effects. No input API, no commits, no account control.
"""
from __future__ import annotations

from anka_contracts.sequence_research import (
    SequenceResearchRequest,SequenceResearchReport,SequenceStepResult)
from anka_decision.tactical_research import inspect_tactical_research
from anka_game_kernel.contexts.projection import FightProjection
from anka_game_kernel.contexts.turn_history import MovementRecord
from anka_game_kernel.results.action_projection import CastActionProjectionResult
from anka_game_kernel.domain.ids import ActorId,CellId,SpellId
from anka_game_kernel.mechanics.projection.service import FightProjectionService


def _block(status,requested,*reasons,steps=()):
    return SequenceResearchReport(status,tuple(reasons),tuple(steps),len(steps),requested)


def inspect_sequence_research(snapshot:dict,request:SequenceResearchRequest,*,map_definition,fight_context,kernel)->SequenceResearchReport:
    """Bounded at four sequential casts; effects and authorization are never inferred."""
    if not isinstance(request,SequenceResearchRequest):
        raise TypeError('P16_SEQUENCE_REQUEST_REQUIRED')
    number=len(request.casts)
    base=inspect_tactical_research(snapshot,request.tactical,map_definition=map_definition,
                                   fight_context=fight_context,kernel=kernel)
    if base.status!='RESEARCH_ONLY':
        return _block('BLOCKED_GATE',number,*base.reasons)
    initial=[c for c in base.candidates if c.movement_cell==request.movement_cell and c.target_cell==request.casts[0].target_cell]
    if len(initial)!=1:
        return _block('BLOCKED_GATE',number,'P16_FIRST_CANDIDATE_MISSING_OR_DUPLICATED')
    candidate=initial[0]
    if candidate.kernel_legality!='LEGAL_STATIC_ONLY' or candidate.mp_cost is None or not candidate.movement_path:
        return _block('BLOCKED_GATE',number,'P16_FIRST_CAST_NOT_PROVEN_STATIC',*candidate.reasons,*candidate.missing_inputs)
    actor_id=ActorId(request.tactical.scope.actor_id)
    origin=int(fight_context.actor(actor_id).cell_id)
    # P14 already validates geometry, shortest path, resources and state scope.
    # A real move remains server-uncertain, but can be simulated for research.
    if (request.movement_cell!=origin and
        (fight_context.per_mp_used_modifiers or 'MOVEMENT_DEPENDENT_EFFECTS_UNPROJECTED' in candidate.missing_inputs)):
        return _block('BLOCKED_MOVEMENT',number,'P16_REACTIVE_MOVEMENT_NOT_PROJECTABLE')
    projector=FightProjectionService()
    try:
        hypothetical=FightProjection.from_context(fight_context)
        if request.movement_cell!=origin:
            hypothetical=projector.move_actor(hypothetical,actor_id,CellId(request.movement_cell))
            hypothetical=projector.spend_mp(hypothetical,actor_id,candidate.mp_cost)
            hypothetical=projector.append_movement(hypothetical,MovementRecord(actor_id,
                tuple(CellId(x) for x in candidate.movement_path),candidate.mp_cost))
    except Exception:
        return _block('BLOCKED_KERNEL',number,'P16_MOVE_PROJECTION_FAILED')
    steps=[]
    for i,cast in enumerate(request.casts,1):
        before=hypothetical.context.actor(actor_id)
        if before is None or before.current_ap is None:
            return _block('BLOCKED_EVIDENCE',number,'P16_ACTOR_AP_UNKNOWN',steps=steps)
        try:
            preview=kernel.spell_decisions.preview_cast(spell_id=SpellId(cast.spell_id),grade=cast.grade,
                caster_id=actor_id,target_cell=CellId(cast.target_cell),map_definition=map_definition,
                context=hypothetical.context)
        except Exception:
            return _block('BLOCKED_KERNEL',number,'P16_CAST_PROJECTION_EXCEPTION',steps=steps)
        if not isinstance(preview,CastActionProjectionResult) or preview.legal not in (True,False,None):
            return _block('BLOCKED_KERNEL',number,'P16_INVALID_KERNEL_RESULT',steps=steps)
        projection=preview.projection
        if projection is not None and not isinstance(projection,FightProjection):
            return _block('BLOCKED_KERNEL',number,'P16_INVALID_KERNEL_PROJECTION',steps=steps)
        new_actor=projection.context.actor(actor_id) if projection is not None else None
        certainty=str(getattr(preview.certainty,'value',preview.certainty))
        missing=tuple(str(x) for x in preview.missing_inputs)
        requirements=tuple(str(getattr(x.kind,'value',x.kind)) for x in preview.live_requirements)
        # Missing/partial/live-authoritative effects prevent chaining onto imaginary facts.
        complete=(preview.legal is True and preview.projection_complete is True and
                  not missing and not requirements and certainty=='deterministic' and new_actor is not None)
        # A "complete" preview must preserve the input context as its exact
        # base and append precisely this cast to both known history streams.
        # This catches stale/contradictory projection adapters before any chaining.
        if complete:
            old_history=hypothetical.context.current_turn
            new_history=projection.context.current_turn
            old_global=hypothetical.context.global_turn_casts
            new_global=projection.context.global_turn_casts
            failure=(projection.base_context!=hypothetical.context or
                     old_history is None or new_history is None or
                     new_history.actor_id!=actor_id or
                     len(new_history.casts)!=len(old_history.casts)+1 or
                     new_history.casts[:-1]!=old_history.casts or
                     new_history.casts[-1].caster_id!=actor_id or
                     new_history.casts[-1].spell_id!=SpellId(cast.spell_id) or
                     new_history.casts[-1].grade!=cast.grade or
                     new_history.casts[-1].target_cell!=CellId(cast.target_cell) or
                     (old_global is not None and
                      (new_global is None or new_global != old_global+(new_history.casts[-1],))) or
                     new_actor.current_ap is None or new_actor.current_ap<0 or
                     new_actor.current_mp is None or new_actor.current_mp<0)
            if failure:
                return _block('BLOCKED_KERNEL',number,'P16_PROJECTION_INTEGRITY_CONFLICT',steps=steps)
        if preview.legal is False:
            status='REJECTED_BY_KERNEL'
        elif preview.legal is None:
            status='UNKNOWN_LEGALITY'
        elif not complete:
            status='STOP_UNRESOLVED_EFFECTS'
        else:
            status='HYPOTHETICAL_COMPLETE'
        history=projection.context.current_turn if projection is not None else None
        projected_count=(history.cast_count(SpellId(cast.spell_id)) if history is not None else None)
        steps.append(SequenceStepResult(i,cast.spell_id,cast.target_cell,status,before.current_ap,
            new_actor.current_ap if new_actor is not None else None,
            new_actor.current_mp if new_actor is not None else None,projected_count,
            new_actor.cooldown_remaining(SpellId(cast.spell_id)) if new_actor is not None else None,
            complete,certainty,missing,requirements,
            ('SYNTHETIC_PROJECTION_ONLY',) if complete else ('SUBSEQUENT_STEPS_NOT_EVALUATED',)))
        if not complete:
            return _block('STOPPED_UNCERTAIN' if preview.legal is not False else 'STOPPED_ILLEGAL',
                          number,'P16_SEQUENCE_STOPPED_AT_STEP_'+str(i),status,steps=steps)
        hypothetical=projection
    return _block('RESEARCH_ONLY',number,'SYNTHETIC_ONLY','NO_INPUT_AUTHORITY',
                  'CURRENT_CLIENT_BUILD_UNCERTIFIED',
                  *('MOVEMENT_OUTCOME_NOT_CONFIRMED',) if request.movement_cell!=origin else (),steps=steps)
