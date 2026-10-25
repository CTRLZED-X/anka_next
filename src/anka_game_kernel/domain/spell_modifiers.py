from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from anka_game_kernel.domain.ids import ClassId, SpellId


class SpellRangeBound(StrEnum):
    MINIMUM = "minimum"
    MAXIMUM = "maximum"


class SpellSemanticTag(StrEnum):
    OFFENSIVE = "offensive"


@dataclass(frozen=True, slots=True)
class ProjectedSpellRangeModifier:
    """Caller-owned hypothetical spell-range modifier produced by a projected cast."""

    source_spell_id: SpellId
    bound: SpellRangeBound
    amount: int
    affected_class_id: ClassId | None = None
    # Live protocol modifiers are emitted per affected spell. Keeping an exact
    # optional selector lets the platform transport those certified identities
    # without broadening the modifier to an entire class/tag family.
    affected_spell_ids: frozenset[SpellId] = frozenset()
    required_tags: frozenset[SpellSemanticTag] = frozenset()
    duration_turns: int | None = None
    max_stacks: int | None = None
    dispellable: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_spell_id, SpellId):
            raise TypeError("source_spell_id must be a SpellId")
        if not isinstance(self.bound, SpellRangeBound):
            raise TypeError("bound must be a SpellRangeBound")
        if isinstance(self.amount, bool) or not isinstance(self.amount, int):
            raise TypeError("amount must be an int")
        if self.affected_class_id is not None and not isinstance(self.affected_class_id, ClassId):
            raise TypeError("affected_class_id must be a ClassId or None")
        if not isinstance(self.affected_spell_ids, frozenset) or any(
            not isinstance(value, SpellId) for value in self.affected_spell_ids
        ):
            raise TypeError("affected_spell_ids must be a frozenset of SpellId values")
        if not isinstance(self.required_tags, frozenset) or any(
            not isinstance(value, SpellSemanticTag) for value in self.required_tags
        ):
            raise TypeError("required_tags must be a frozenset of SpellSemanticTag values")
        if self.duration_turns is not None:
            if isinstance(self.duration_turns, bool) or not isinstance(self.duration_turns, int):
                raise TypeError("duration_turns must be an int or None")
            if self.duration_turns < 0:
                raise ValueError("duration_turns cannot be negative")
        if self.max_stacks is not None:
            if isinstance(self.max_stacks, bool) or not isinstance(self.max_stacks, int):
                raise TypeError("max_stacks must be an int or None")
            if self.max_stacks < 1:
                raise ValueError("max_stacks must be >= 1 when supplied")
        if self.dispellable is not None and not isinstance(self.dispellable, bool):
            raise TypeError("dispellable must be a bool or None")
