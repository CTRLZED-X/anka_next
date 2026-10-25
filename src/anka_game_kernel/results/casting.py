from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.results.base import MechanicResult


class CastAvailabilityFailureReason(StrEnum):
    NOT_ENOUGH_AP = "not_enough_ap"
    MAX_CASTS_PER_TURN = "max_casts_per_turn"
    MAX_GLOBAL_CASTS_PER_TURN = "max_global_casts_per_turn"
    COOLDOWN_ACTIVE = "cooldown_active"
    MAX_CASTS_PER_TARGET = "max_casts_per_target"
    STATE_CRITERION_FAILED = "state_criterion_failed"
    NO_SUMMON_SLOT = "no_summon_slot"


@dataclass(frozen=True, slots=True)
class CastAvailabilityResult(MechanicResult):
    legal: bool | None = None
    failure: CastAvailabilityFailureReason | None = None
    cooldown_remaining: int | None = None

    @classmethod
    def deterministic(
        cls,
        *,
        legal: bool,
        failure: CastAvailabilityFailureReason | None = None,
        cooldown_remaining: int | None = None,
        explanation: str | None = None,
    ) -> "CastAvailabilityResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            legal=legal,
            failure=failure,
            cooldown_remaining=cooldown_remaining,
            explanation=explanation,
        )

    @classmethod
    def incomplete(
        cls,
        *,
        missing_inputs: tuple[str, ...],
        explanation: str,
    ) -> "CastAvailabilityResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            missing_inputs=missing_inputs,
            legal=None,
            explanation=explanation,
        )
