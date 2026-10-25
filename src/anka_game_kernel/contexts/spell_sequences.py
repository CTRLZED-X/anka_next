from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.ids import ActorId, SpellId


@dataclass(frozen=True, slots=True)
class SpellTargetSequenceState:
    """Caller-owned target-sequence state for spells that charge one tracked target.

    The Kernel can project this state for hypothetical planning, but the live reducer remains
    authoritative for cross-turn expiry/trigger settlement.
    """

    caster_id: ActorId
    spell_id: SpellId
    target_actor_id: ActorId
    stacks: int
    turns_remaining: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.caster_id, ActorId):
            raise TypeError("caster_id must be an ActorId")
        if not isinstance(self.spell_id, SpellId):
            raise TypeError("spell_id must be a SpellId")
        if not isinstance(self.target_actor_id, ActorId):
            raise TypeError("target_actor_id must be an ActorId")
        if isinstance(self.stacks, bool) or not isinstance(self.stacks, int):
            raise TypeError("stacks must be an int")
        if self.stacks < 1:
            raise ValueError("stacks must be >= 1")
        if self.turns_remaining is not None:
            if isinstance(self.turns_remaining, bool) or not isinstance(self.turns_remaining, int):
                raise TypeError("turns_remaining must be an int or None")
            if self.turns_remaining < 1:
                raise ValueError("turns_remaining must be >= 1 when known")
