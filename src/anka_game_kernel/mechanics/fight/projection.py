from __future__ import annotations

from dataclasses import dataclass, replace

from anka_game_kernel.contexts.fight import FightContext
from anka_game_kernel.contexts.projection import FightProjection
from anka_game_kernel.contexts.turn_history import CastRecord
from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.ids import ActorId, CellId, SpellId
from anka_game_kernel.domain.maps import MapDefinition
from anka_game_kernel.domain.spell_effects import SpellEffectBranch
from anka_game_kernel.knowledge.spell_overlay import SpellMechanicsOverlay
from anka_game_kernel.mechanics.effect_resolution.service import EffectResolutionService
from anka_game_kernel.mechanics.fight.model import CastEvaluationContext
from anka_game_kernel.mechanics.fight.service import FightService
from anka_game_kernel.mechanics.fight_queries.service import FightQueryService
from anka_game_kernel.mechanics.projection.service import FightProjectionService
from anka_game_kernel.results.action_projection import CastActionProjectionResult


@dataclass(frozen=True, slots=True)
class CastActionProjectionService:
    overlay: SpellMechanicsOverlay
    fight: FightService
    resolver: EffectResolutionService
    projection_service: FightProjectionService

    def project_spell_cast(
        self,
        *,
        spell_id: SpellId,
        grade: int,
        caster_id: ActorId,
        target_cell: CellId,
        map_definition: MapDefinition,
        context: FightContext,
        branch: SpellEffectBranch = SpellEffectBranch.NORMAL,
        range_bonus: int | None = None,
        summon_slots_remaining: int | None = None,
    ) -> CastActionProjectionResult:
        base_projection = FightProjection.from_context(context)
        if not context.require_map(map_definition.map_id):
            return CastActionProjectionResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                missing_inputs=("map_id",),
                legal=None,
                projection_complete=False,
                projection=base_projection,
                explanation="Cast projection requires the fight snapshot's canonical map identity.",
            )
        view = self.overlay.require_grade(spell_id, grade)
        effective_grade = view.effective_grade
        caster = context.actor(caster_id)
        if caster is None:
            return CastActionProjectionResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                missing_inputs=(f"actor:{int(caster_id)}",),
                legal=None, projection_complete=False, projection=base_projection,
                explanation="Cast projection requires the caster snapshot.",
            )
        if caster.cell_id is None:
            return CastActionProjectionResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                missing_inputs=(f"actor:{int(caster_id)}:cell",),
                legal=None, projection_complete=False, projection=base_projection,
                explanation="Cast projection requires the caster cell.",
            )

        effective_grade, modifier_missing = self.overlay.resolve_projected_grade(view, caster)
        if effective_grade is None:
            return CastActionProjectionResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                missing_inputs=modifier_missing,
                legal=None, projection_complete=False, projection=base_projection,
                explanation=(
                    "Cast projection cannot evaluate active spell-range modifiers until the "
                    "target spell's verified selector metadata is available."
                ),
            )

        resolved_range_bonus = self.fight.range.resolve_bonus(caster, effective_grade, range_bonus)
        if resolved_range_bonus is None:
            return CastActionProjectionResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                missing_inputs=(f"actor:{int(caster_id)}.combat_stats.range_bonus",),
                legal=None, projection_complete=False, projection=base_projection,
                explanation=(
                    "Cast projection requires current caller-owned PO for a modifiable-range spell."
                ),
            )

        if context.active_actor_id is not None and context.active_actor_id != caster_id:
            return CastActionProjectionResult(
                certainty=Certainty.DETERMINISTIC,
                legal=False, projection_complete=False, projection=base_projection,
                explanation=(
                    "No cast changes were projected because the requested caster is not the active actor."
                ),
            )
        if context.current_turn is None:
            return CastActionProjectionResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                missing_inputs=("current_turn",),
                legal=None, projection_complete=False, projection=base_projection,
                explanation="Cast projection requires current-turn history before appending a cast.",
            )
        if context.current_turn.actor_id != caster_id:
            return CastActionProjectionResult(
                certainty=Certainty.DETERMINISTIC,
                legal=False, projection_complete=False, projection=base_projection,
                explanation=(
                    "No cast changes were projected because current-turn history belongs to another actor."
                ),
            )

        target_actor = context.actor_at(target_cell)
        availability = FightQueryService.cast_availability_from_context(
            context,
            actor_id=caster_id,
            spell_id=spell_id,
            target_actor_id=None if target_actor is None else target_actor.actor_id,
            summon_slots_remaining=summon_slots_remaining,
        )
        evaluation = self.fight.evaluate_grade_cast(
            effective_grade,
            CastEvaluationContext(
                map_definition=map_definition,
                caster_cell=caster.cell_id,
                target_cell=target_cell,
                availability=availability,
                range_bonus=resolved_range_bonus,
                occupied_cells=context.occupied_cells,
                proven_occupied_cells=context.proven_occupied_cells,
            ),
        )
        if evaluation.legal is not True:
            return CastActionProjectionResult(
                certainty=evaluation.certainty,
                missing_inputs=evaluation.missing_inputs,
                legal=evaluation.legal, projection_complete=False,
                cast_evaluation=evaluation,
                projection=base_projection,
                explanation=(
                    "No deterministic cast changes were projected because the cast is illegal "
                    "or its legality is incomplete."
                ),
            )

        projection = self.projection_service.spend_ap(base_projection, caster_id, effective_grade.ap_cost)
        projection = self.projection_service.append_cast(
            projection,
            CastRecord(
                caster_id=caster_id,
                spell_id=spell_id,
                grade=grade,
                target_actor_id=None if target_actor is None else target_actor.actor_id,
                target_cell=target_cell,
                ap_spent=effective_grade.ap_cost,
            ),
        )
        cooldown_after_cast = self.fight.casting.cooldown_after_cast(
            self.fight.compile_grade(effective_grade).spec.availability
        )
        if caster.cooldown_remaining(spell_id) is not None:
            projection = self.projection_service.set_cooldown(
                projection, caster_id, spell_id, cooldown_after_cast
            )

        mechanics = view.mechanics
        if (
            mechanics is not None
            and mechanics.cast_rule_override is not None
            and mechanics.cast_rule_override.shared_cooldown is True
            and caster.team_id is not None
            and caster.class_id is not None
        ):
            for allied_actor in projection.context.actors:
                if allied_actor.actor_id == caster_id:
                    continue
                if allied_actor.summoned:
                    continue
                if allied_actor.team_id != caster.team_id or allied_actor.class_id != caster.class_id:
                    continue
                if allied_actor.cooldown_remaining(spell_id) is None:
                    continue
                projection = self.projection_service.set_cooldown(
                    projection, allied_actor.actor_id, spell_id, cooldown_after_cast
                )

        if mechanics is None:
            return CastActionProjectionResult(
                certainty=Certainty.UNKNOWN,
                legal=True, projection_complete=False, cast_evaluation=evaluation,
                projection=projection,
                explanation="Cast rules are known, but ordered spell mechanics are unknown.",
            )
        effects = mechanics.normal_effects if branch is SpellEffectBranch.NORMAL else mechanics.critical_effects
        if effects is None:
            return CastActionProjectionResult(
                certainty=Certainty.UNKNOWN,
                legal=True, projection_complete=False, cast_evaluation=evaluation,
                projection=projection,
                explanation="The selected spell effect branch is unknown.",
            )

        effect_result = self.resolver.resolve(
            effects=effects,
            caster_id=caster_id,
            target_cell=target_cell,
            map_definition=map_definition,
            context=projection.context,
        )
        assert effect_result.projection is not None
        combined = replace(
            effect_result.projection,
            base_context=context,
            changes=projection.changes + effect_result.projection.changes,
        )
        return CastActionProjectionResult(
            certainty=effect_result.certainty,
            missing_inputs=effect_result.missing_inputs,
            legal=True,
            projection_complete=(
                effect_result.certainty in (Certainty.DETERMINISTIC, Certainty.LIVE_REQUIRED)
                and not effect_result.missing_inputs
            ),
            cast_evaluation=evaluation,
            projection=combined,
            effect_resolution=effect_result,
            live_requirements=effect_result.live_requirements,
            explanation=(
                "Legal accepted hypothetical cast projected deterministic AP/history/cooldown changes "
                "and resolved ordered effects without claiming server confirmation."
            ),
        )
