from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.ids import SpellId, SpellLevelId
from anka_game_kernel.domain.provenance import Provenance
from anka_game_kernel.domain.state_criteria import StateCriterion


@dataclass(frozen=True, slots=True)
class SpellGradeDefinition:
    level_id: SpellLevelId
    spell_id: SpellId
    grade: int
    ap_cost: int
    min_range: int
    max_range: int
    max_cast_per_turn: int
    max_cast_per_target: int
    min_cast_interval: int
    initial_cooldown: int
    min_player_level: int
    state_criterion: StateCriterion | None
    cast_in_line: bool
    cast_in_diagonal: bool
    requires_line_of_sight: bool
    need_free_cell: bool
    need_taken_cell: bool
    range_modifiable: bool
    can_summon: bool
    provenance: Provenance
    max_global_cast_per_turn: int = 0

    def __post_init__(self) -> None:
        if self.grade < 1:
            raise ValueError("spell grade must be >= 1")
        for name, value in (
            ("ap_cost", self.ap_cost),
            ("min_range", self.min_range),
            ("max_range", self.max_range),
            ("max_cast_per_target", self.max_cast_per_target),
            ("min_cast_interval", self.min_cast_interval),
            ("min_player_level", self.min_player_level),
        ):
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.max_cast_per_turn < -1:
            raise ValueError("max_cast_per_turn cannot be below the unresolved -1 sentinel")
        if self.max_global_cast_per_turn < 0:
            raise ValueError("max_global_cast_per_turn cannot be negative")
        if self.initial_cooldown < -1:
            raise ValueError("initial_cooldown cannot be below the unresolved -1 sentinel")


@dataclass(frozen=True, slots=True)
class SpellDefinition:
    spell_id: SpellId
    name_id: int
    description_id: int
    name: str
    grades: tuple[SpellGradeDefinition, ...]
    provenance: Provenance

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("spell name must not be empty")
        if len({grade.level_id for grade in self.grades}) != len(self.grades):
            raise ValueError("spell cannot contain duplicate spell-level ids")
        if any(grade.spell_id != self.spell_id for grade in self.grades):
            raise ValueError("spell grade backreference does not match spell id")
        grade_numbers = tuple(grade.grade for grade in self.grades)
        if grade_numbers != tuple(sorted(grade_numbers)):
            raise ValueError("spell grades must be ordered by grade")
        if len(set(grade_numbers)) != len(grade_numbers):
            raise ValueError("spell cannot contain duplicate grade numbers")
