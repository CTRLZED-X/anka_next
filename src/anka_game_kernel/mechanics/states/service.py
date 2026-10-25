from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.actors import ActorState
from anka_game_kernel.mechanics.states.model import StateTransitionSpec
from anka_game_kernel.results.states import StateTransitionResult


@dataclass(frozen=True, slots=True)
class StateService:
    """Pure state-set transitions over caller-owned ActorState snapshots."""

    def evaluate(
        self,
        actor: ActorState,
        spec: StateTransitionSpec,
    ) -> StateTransitionResult:
        if not spec.apply and not spec.remove:
            return StateTransitionResult.deterministic(
                before=actor.active_state_ids,
                after=actor.active_state_ids,
                explanation="The state transition is an explicit no-op.",
            )
        if actor.active_state_ids is None:
            return StateTransitionResult.incomplete(
                explanation="State transitions require the actor's active-state snapshot.",
            )

        before = actor.active_state_ids
        after = (before - spec.remove) | spec.apply
        return StateTransitionResult.deterministic(
            before=before,
            after=after,
            added=after - before,
            removed=before - after,
            explanation="State additions/removals were applied as a pure set transition.",
        )
