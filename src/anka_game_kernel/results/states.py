from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.ids import StateId
from anka_game_kernel.results.base import MechanicResult


@dataclass(frozen=True, slots=True)
class StateTransitionResult(MechanicResult):
    before: frozenset[StateId] | None = None
    after: frozenset[StateId] | None = None
    added: frozenset[StateId] = frozenset()
    removed: frozenset[StateId] = frozenset()

    @classmethod
    def deterministic(
        cls,
        *,
        before: frozenset[StateId] | None,
        after: frozenset[StateId] | None,
        added: frozenset[StateId] = frozenset(),
        removed: frozenset[StateId] = frozenset(),
        explanation: str | None = None,
    ) -> "StateTransitionResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            before=before,
            after=after,
            added=added,
            removed=removed,
            explanation=explanation,
        )

    @classmethod
    def incomplete(cls, *, explanation: str) -> "StateTransitionResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            missing_inputs=("active_state_ids",),
            before=None,
            after=None,
            explanation=explanation,
        )
