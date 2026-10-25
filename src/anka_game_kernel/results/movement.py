from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.ids import CellId
from anka_game_kernel.mechanics.movement.model import MovementFailureReason, ReachableCell
from anka_game_kernel.results.base import MechanicResult


@dataclass(frozen=True, slots=True)
class MovementResult(MechanicResult):
    reachable: bool | None = None
    path: tuple[CellId, ...] = ()
    failure: MovementFailureReason | None = None

    @property
    def step_count(self) -> int | None:
        if self.reachable is not True:
            return None
        return max(0, len(self.path) - 1)

    @classmethod
    def deterministic(
        cls,
        *,
        reachable: bool,
        path: tuple[CellId, ...] = (),
        failure: MovementFailureReason | None = None,
        explanation: str | None = None,
    ) -> "MovementResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            reachable=reachable,
            path=path,
            failure=failure,
            explanation=explanation,
        )

    @classmethod
    def incomplete(
        cls,
        *,
        missing_input: str,
        explanation: str | None = None,
    ) -> "MovementResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            missing_inputs=(missing_input,),
            reachable=None,
            explanation=explanation,
        )


@dataclass(frozen=True, slots=True)
class ReachableCellsResult(MechanicResult):
    reachable: tuple[ReachableCell, ...] = ()

    @property
    def cells(self) -> tuple[CellId, ...]:
        return tuple(item.cell_id for item in self.reachable)

    def distance_to(self, cell_id: CellId) -> int | None:
        for item in self.reachable:
            if item.cell_id == cell_id:
                return item.distance
        return None

    @classmethod
    def deterministic(
        cls,
        reachable: tuple[ReachableCell, ...],
        *,
        explanation: str | None = None,
    ) -> "ReachableCellsResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            reachable=reachable,
            explanation=explanation,
        )

    @classmethod
    def incomplete(
        cls,
        *,
        missing_input: str,
        explanation: str | None = None,
    ) -> "ReachableCellsResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            missing_inputs=(missing_input,),
            explanation=explanation,
        )
