from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.mechanics.range.model import RangeFailureReason
from anka_game_kernel.results.base import MechanicResult


@dataclass(frozen=True, slots=True)
class RangeResult(MechanicResult):
    legal: bool = False
    distance: int = 0
    effective_min_range: int = 0
    effective_max_range: int = 0
    failure: RangeFailureReason | None = None

    @classmethod
    def deterministic(
        cls,
        *,
        legal: bool,
        distance: int,
        effective_min_range: int,
        effective_max_range: int,
        failure: RangeFailureReason | None = None,
    ) -> "RangeResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            legal=legal,
            distance=distance,
            effective_min_range=effective_min_range,
            effective_max_range=effective_max_range,
            failure=failure,
        )
