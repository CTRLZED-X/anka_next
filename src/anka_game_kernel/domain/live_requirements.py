from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from anka_game_kernel.domain.ids import ActorId, SpellId


class LiveRequirementKind(StrEnum):
    DAMAGE_AMOUNT = "damage_amount"
    TRIGGER_DAMAGE_EVENT = "trigger_damage_event"
    HP_AFTER_DAMAGE = "hp_after_damage"
    HEAL_AMOUNT = "heal_amount"
    HP_AFTER_HEAL = "hp_after_heal"
    SHIELD_AMOUNT = "shield_amount"
    SHIELD_REMAINING = "shield_remaining"
    AP_CHANGE_RESULT = "ap_change_result"
    MP_CHANGE_RESULT = "mp_change_result"
    COLLISION_DAMAGE = "collision_damage"
    RANDOM_OUTCOME = "random_outcome"
    STATUS_LIFECYCLE = "status_lifecycle"
    SUMMON_ACTOR_IDENTITY = "summon_actor_identity"
    SUMMON_RUNTIME_STATS = "summon_runtime_stats"


@dataclass(frozen=True, slots=True)
class LiveObservationRequirement:
    kind: LiveRequirementKind
    actor_id: ActorId | None = None
    source_spell_id: SpellId | None = None
    effect_order: int | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, LiveRequirementKind):
            raise TypeError("kind must be a LiveRequirementKind")
        if self.actor_id is not None and not isinstance(self.actor_id, ActorId):
            raise TypeError("actor_id must be an ActorId or None")
        if self.source_spell_id is not None and not isinstance(self.source_spell_id, SpellId):
            raise TypeError("source_spell_id must be a SpellId or None")
        if self.effect_order is not None:
            if isinstance(self.effect_order, bool) or not isinstance(self.effect_order, int):
                raise TypeError("effect_order must be an int or None")
            if self.effect_order < 0:
                raise ValueError("effect_order cannot be negative")
        if self.reason is not None and not isinstance(self.reason, str):
            raise TypeError("reason must be a str or None")
