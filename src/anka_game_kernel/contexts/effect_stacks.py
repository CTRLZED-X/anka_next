from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.ids import ActorId, SpellId


@dataclass(frozen=True, slots=True)
class EffectStackState:
    """Caller/projector-owned stack state for one declarative spell effect on one actor.

    This state is intentionally generic and source-effect keyed. It lets hypothetical
    same-turn planning respect per-target ``max_stacks`` without treating a spell-wide
    cast count as if every affected actor already had the modifier. Authoritative
    cross-turn expiry remains owned by live state.
    """

    actor_id: ActorId
    source_spell_id: SpellId
    effect_order: int
    stacks: int

    def __post_init__(self) -> None:
        if not isinstance(self.actor_id, ActorId):
            raise TypeError("actor_id must be an ActorId")
        if not isinstance(self.source_spell_id, SpellId):
            raise TypeError("source_spell_id must be a SpellId")
        if isinstance(self.effect_order, bool) or not isinstance(self.effect_order, int):
            raise TypeError("effect_order must be an int")
        if self.effect_order < 0:
            raise ValueError("effect_order cannot be negative")
        if isinstance(self.stacks, bool) or not isinstance(self.stacks, int):
            raise TypeError("stacks must be an int")
        if self.stacks < 1:
            raise ValueError("stacks must be >= 1")
