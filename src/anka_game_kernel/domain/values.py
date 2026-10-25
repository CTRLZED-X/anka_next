from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ValueUnit(StrEnum):
    ABSOLUTE = "absolute"
    PERCENT = "percent"


class ValueReference(StrEnum):
    CASTER_CURRENT_HP = "caster_current_hp"
    CASTER_MAX_HP = "caster_max_hp"
    CASTER_ERODED_HP = "caster_eroded_hp"
    TARGET_CURRENT_HP = "target_current_hp"
    TARGET_MAX_HP = "target_max_hp"
    TARGET_ERODED_HP = "target_eroded_hp"
    TRIGGER_DAMAGE_RECEIVED = "trigger_damage_received"


def _require_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")


@dataclass(frozen=True, slots=True)
class AmountSpec:
    """Canonical scalar/interval amount.

    Percentage values are stored in basis points to avoid floating-point source
    ambiguity (10000 = 100%). A percentage is meaningless without an explicit
    value reference, so the reference is mandatory for percentage amounts and
    forbidden for absolute amounts.
    """

    minimum: int
    maximum: int
    unit: ValueUnit = ValueUnit.ABSOLUTE
    reference: ValueReference | None = None

    def __post_init__(self) -> None:
        _require_int("minimum", self.minimum)
        _require_int("maximum", self.maximum)
        if not isinstance(self.unit, ValueUnit):
            raise TypeError("unit must be a ValueUnit")
        if self.reference is not None and not isinstance(self.reference, ValueReference):
            raise TypeError("reference must be a ValueReference or None")
        if self.maximum < self.minimum:
            raise ValueError("maximum must be >= minimum")
        if self.unit is ValueUnit.PERCENT and self.reference is None:
            raise ValueError("percentage amount requires an explicit reference")
        if self.unit is ValueUnit.ABSOLUTE and self.reference is not None:
            raise ValueError("absolute amount cannot carry a percentage reference")

    @classmethod
    def fixed(cls, value: int) -> "AmountSpec":
        return cls(minimum=value, maximum=value)

    @classmethod
    def interval(cls, minimum: int, maximum: int) -> "AmountSpec":
        return cls(minimum=minimum, maximum=maximum)

    @classmethod
    def percent(
        cls,
        basis_points: int,
        *,
        reference: ValueReference,
    ) -> "AmountSpec":
        return cls(
            minimum=basis_points,
            maximum=basis_points,
            unit=ValueUnit.PERCENT,
            reference=reference,
        )

    @classmethod
    def percent_interval(
        cls,
        minimum_basis_points: int,
        maximum_basis_points: int,
        *,
        reference: ValueReference,
    ) -> "AmountSpec":
        return cls(
            minimum=minimum_basis_points,
            maximum=maximum_basis_points,
            unit=ValueUnit.PERCENT,
            reference=reference,
        )

    @property
    def deterministic(self) -> bool:
        return self.minimum == self.maximum


@dataclass(frozen=True, slots=True)
class ProbabilitySpec:
    """Canonical probability in basis points (0..10000)."""

    basis_points: int

    def __post_init__(self) -> None:
        _require_int("basis_points", self.basis_points)
        if not 0 <= self.basis_points <= 10000:
            raise ValueError("basis_points must be within 0..10000")

    @property
    def percent(self) -> float:
        return self.basis_points / 100
