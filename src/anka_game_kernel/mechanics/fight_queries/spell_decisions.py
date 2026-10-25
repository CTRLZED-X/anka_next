from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.contexts.fight import FightContext
from anka_game_kernel.mechanics.casting.model import CastAvailabilityContext
from anka_game_kernel.mechanics.fight.model import CastEvaluationContext
from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.ids import ActorId, CellId, SpellId
from anka_game_kernel.domain.maps import MapDefinition
from anka_game_kernel.domain.spell_effects import SpellEffectBranch
from anka_game_kernel.knowledge.spell_overlay import SpellMechanicsOverlay
from anka_game_kernel.mechanics.fight.projection import CastActionProjectionService
from anka_game_kernel.mechanics.fight.service import FightService
from anka_game_kernel.results.action_projection import CastActionProjectionResult
from anka_game_kernel.results.fight import CastAreaResult, CastEvaluationResult


@dataclass(frozen=True, slots=True)
class SpellDecisionService:
    """AI-facing read-only spell decision facade over verified Kernel mechanics.

    It deliberately separates cast-area legality from effect-area projection. Consumers do not
    need to understand the low-level range/LoS/targeting/effect services to ask the two questions.
    """

    overlay: SpellMechanicsOverlay
    fight: FightService
    action_projection: CastActionProjectionService

    def legal_cast_cells(
        self,
        *,
        spell_id: SpellId,
        grade: int,
        caster_id: ActorId,
        map_definition: MapDefinition,
        context: FightContext,
        range_bonus: int | None = None,
        summon_slots_remaining: int | None = None,
    ) -> CastAreaResult:
        view = self.overlay.require_grade(spell_id, grade)
        caster = context.actor(caster_id)
        if caster is None:
            return CastAreaResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                missing_inputs=(f"actor:{int(caster_id)}",),
                complete=False,
                explanation="Spell decision query requires the caster snapshot.",
            )
        effective_grade, missing = self.overlay.resolve_projected_grade(view, caster)
        if effective_grade is None:
            return CastAreaResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                missing_inputs=missing,
                complete=False,
                explanation=(
                    "Spell decision query cannot evaluate active range modifiers until verified "
                    "selector metadata is available for the candidate spell."
                ),
            )
        return self.fight.legal_target_cells_for_grade(
            effective_grade,
            map_definition=map_definition,
            context=context,
            caster_id=caster_id,
            range_bonus=range_bonus,
            summon_slots_remaining=summon_slots_remaining,
        )


    def evaluate_cast_cell(
        self,
        *,
        spell_id: SpellId,
        grade: int,
        caster_id: ActorId,
        target_cell: CellId,
        map_definition: MapDefinition,
        context: FightContext,
        range_bonus: int | None = None,
        summon_slots_remaining: int | None = None,
    ) -> CastEvaluationResult:
        """Evaluate one concrete cast target without enumerating the 560-cell map.

        This is the candidate-first planner primitive.  It composes the exact same
        availability/range/LoS/target-cell rules as ``legal_cast_cells`` but only
        for the target the caller actually intends to score.
        """
        view = self.overlay.require_grade(spell_id, grade)
        caster = context.actor(caster_id)
        if caster is None:
            return CastEvaluationResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE, legal=None,
                missing_inputs=(f"actor:{int(caster_id)}",),
                explanation="Single-cell cast evaluation requires the caster snapshot.",
            )
        if caster.cell_id is None:
            return CastEvaluationResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE, legal=None,
                missing_inputs=(f"actor:{int(caster_id)}:cell",),
                explanation="Single-cell cast evaluation requires the caster cell.",
            )
        effective_grade, missing = self.overlay.resolve_projected_grade(view, caster)
        if effective_grade is None:
            return CastEvaluationResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE, legal=None,
                missing_inputs=missing,
                explanation=(
                    "Single-cell cast evaluation cannot resolve active spell-property modifiers "
                    "without verified selector metadata."
                ),
            )
        resolved_range_bonus = self.fight.range.resolve_bonus(caster, effective_grade, range_bonus)
        if resolved_range_bonus is None:
            return CastEvaluationResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE, legal=None,
                missing_inputs=(f"actor:{int(caster_id)}.combat_stats.range_bonus",),
                explanation="Single-cell cast evaluation requires current caller-owned PO.",
            )
        if not context.require_map(map_definition.map_id):
            return CastEvaluationResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE, legal=None,
                missing_inputs=("map_id",),
                explanation="Single-cell cast evaluation requires canonical map identity.",
            )
        target_actor = context.actor_at(target_cell)
        history = context.current_turn
        history_matches_actor = history is not None and history.actor_id == caster_id
        target_actor_id = None if target_actor is None else target_actor.actor_id
        availability = CastAvailabilityContext(
            current_ap=caster.current_ap,
            casts_this_turn=(history.cast_count(effective_grade.spell_id) if history_matches_actor else None),
            global_casts_this_turn=context.global_cast_count(effective_grade.spell_id),
            cooldown_remaining=caster.cooldown_remaining(effective_grade.spell_id),
            target_id=None if target_actor_id is None else int(target_actor_id),
            casts_on_target_this_turn=(
                history.cast_count_on_target(effective_grade.spell_id, target_actor_id)
                if history_matches_actor and target_actor_id is not None
                else None
            ),
            active_state_ids=caster.active_state_ids,
            summon_slots_remaining=summon_slots_remaining,
        )
        return self.fight.evaluate_grade_cast(
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

    def preview_cast(
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
        """Validate a cast then return its ordered deterministic/live-authority projection."""
        return self.action_projection.project_spell_cast(
            spell_id=spell_id,
            grade=grade,
            caster_id=caster_id,
            target_cell=target_cell,
            map_definition=map_definition,
            context=context,
            branch=branch,
            range_bonus=range_bonus,
            summon_slots_remaining=summon_slots_remaining,
        )
