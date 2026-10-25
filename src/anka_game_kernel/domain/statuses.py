from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.ids import ActorId, EffectId, SpellId, StateId


def _validate_turns_remaining(value: int | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("turns_remaining must be an int or None")
    if value < 1:
        raise ValueError("turns_remaining must be >= 1 for an active instance")


def _active_after_ticks(turns_remaining: int | None, ticks_ahead: int) -> bool | None:
    if isinstance(ticks_ahead, bool) or not isinstance(ticks_ahead, int):
        raise TypeError("ticks_ahead must be an int")
    if ticks_ahead < 0:
        raise ValueError("ticks_ahead cannot be negative")
    if ticks_ahead == 0:
        return True
    if turns_remaining is None:
        return None
    return turns_remaining > ticks_ahead


@dataclass(frozen=True, slots=True)
class ActiveStateInstance:
    state_id: StateId
    source_actor_id: ActorId | None = None
    source_spell_id: SpellId | None = None
    turns_remaining: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state_id, StateId):
            raise TypeError("state_id must be a StateId")
        if self.source_actor_id is not None and not isinstance(self.source_actor_id, ActorId):
            raise TypeError("source_actor_id must be an ActorId or None")
        if self.source_spell_id is not None and not isinstance(self.source_spell_id, SpellId):
            raise TypeError("source_spell_id must be a SpellId or None")
        _validate_turns_remaining(self.turns_remaining)

    def active_after_ticks(self, ticks_ahead: int) -> bool | None:
        return _active_after_ticks(self.turns_remaining, ticks_ahead)


@dataclass(frozen=True, slots=True)
class ActiveEffectInstance:
    effect_id: EffectId
    source_actor_id: ActorId | None = None
    source_spell_id: SpellId | None = None
    turns_remaining: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.effect_id, EffectId):
            raise TypeError("effect_id must be an EffectId")
        if self.source_actor_id is not None and not isinstance(self.source_actor_id, ActorId):
            raise TypeError("source_actor_id must be an ActorId or None")
        if self.source_spell_id is not None and not isinstance(self.source_spell_id, SpellId):
            raise TypeError("source_spell_id must be a SpellId or None")
        _validate_turns_remaining(self.turns_remaining)

    def active_after_ticks(self, ticks_ahead: int) -> bool | None:
        return _active_after_ticks(self.turns_remaining, ticks_ahead)
