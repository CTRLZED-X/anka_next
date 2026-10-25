from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CharacteristicKey(StrEnum):
    """Kernel-owned semantic characteristics whose raw source IDs are not yet authoritative.

    Resource, positioning, lock/dodge, and resistance values that already have a canonical
    home in ActorCombatStats are intentionally not duplicated here.
    """

    STRENGTH = "strength"
    INTELLIGENCE = "intelligence"
    CHANCE = "chance"
    AGILITY = "agility"
    POWER = "power"
    VITALITY = "vitality"
    INITIATIVE = "initiative"
    PROSPECTING = "prospecting"
    SUMMONS = "summons"
    CRITICAL_CHANCE = "critical_chance"
    CRITICAL_DAMAGE = "critical_damage"
    PUSHBACK_DAMAGE = "pushback_damage"
    AP_REDUCTION = "ap_reduction"
    MP_REDUCTION = "mp_reduction"
    FIXED_DAMAGE = "fixed_damage"
    PERCENT_DAMAGE = "percent_damage"
    DISTANCE_DAMAGE_PERCENT = "distance_damage_percent"
    DAMAGE_RECEIVED_PERCENT = "damage_received_percent"
    EROSION_PERCENT = "erosion_percent"
    HEAL_RECEIVED_PERCENT = "heal_received_percent"
    HEAL_BONUS = "heal_bonus"


@dataclass(frozen=True, slots=True)
class SemanticCharacteristicValue:
    key: CharacteristicKey
    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.key, CharacteristicKey):
            raise TypeError("key must be a CharacteristicKey")
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise TypeError("semantic characteristic value must be an int")


@dataclass(frozen=True, slots=True)
class SemanticCharacteristics:
    values: tuple[SemanticCharacteristicValue, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.values, tuple):
            raise TypeError("values must be a tuple of SemanticCharacteristicValue values")
        if any(not isinstance(item, SemanticCharacteristicValue) for item in self.values):
            raise TypeError("values must contain only SemanticCharacteristicValue values")
        keys = tuple(item.key for item in self.values)
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate semantic characteristic key")

    def get(self, key: CharacteristicKey) -> int | None:
        if not isinstance(key, CharacteristicKey):
            raise TypeError("key must be a CharacteristicKey")
        for item in self.values:
            if item.key is key:
                return item.value
        return None
