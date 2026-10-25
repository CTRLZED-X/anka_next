from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.results.collision import CollisionResult
from anka_game_kernel.results.displacement import DisplacementResult


@dataclass(frozen=True, slots=True)
class CollisionService:
    """Derive structural collision facts from a forced-displacement result.

    This service intentionally does not calculate collision damage. It only
    reports whether movement was blocked and how much requested displacement
    remained when the block occurred.
    """

    def evaluate(
        self,
        displacement: DisplacementResult,
        *,
        requested_distance: int,
    ) -> CollisionResult:
        if isinstance(requested_distance, bool) or not isinstance(requested_distance, int):
            raise TypeError("requested_distance must be an int")
        if requested_distance < 0:
            raise ValueError("requested_distance cannot be negative")

        moved_distance = displacement.step_count
        if moved_distance > requested_distance:
            raise ValueError(
                "requested_distance cannot be less than the already moved distance"
            )

        if displacement.certainty is Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE:
            return CollisionResult.indeterminate(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                missing_inputs=displacement.missing_inputs,
                explanation=displacement.explanation,
            )
        if displacement.certainty is Certainty.UNSUPPORTED:
            return CollisionResult.indeterminate(
                certainty=Certainty.UNSUPPORTED,
                explanation=displacement.explanation,
            )
        if displacement.certainty in (Certainty.UNKNOWN, Certainty.LIVE_REQUIRED):
            return CollisionResult.indeterminate(
                certainty=displacement.certainty,
                missing_inputs=displacement.missing_inputs,
                explanation=displacement.explanation,
            )

        if displacement.completed is True:
            return CollisionResult.deterministic(
                collided=False,
                moved_distance=moved_distance,
                remaining_distance=requested_distance - moved_distance,
                explanation="The requested forced displacement completed without a blocker.",
            )
        if displacement.completed is False:
            return CollisionResult.deterministic(
                collided=True,
                moved_distance=moved_distance,
                remaining_distance=requested_distance - moved_distance,
                blocked_cell=displacement.blocked_cell,
                block_reason=displacement.failure,
                explanation="Forced displacement stopped before the requested distance was completed.",
            )

        return CollisionResult.indeterminate(
            certainty=Certainty.UNKNOWN,
            explanation="The displacement result did not contain a resolvable completion state.",
        )
