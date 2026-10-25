from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.combat_stats import ElementalResistance
from anka_game_kernel.results.base import MechanicResult


@dataclass(frozen=True, slots=True)
class HealthPercentResult(MechanicResult):
    percent: float | None = None

    @classmethod
    def known(cls, percent: float) -> "HealthPercentResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            percent=percent,
            explanation="Health percentage is deterministically known from current and maximum HP.",
        )

    @classmethod
    def incomplete(cls, *, missing_inputs: tuple[str, ...]) -> "HealthPercentResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            missing_inputs=missing_inputs,
            explanation="Health percentage requires complete current and maximum HP inputs.",
        )


@dataclass(frozen=True, slots=True)
class EffectiveHealthResult(MechanicResult):
    value: int | None = None

    @classmethod
    def known(cls, value: int) -> "EffectiveHealthResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            value=value,
            explanation="Effective health is current HP plus known current shield HP.",
        )

    @classmethod
    def incomplete(cls, *, missing_inputs: tuple[str, ...]) -> "EffectiveHealthResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            missing_inputs=missing_inputs,
            explanation="Effective health requires both current HP and current shield HP.",
        )


@dataclass(frozen=True, slots=True)
class ResourceSnapshotResult(MechanicResult):
    current_ap: int | None = None
    max_ap: int | None = None
    current_mp: int | None = None
    max_mp: int | None = None
    range_bonus: int | None = None

    @classmethod
    def known(
        cls,
        *,
        current_ap: int,
        max_ap: int,
        current_mp: int,
        max_mp: int,
        range_bonus: int,
    ) -> "ResourceSnapshotResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            current_ap=current_ap,
            max_ap=max_ap,
            current_mp=current_mp,
            max_mp=max_mp,
            range_bonus=range_bonus,
            explanation="Actor action, movement, and range resources are completely known.",
        )

    @classmethod
    def incomplete(
        cls,
        *,
        current_ap: int | None,
        max_ap: int | None,
        current_mp: int | None,
        max_mp: int | None,
        range_bonus: int | None,
        missing_inputs: tuple[str, ...],
    ) -> "ResourceSnapshotResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            current_ap=current_ap,
            max_ap=max_ap,
            current_mp=current_mp,
            max_mp=max_mp,
            range_bonus=range_bonus,
            missing_inputs=missing_inputs,
            explanation="Actor resource snapshot is partial because one or more inputs are unknown.",
        )


@dataclass(frozen=True, slots=True)
class ElementalResistanceResult(MechanicResult):
    resistance: ElementalResistance | None = None

    @classmethod
    def known(cls, resistance: ElementalResistance) -> "ElementalResistanceResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            resistance=resistance,
            explanation="Elemental resistance is explicitly present in the canonical actor profile.",
        )

    @classmethod
    def incomplete(
        cls, *, missing_inputs: tuple[str, ...]
    ) -> "ElementalResistanceResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            missing_inputs=missing_inputs,
            explanation="Elemental resistance is not completely known in the supplied actor profile.",
        )


@dataclass(frozen=True, slots=True)
class LockDodgeResult(MechanicResult):
    lock: int | None = None
    dodge: int | None = None

    @classmethod
    def known(cls, *, lock: int, dodge: int) -> "LockDodgeResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            lock=lock,
            dodge=dodge,
            explanation="Actor lock and dodge characteristics are completely known.",
        )

    @classmethod
    def incomplete(
        cls,
        *,
        lock: int | None,
        dodge: int | None,
        missing_inputs: tuple[str, ...],
    ) -> "LockDodgeResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            lock=lock,
            dodge=dodge,
            missing_inputs=missing_inputs,
            explanation="Actor lock/dodge snapshot is partial because one or more inputs are unknown.",
        )

@dataclass(frozen=True, slots=True)
class SummonCountResult(MechanicResult):
    count: int | None = None

    @classmethod
    def known(cls, count: int) -> "SummonCountResult":
        if isinstance(count, bool) or not isinstance(count, int):
            raise TypeError("count must be an int")
        if count < 0:
            raise ValueError("count cannot be negative")
        return cls(
            certainty=Certainty.DETERMINISTIC,
            count=count,
            explanation="Current on-field summon count is deterministically known.",
        )

    @classmethod
    def incomplete(
        cls,
        *,
        count: int,
        missing_inputs: tuple[str, ...],
    ) -> "SummonCountResult":
        if isinstance(count, bool) or not isinstance(count, int):
            raise TypeError("count must be an int")
        if count < 0:
            raise ValueError("count cannot be negative")
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            count=count,
            missing_inputs=missing_inputs,
            explanation="Known summons are counted, but unresolved actor relationships could change the total.",
        )
