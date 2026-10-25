from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.ids import CellId
from anka_game_kernel.mechanics.displacement.model import DisplacementBlockReason
from anka_game_kernel.results.base import MechanicResult


@dataclass(frozen=True, slots=True)
class CollisionResult(MechanicResult):
    collided: bool | None = None
    moved_distance: int | None = None
    remaining_distance: int | None = None
    blocked_cell: CellId | None = None
    block_reason: DisplacementBlockReason | None = None

    @classmethod
    def deterministic(
        cls,
        *,
        collided: bool,
        moved_distance: int,
        remaining_distance: int,
        blocked_cell: CellId | None = None,
        block_reason: DisplacementBlockReason | None = None,
        explanation: str | None = None,
    ) -> "CollisionResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            collided=collided,
            moved_distance=moved_distance,
            remaining_distance=remaining_distance,
            blocked_cell=blocked_cell,
            block_reason=block_reason,
            explanation=explanation,
        )

    @classmethod
    def indeterminate(
        cls,
        *,
        certainty: Certainty,
        missing_inputs: tuple[str, ...] = (),
        explanation: str | None = None,
    ) -> "CollisionResult":
        return cls(
            certainty=certainty,
            missing_inputs=missing_inputs,
            collided=None,
            explanation=explanation,
        )
