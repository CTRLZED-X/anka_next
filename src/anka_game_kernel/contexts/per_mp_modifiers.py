from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.characteristics import CharacteristicKey
from anka_game_kernel.domain.ids import ActorId, SpellId


@dataclass(frozen=True, slots=True)
class PerMPUsedModifierState:
    """Caller/projector-owned reactive modifier applied once per MP spent on movement.

    This is deliberately generic. It records only the deterministic rule needed for
    hypothetical planning; authoritative effect lifetime remains owned by live state.
    """

    actor_id: ActorId
    source_spell_id: SpellId
    characteristic: CharacteristicKey
    characteristic_delta_per_mp: int
    range_delta_per_mp: int
    max_triggers: int
    triggers_applied: int = 0
    duration_turns: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.actor_id, ActorId):
            raise TypeError("actor_id must be an ActorId")
        if not isinstance(self.source_spell_id, SpellId):
            raise TypeError("source_spell_id must be a SpellId")
        if not isinstance(self.characteristic, CharacteristicKey):
            raise TypeError("characteristic must be a CharacteristicKey")
        for name, value in (
            ("characteristic_delta_per_mp", self.characteristic_delta_per_mp),
            ("range_delta_per_mp", self.range_delta_per_mp),
            ("max_triggers", self.max_triggers),
            ("triggers_applied", self.triggers_applied),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an int")
        if self.max_triggers < 1:
            raise ValueError("max_triggers must be >= 1")
        if self.triggers_applied < 0:
            raise ValueError("triggers_applied cannot be negative")
        if self.triggers_applied > self.max_triggers:
            raise ValueError("triggers_applied cannot exceed max_triggers")
        if self.duration_turns is not None:
            if isinstance(self.duration_turns, bool) or not isinstance(self.duration_turns, int):
                raise TypeError("duration_turns must be an int or None")
            if self.duration_turns < 1:
                raise ValueError("duration_turns must be >= 1 when supplied")

    @property
    def remaining_triggers(self) -> int:
        return self.max_triggers - self.triggers_applied
