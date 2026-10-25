from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.ids import ActorId, CellId, SpellId


def _non_negative_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if value < 0:
        raise ValueError(f"{name} cannot be negative")


@dataclass(frozen=True, slots=True)
class CastRecord:
    caster_id: ActorId
    spell_id: SpellId
    grade: int | None
    target_actor_id: ActorId | None = None
    target_cell: CellId | None = None
    ap_spent: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.caster_id, ActorId):
            raise TypeError("caster_id must be an ActorId")
        if not isinstance(self.spell_id, SpellId):
            raise TypeError("spell_id must be a SpellId")
        if self.grade is not None:
            if isinstance(self.grade, bool) or not isinstance(self.grade, int):
                raise TypeError("grade must be an int or None")
            if self.grade < 1:
                raise ValueError("grade must be >= 1 when known")
        if self.target_actor_id is not None and not isinstance(self.target_actor_id, ActorId):
            raise TypeError("target_actor_id must be an ActorId or None")
        if self.target_cell is not None and not isinstance(self.target_cell, CellId):
            raise TypeError("target_cell must be a CellId or None")
        if self.ap_spent is not None:
            _non_negative_int("ap_spent", self.ap_spent)


@dataclass(frozen=True, slots=True)
class MovementRecord:
    actor_id: ActorId
    path: tuple[CellId, ...]
    mp_spent: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.actor_id, ActorId):
            raise TypeError("actor_id must be an ActorId")
        if not isinstance(self.path, tuple) or any(not isinstance(item, CellId) for item in self.path):
            raise TypeError("path must be a tuple of CellId values")
        if self.mp_spent is not None:
            _non_negative_int("mp_spent", self.mp_spent)


@dataclass(frozen=True, slots=True)
class TurnActionHistory:
    actor_id: ActorId
    round_number: int
    casts: tuple[CastRecord, ...] = ()
    movements: tuple[MovementRecord, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.actor_id, ActorId):
            raise TypeError("actor_id must be an ActorId")
        if isinstance(self.round_number, bool) or not isinstance(self.round_number, int):
            raise TypeError("round_number must be an int")
        if self.round_number < 1:
            raise ValueError("round_number must be >= 1")
        if not isinstance(self.casts, tuple) or any(not isinstance(item, CastRecord) for item in self.casts):
            raise TypeError("casts must be a tuple of CastRecord values")
        if not isinstance(self.movements, tuple) or any(
            not isinstance(item, MovementRecord) for item in self.movements
        ):
            raise TypeError("movements must be a tuple of MovementRecord values")
        if any(item.caster_id != self.actor_id for item in self.casts):
            raise ValueError("cast record actor must match turn actor")
        if any(item.actor_id != self.actor_id for item in self.movements):
            raise ValueError("movement record actor must match turn actor")

    def cast_count(self, spell_id: SpellId) -> int:
        if not isinstance(spell_id, SpellId):
            raise TypeError("spell_id must be a SpellId")
        return sum(item.spell_id == spell_id for item in self.casts)

    def cast_count_on_target(self, spell_id: SpellId, target_actor_id: ActorId) -> int | None:
        if not isinstance(spell_id, SpellId):
            raise TypeError("spell_id must be a SpellId")
        if not isinstance(target_actor_id, ActorId):
            raise TypeError("target_actor_id must be an ActorId")
        relevant = tuple(item for item in self.casts if item.spell_id == spell_id)
        # An observed cast with unresolved target identity may have been aimed at
        # this actor. Returning zero would silently convert incomplete evidence
        # into permission to exceed max-casts-per-target.
        if any(item.target_actor_id is None for item in relevant):
            return None
        return sum(item.target_actor_id == target_actor_id for item in relevant)
