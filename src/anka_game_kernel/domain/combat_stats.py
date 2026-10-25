from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, StrEnum


class CombatStatKey(StrEnum):
    """Canonical ActorCombatStats fields that spell effects may modify temporarily."""

    LOCK = "lock"
    DODGE = "dodge"
    AP_LOSS_RESISTANCE = "ap_loss_resistance"
    MP_LOSS_RESISTANCE = "mp_loss_resistance"
    CRITICAL_DAMAGE_FIXED_RESISTANCE = "critical_damage_fixed_resistance"
    PUSHBACK_DAMAGE_FIXED_RESISTANCE = "pushback_damage_fixed_resistance"


class Element(str, Enum):
    NEUTRAL = "neutral"
    EARTH = "earth"
    FIRE = "fire"
    WATER = "water"
    AIR = "air"


def _validate_optional_int(name: str, value: int | None, *, non_negative: bool = False) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int or None")
    if non_negative and value < 0:
        raise ValueError(f"{name} cannot be negative")


@dataclass(frozen=True, slots=True)
class ElementalResistance:
    element: Element
    percent: int | None = None
    fixed: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.element, Element):
            raise TypeError("element must be an Element")
        _validate_optional_int("percent", self.percent)
        _validate_optional_int("fixed", self.fixed)


@dataclass(frozen=True, slots=True)
class DamageReceivedModifiers:
    melee_percent: int | None = None
    ranged_percent: int | None = None
    weapon_percent: int | None = None
    spell_percent: int | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("melee_percent", self.melee_percent),
            ("ranged_percent", self.ranged_percent),
            ("weapon_percent", self.weapon_percent),
            ("spell_percent", self.spell_percent),
        ):
            _validate_optional_int(name, value)


@dataclass(frozen=True, slots=True)
class ActorCombatStats:
    shield_hp: int | None = None
    max_ap: int | None = None
    max_mp: int | None = None
    range_bonus: int | None = None
    lock: int | None = None
    dodge: int | None = None
    ap_loss_resistance: int | None = None
    mp_loss_resistance: int | None = None
    critical_damage_fixed_resistance: int | None = None
    pushback_damage_fixed_resistance: int | None = None
    visible: bool | None = None
    elemental_resistances: tuple[ElementalResistance, ...] = ()
    damage_received: DamageReceivedModifiers | None = None

    def __post_init__(self) -> None:
        for name, value, non_negative in (
            ("shield_hp", self.shield_hp, True),
            ("max_ap", self.max_ap, True),
            ("max_mp", self.max_mp, True),
            ("range_bonus", self.range_bonus, False),
            ("lock", self.lock, False),
            ("dodge", self.dodge, False),
            ("ap_loss_resistance", self.ap_loss_resistance, False),
            ("mp_loss_resistance", self.mp_loss_resistance, False),
            ("critical_damage_fixed_resistance", self.critical_damage_fixed_resistance, False),
            ("pushback_damage_fixed_resistance", self.pushback_damage_fixed_resistance, False),
        ):
            _validate_optional_int(name, value, non_negative=non_negative)

        if self.visible is not None and not isinstance(self.visible, bool):
            raise TypeError("visible must be a bool or None")
        if self.damage_received is not None and not isinstance(
            self.damage_received, DamageReceivedModifiers
        ):
            raise TypeError("damage_received must be DamageReceivedModifiers or None")
        if any(not isinstance(item, ElementalResistance) for item in self.elemental_resistances):
            raise TypeError("elemental_resistances must contain ElementalResistance values")

        elements = [item.element for item in self.elemental_resistances]
        if len(set(elements)) != len(elements):
            raise ValueError("actor combat stats cannot contain duplicate elemental resistance elements")

    def elemental_resistance(self, element: Element) -> ElementalResistance | None:
        if not isinstance(element, Element):
            raise TypeError("element must be an Element")
        for resistance in self.elemental_resistances:
            if resistance.element is element:
                return resistance
        return None
