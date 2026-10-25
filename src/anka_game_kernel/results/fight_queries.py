from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.ids import ActorId, CellId
from anka_game_kernel.results.base import MechanicResult


@dataclass(frozen=True, slots=True)
class NearestActorResult(MechanicResult):
    actor_id: ActorId | None = None
    cell_id: CellId | None = None
    distance: int | None = None

    @classmethod
    def found(
        cls,
        *,
        actor_id: ActorId,
        cell_id: CellId,
        distance: int,
    ) -> "NearestActorResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            actor_id=actor_id,
            cell_id=cell_id,
            distance=distance,
            explanation="Nearest matching live actor is deterministically known from the snapshot.",
        )

    @classmethod
    def no_match(cls) -> "NearestActorResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            explanation="The complete supplied snapshot contains no matching live actor.",
        )

    @classmethod
    def incomplete(
        cls,
        *,
        missing_inputs: tuple[str, ...],
        explanation: str,
    ) -> "NearestActorResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            missing_inputs=missing_inputs,
            explanation=explanation,
        )
