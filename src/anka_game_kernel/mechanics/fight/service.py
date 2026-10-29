from __future__ import annotations

from dataclasses import dataclass, field

from anka_game_kernel.contexts.fight import FightContext
from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.ids import ActorId, CellId
from anka_game_kernel.domain.maps import MapDefinition
from anka_game_kernel.mechanics.casting.model import CastAvailabilityContext
from anka_game_kernel.mechanics.casting.service import CastAvailabilityService
from anka_game_kernel.domain.spells import SpellGradeDefinition
from anka_game_kernel.mechanics.fight.compiler import (
    SpellRuleCompilationResult,
    SpellRuleCompiler,
)
from anka_game_kernel.mechanics.fight.model import CastEvaluationContext, CastEvaluationSpec
from anka_game_kernel.mechanics.geometry.grid import MAP_CELL_COUNT
from anka_game_kernel.mechanics.los.service import LineOfSightService
from anka_game_kernel.mechanics.range.service import RangeService
from anka_game_kernel.mechanics.targeting.model import TargetCellContext
from anka_game_kernel.mechanics.targeting.service import TargetingService
from anka_game_kernel.results.fight import (
    CastAreaResult,
    CastEvaluationResult,
    CastEvaluationStage,
)


@dataclass(frozen=True, slots=True)
class FightService:
    compiler: SpellRuleCompiler = field(default_factory=SpellRuleCompiler)
    casting: CastAvailabilityService = field(default_factory=CastAvailabilityService)
    range: RangeService = field(default_factory=RangeService)
    los: LineOfSightService = field(default_factory=LineOfSightService)
    targeting: TargetingService = field(default_factory=TargetingService)

    def compile_grade(self, grade: SpellGradeDefinition) -> SpellRuleCompilationResult:
        return self.compiler.compile(grade)

    def evaluate_grade_cast(
        self,
        grade: SpellGradeDefinition,
        context: CastEvaluationContext,
    ) -> CastEvaluationResult:
        compiled = self.compile_grade(grade)
        if compiled.spec is None:
            return CastEvaluationResult.unsupported_compilation(
                unsupported_fields=compiled.unsupported_fields,
                explanation=compiled.explanation
                or "The canonical spell grade could not be compiled into supported cast rules.",
            )
        return self.evaluate_cast(compiled.spec, context)


    def legal_target_cells_for_grade(
        self,
        grade: SpellGradeDefinition,
        *,
        map_definition: MapDefinition,
        context: FightContext,
        caster_id: ActorId,
        range_bonus: int | None = None,
        summon_slots_remaining: int | None = None,
    ) -> CastAreaResult:
        caster = context.actor(caster_id)
        if caster is None:
            return CastAreaResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                missing_inputs=(f"actor:{int(caster_id)}",),
                complete=False,
                explanation="Cast-area enumeration requires the caster snapshot.",
            )
        if caster.cell_id is None:
            return CastAreaResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                missing_inputs=(f"actor:{int(caster_id)}:cell",),
                complete=False,
                explanation="Cast-area enumeration requires the caster cell.",
            )

        resolved_range_bonus = self.range.resolve_bonus(caster, grade, range_bonus)
        if resolved_range_bonus is None:
            return CastAreaResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                missing_inputs=(f"actor:{int(caster_id)}.combat_stats.range_bonus",),
                complete=False,
                explanation=(
                    "Cast-area enumeration requires current caller-owned PO for a modifiable-range spell."
                ),
            )

        if not context.require_map(map_definition.map_id):
            return CastAreaResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                missing_inputs=("map_id",),
                legal_cells=None,
                indeterminate_cells=None,
                complete=False,
                explanation="Cast-area enumeration requires the fight snapshot's canonical map identity.",
            )

        legal: list[CellId] = []
        indeterminate: list[CellId] = []
        missing: list[str] = []
        worst = Certainty.DETERMINISTIC
        priority = {
            Certainty.DETERMINISTIC: 0,
            Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE: 1,
            Certainty.LIVE_REQUIRED: 2,
            Certainty.UNKNOWN: 3,
            Certainty.UNSUPPORTED: 4,
        }
        for cell in sorted(map_definition.cells, key=lambda item: int(item.cell_id)):
            target_actor = context.actor_at(cell.cell_id)
            history = context.current_turn
            history_matches_actor = history is not None and history.actor_id == caster_id
            target_actor_id = None if target_actor is None else target_actor.actor_id
            availability = CastAvailabilityContext(
                current_ap=caster.current_ap,
                casts_this_turn=(history.cast_count(grade.spell_id) if history_matches_actor else None),
                global_casts_this_turn=context.global_cast_count(grade.spell_id),
                cooldown_remaining=caster.cooldown_remaining(grade.spell_id),
                target_id=None if target_actor_id is None else int(target_actor_id),
                casts_on_target_this_turn=(
                    history.cast_count_on_target(grade.spell_id, target_actor_id)
                    if history_matches_actor and target_actor_id is not None
                    else None
                ),
                active_state_ids=caster.active_state_ids,
                summon_slots_remaining=summon_slots_remaining,
            )
            evaluated = self.evaluate_grade_cast(
                grade,
                CastEvaluationContext(
                    map_definition=map_definition,
                    caster_cell=caster.cell_id,
                    target_cell=cell.cell_id,
                    availability=availability,
                    range_bonus=resolved_range_bonus,
                    occupied_cells=context.occupied_cells,
                    proven_occupied_cells=context.proven_occupied_cells,
                ),
            )
            if evaluated.legal is True:
                legal.append(cell.cell_id)
            elif evaluated.legal is None:
                indeterminate.append(cell.cell_id)
                if priority[evaluated.certainty] > priority[worst]:
                    worst = evaluated.certainty
                for item in evaluated.missing_inputs:
                    if item not in missing:
                        missing.append(item)

        complete_map = len(map_definition.cells) == MAP_CELL_COUNT
        if not complete_map:
            if "complete_map_cells" not in missing:
                missing.append("complete_map_cells")
            if priority[Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE] > priority[worst]:
                worst = Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE
        complete = complete_map and not indeterminate
        return CastAreaResult(
            certainty=Certainty.DETERMINISTIC if complete else worst,
            missing_inputs=tuple(missing),
            legal_cells=tuple(legal),
            indeterminate_cells=tuple(indeterminate),
            complete=complete,
            explanation=(
                "Legal cast-target cells were enumerated by applying the canonical grade cast rules "
                "independently to every supplied map cell; effect AoE was not consulted."
            ),
        )

    def evaluate_cast(
        self,
        spec: CastEvaluationSpec,
        context: CastEvaluationContext,
    ) -> CastEvaluationResult:
        availability = self.casting.evaluate(spec.availability, context.availability)
        range_result = self.range.evaluate(
            context.caster_cell,
            context.target_cell,
            spec.range,
            range_bonus=context.range_bonus,
        )
        line_of_sight = (
            self.los.evaluate(
                context.map_definition,
                context.caster_cell,
                context.target_cell,
                occupied_cells=context.occupied_cells,
            )
            if spec.requires_line_of_sight
            else None
        )
        target_cell = self.targeting.evaluate_cell(
            context.map_definition,
            context.target_cell,
            spec.target_cell,
            TargetCellContext(
                caster_cell=context.caster_cell,
                occupied_cells=context.occupied_cells,
                proven_occupied_cells=context.proven_occupied_cells,
            ),
        )

        failed_stages = tuple(
            stage
            for stage, failed in (
                (CastEvaluationStage.AVAILABILITY, availability.legal is False),
                (CastEvaluationStage.RANGE, range_result.legal is False),
                (
                    CastEvaluationStage.LINE_OF_SIGHT,
                    line_of_sight is not None and line_of_sight.visible is False,
                ),
                (CastEvaluationStage.TARGET_CELL, target_cell.legal is False),
            )
            if failed
        )
        if failed_stages:
            return CastEvaluationResult.deterministic(
                legal=False,
                failed_stages=failed_stages,
                availability=availability,
                range_result=range_result,
                line_of_sight=line_of_sight,
                target_cell=target_cell,
                explanation=(
                    "One or more independently evaluated cast constraints prove the cast illegal."
                ),
            )

        components = tuple(
            component
            for component in (availability, range_result, line_of_sight, target_cell)
            if component is not None
        )
        for certainty in (Certainty.UNSUPPORTED, Certainty.UNKNOWN, Certainty.LIVE_REQUIRED):
            if any(component.certainty is certainty for component in components):
                return CastEvaluationResult.indeterminate(
                    certainty=certainty,
                    availability=availability,
                    range_result=range_result,
                    line_of_sight=line_of_sight,
                    target_cell=target_cell,
                    explanation=(
                        "No known constraint proves the cast illegal, but at least one required "
                        f"component is {certainty.value}."
                    ),
                )

        missing_inputs: list[str] = []
        for component in components:
            for missing_input in component.missing_inputs:
                if missing_input not in missing_inputs:
                    missing_inputs.append(missing_input)
        if missing_inputs:
            return CastEvaluationResult.incomplete(
                missing_inputs=tuple(missing_inputs),
                availability=availability,
                range_result=range_result,
                line_of_sight=line_of_sight,
                target_cell=target_cell,
            )

        return CastEvaluationResult.deterministic(
            legal=True,
            failed_stages=(),
            availability=availability,
            range_result=range_result,
            line_of_sight=line_of_sight,
            target_cell=target_cell,
            explanation="All composed cast-legality constraints are satisfied.",
        )
