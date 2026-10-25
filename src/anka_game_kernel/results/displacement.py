from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.ids import CellId
from anka_game_kernel.mechanics.displacement.model import DisplacementBlockReason
from anka_game_kernel.results.base import MechanicResult


@dataclass(frozen=True, slots=True)
class DisplacementResult(MechanicResult):
    completed: bool | None = None
    traversed_cells: tuple[CellId, ...] = ()
    blocked_cell: CellId | None = None
    failure: DisplacementBlockReason | None = None

    @property
    def step_count(self) -> int:
        return max(0, len(self.traversed_cells) - 1)

    @classmethod
    def deterministic(
        cls,
        *,
        completed: bool,
        traversed_cells: tuple[CellId, ...],
        blocked_cell: CellId | None = None,
        failure: DisplacementBlockReason | None = None,
        explanation: str | None = None,
    ) -> "DisplacementResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            completed=completed,
            traversed_cells=traversed_cells,
            blocked_cell=blocked_cell,
            failure=failure,
            explanation=explanation,
        )

    @classmethod
    def unsupported(
        cls,
        *,
        explanation: str,
    ) -> "DisplacementResult":
        return cls(
            certainty=Certainty.UNSUPPORTED,
            completed=None,
            explanation=explanation,
        )

    @classmethod
    def incomplete(
        cls,
        *,
        missing_input: str,
        traversed_cells: tuple[CellId, ...],
        explanation: str,
    ) -> "DisplacementResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            missing_inputs=(missing_input,),
            completed=None,
            traversed_cells=traversed_cells,
            explanation=explanation,
        )


@dataclass(frozen=True, slots=True)
class LinearDisplacementPlanResult(MechanicResult):
    path: tuple[CellId, ...] = ()
    requested_distance: int = 0
    boundary_reached: bool = False

    @classmethod
    def deterministic(
        cls,
        *,
        path: tuple[CellId, ...],
        requested_distance: int,
        boundary_reached: bool = False,
        explanation: str | None = None,
    ) -> "LinearDisplacementPlanResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            path=path,
            requested_distance=requested_distance,
            boundary_reached=boundary_reached,
            explanation=explanation,
        )

    @classmethod
    def unsupported(
        cls,
        *,
        requested_distance: int,
        explanation: str,
    ) -> "LinearDisplacementPlanResult":
        return cls(
            certainty=Certainty.UNSUPPORTED,
            path=(),
            requested_distance=requested_distance,
            boundary_reached=False,
            explanation=explanation,
        )
