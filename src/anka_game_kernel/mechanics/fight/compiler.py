from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.spells import SpellGradeDefinition
from anka_game_kernel.mechanics.casting.model import CastAvailabilitySpec
from anka_game_kernel.mechanics.fight.model import CastEvaluationSpec
from anka_game_kernel.mechanics.range.model import RangeSpec
from anka_game_kernel.mechanics.targeting.model import TargetCellSpec
from anka_game_kernel.results.base import MechanicResult


@dataclass(frozen=True, slots=True)
class SpellRuleCompilationResult(MechanicResult):
    spec: CastEvaluationSpec | None = None
    unsupported_fields: tuple[str, ...] = ()

    @classmethod
    def compiled(cls, spec: CastEvaluationSpec) -> "SpellRuleCompilationResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            spec=spec,
            explanation="Canonical spell-grade cast rules compiled into generic mechanic specs.",
        )

    @classmethod
    def unsupported(
        cls, fields: tuple[str, ...], explanation: str
    ) -> "SpellRuleCompilationResult":
        return cls(
            certainty=Certainty.UNSUPPORTED,
            spec=None,
            unsupported_fields=fields,
            explanation=explanation,
        )


@dataclass(frozen=True, slots=True)
class SpellRuleCompiler:
    def compile(self, grade: SpellGradeDefinition) -> SpellRuleCompilationResult:
        unsupported_fields: list[str] = []
        if grade.max_cast_per_turn < 0:
            unsupported_fields.append("max_cast_per_turn")
        if grade.initial_cooldown < 0:
            unsupported_fields.append("initial_cooldown")
        if grade.max_range < grade.min_range:
            unsupported_fields.append("range")

        if unsupported_fields:
            return SpellRuleCompilationResult.unsupported(
                tuple(unsupported_fields),
                "The source spell grade contains unresolved or contradictory cast-rule values; "
                "the Kernel will not guess a normalized meaning.",
            )

        return SpellRuleCompilationResult.compiled(
            CastEvaluationSpec(
                availability=CastAvailabilitySpec(
                    ap_cost=grade.ap_cost,
                    max_cast_per_turn=grade.max_cast_per_turn,
                    max_global_cast_per_turn=grade.max_global_cast_per_turn,
                    max_cast_per_target=grade.max_cast_per_target,
                    min_cast_interval=grade.min_cast_interval,
                    initial_cooldown=grade.initial_cooldown,
                    state_criterion=grade.state_criterion,
                    requires_summon_slot=grade.can_summon,
                ),
                range=RangeSpec(
                    min_range=grade.min_range,
                    max_range=grade.max_range,
                    modifiable=grade.range_modifiable,
                    cast_in_line=grade.cast_in_line,
                    cast_in_diagonal=grade.cast_in_diagonal,
                ),
                target_cell=TargetCellSpec(
                    need_free_cell=grade.need_free_cell,
                    need_taken_cell=grade.need_taken_cell,
                ),
                requires_line_of_sight=grade.requires_line_of_sight,
            )
        )
