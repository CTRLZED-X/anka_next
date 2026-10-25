from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.ids import CellId
from anka_game_kernel.results.base import MechanicResult
from anka_game_kernel.results.casting import CastAvailabilityResult
from anka_game_kernel.results.los import LineOfSightResult
from anka_game_kernel.results.range import RangeResult
from anka_game_kernel.results.targeting import TargetCellResult


class CastEvaluationStage(StrEnum):
    AVAILABILITY = "availability"
    RANGE = "range"
    LINE_OF_SIGHT = "line_of_sight"
    TARGET_CELL = "target_cell"


@dataclass(frozen=True, slots=True)
class CastEvaluationResult(MechanicResult):
    legal: bool | None = None
    failed_stages: tuple[CastEvaluationStage, ...] = ()
    availability: CastAvailabilityResult | None = None
    range: RangeResult | None = None
    line_of_sight: LineOfSightResult | None = None
    target_cell: TargetCellResult | None = None
    unsupported_fields: tuple[str, ...] = ()

    @classmethod
    def deterministic(
        cls,
        *,
        legal: bool,
        failed_stages: tuple[CastEvaluationStage, ...],
        availability: CastAvailabilityResult,
        range_result: RangeResult,
        line_of_sight: LineOfSightResult | None,
        target_cell: TargetCellResult,
        explanation: str,
    ) -> "CastEvaluationResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            legal=legal,
            failed_stages=failed_stages,
            availability=availability,
            range=range_result,
            line_of_sight=line_of_sight,
            target_cell=target_cell,
            explanation=explanation,
        )

    @classmethod
    def unsupported_compilation(
        cls,
        *,
        unsupported_fields: tuple[str, ...],
        explanation: str,
    ) -> "CastEvaluationResult":
        return cls(
            certainty=Certainty.UNSUPPORTED,
            legal=None,
            unsupported_fields=unsupported_fields,
            explanation=explanation,
        )

    @classmethod
    def incomplete(
        cls,
        *,
        missing_inputs: tuple[str, ...],
        availability: CastAvailabilityResult,
        range_result: RangeResult,
        line_of_sight: LineOfSightResult | None,
        target_cell: TargetCellResult,
    ) -> "CastEvaluationResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            missing_inputs=missing_inputs,
            legal=None,
            availability=availability,
            range=range_result,
            line_of_sight=line_of_sight,
            target_cell=target_cell,
            explanation="Cast legality requires the listed missing context values.",
        )

    @classmethod
    def indeterminate(
        cls,
        *,
        certainty: Certainty,
        availability: CastAvailabilityResult,
        range_result: RangeResult,
        line_of_sight: LineOfSightResult | None,
        target_cell: TargetCellResult,
        explanation: str,
    ) -> "CastEvaluationResult":
        if certainty in (Certainty.DETERMINISTIC, Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE):
            raise ValueError("indeterminate cast results require non-deterministic certainty")
        return cls(
            certainty=certainty,
            legal=None,
            availability=availability,
            range=range_result,
            line_of_sight=line_of_sight,
            target_cell=target_cell,
            explanation=explanation,
        )


@dataclass(frozen=True, slots=True)
class CastAreaResult(MechanicResult):
    legal_cells: tuple[CellId, ...] | None = None
    indeterminate_cells: tuple[CellId, ...] | None = None
    complete: bool = False
