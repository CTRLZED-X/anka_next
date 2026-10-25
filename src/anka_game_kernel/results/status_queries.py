from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.statuses import ActiveEffectInstance, ActiveStateInstance
from anka_game_kernel.results.base import MechanicResult


@dataclass(frozen=True, slots=True)
class ActiveStatesResult(MechanicResult):
    states: tuple[ActiveStateInstance, ...] | None = None

    @classmethod
    def known(cls, states: tuple[ActiveStateInstance, ...]) -> "ActiveStatesResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            states=states,
            explanation="Detailed active-state snapshot is known.",
        )

    @classmethod
    def incomplete(cls, *, missing_inputs: tuple[str, ...]) -> "ActiveStatesResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            states=None,
            missing_inputs=missing_inputs,
            explanation="Detailed active-state snapshot is not known.",
        )


@dataclass(frozen=True, slots=True)
class ActiveEffectsResult(MechanicResult):
    effects: tuple[ActiveEffectInstance, ...] | None = None

    @classmethod
    def known(cls, effects: tuple[ActiveEffectInstance, ...]) -> "ActiveEffectsResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            effects=effects,
            explanation="Detailed active-effect snapshot is known.",
        )

    @classmethod
    def incomplete(cls, *, missing_inputs: tuple[str, ...]) -> "ActiveEffectsResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            effects=None,
            missing_inputs=missing_inputs,
            explanation="Detailed active-effect snapshot is not known.",
        )


@dataclass(frozen=True, slots=True)
class StatusPresenceResult(MechanicResult):
    active: bool | None = None

    @classmethod
    def known(cls, active: bool) -> "StatusPresenceResult":
        if not isinstance(active, bool):
            raise TypeError("active must be a bool")
        return cls(
            certainty=Certainty.DETERMINISTIC,
            active=active,
            explanation="Status presence is deterministically known from the supplied snapshot.",
        )

    @classmethod
    def incomplete(cls, *, missing_inputs: tuple[str, ...]) -> "StatusPresenceResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            active=None,
            missing_inputs=missing_inputs,
            explanation="Status presence cannot be determined from the supplied snapshot.",
        )


@dataclass(frozen=True, slots=True)
class StatusTurnsResult(MechanicResult):
    active: bool | None = None
    turns_remaining: int | None = None

    @classmethod
    def known(cls, *, active: bool, turns_remaining: int) -> "StatusTurnsResult":
        if not isinstance(active, bool):
            raise TypeError("active must be a bool")
        if isinstance(turns_remaining, bool) or not isinstance(turns_remaining, int):
            raise TypeError("turns_remaining must be an int")
        if turns_remaining < 0:
            raise ValueError("turns_remaining cannot be negative")
        if active and turns_remaining < 1:
            raise ValueError("active status must have at least one turn remaining")
        if not active and turns_remaining != 0:
            raise ValueError("inactive status must report zero turns remaining")
        return cls(
            certainty=Certainty.DETERMINISTIC,
            active=active,
            turns_remaining=turns_remaining,
            explanation="Status duration is deterministically known from the supplied snapshot.",
        )

    @classmethod
    def incomplete(
        cls,
        *,
        active: bool | None,
        turns_remaining: int | None,
        missing_inputs: tuple[str, ...],
    ) -> "StatusTurnsResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            active=active,
            turns_remaining=turns_remaining,
            missing_inputs=missing_inputs,
            explanation="Status duration cannot be resolved without additional status-instance semantics.",
        )


@dataclass(frozen=True, slots=True)
class StatusForecastResult(MechanicResult):
    active: bool | None = None

    @classmethod
    def known(cls, active: bool) -> "StatusForecastResult":
        if not isinstance(active, bool):
            raise TypeError("active must be a bool")
        return cls(
            certainty=Certainty.DETERMINISTIC,
            active=active,
            explanation="Future status activity is deterministically known for the requested normalized duration offset.",
        )

    @classmethod
    def incomplete(cls, *, missing_inputs: tuple[str, ...]) -> "StatusForecastResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            active=None,
            missing_inputs=missing_inputs,
            explanation="Future status activity is not deterministically known from the supplied duration data.",
        )
