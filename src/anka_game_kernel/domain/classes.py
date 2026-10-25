from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.ids import ClassId
from anka_game_kernel.domain.provenance import Provenance


@dataclass(frozen=True, slots=True, order=True)
class CharacteristicPointCostTier:
    starting_value: int
    points_per_characteristic: int

    def __post_init__(self) -> None:
        if self.starting_value < 0:
            raise ValueError("characteristic cost starting_value cannot be negative")
        if self.points_per_characteristic <= 0:
            raise ValueError("points_per_characteristic must be positive")


def _validate_curve(name: str, curve: tuple[CharacteristicPointCostTier, ...]) -> None:
    if not curve:
        raise ValueError(f"{name} cost curve must not be empty")
    starts = tuple(tier.starting_value for tier in curve)
    if starts != tuple(sorted(starts)):
        raise ValueError(f"{name} cost curve must be ordered by starting_value")
    if len(set(starts)) != len(starts):
        raise ValueError(f"{name} cost curve cannot repeat a starting_value")


@dataclass(frozen=True, slots=True)
class ClassCharacteristicCosts:
    strength: tuple[CharacteristicPointCostTier, ...]
    intelligence: tuple[CharacteristicPointCostTier, ...]
    chance: tuple[CharacteristicPointCostTier, ...]
    agility: tuple[CharacteristicPointCostTier, ...]
    vitality: tuple[CharacteristicPointCostTier, ...]
    wisdom: tuple[CharacteristicPointCostTier, ...]

    def __post_init__(self) -> None:
        for name in ("strength", "intelligence", "chance", "agility", "vitality", "wisdom"):
            _validate_curve(name, getattr(self, name))


@dataclass(frozen=True, slots=True)
class ClassDefinition:
    class_id: ClassId
    short_name_id: int
    name: str
    costs: ClassCharacteristicCosts
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.short_name_id < 0:
            raise ValueError("class short_name_id cannot be negative")
        if not self.name.strip():
            raise ValueError("class name must not be empty")
