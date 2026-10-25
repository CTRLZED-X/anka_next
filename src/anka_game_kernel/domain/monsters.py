from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.ids import MonsterId
from anka_game_kernel.domain.provenance import Provenance


@dataclass(frozen=True, slots=True, order=True)
class MonsterGradeDefinition:
    grade: int
    level: int

    def __post_init__(self) -> None:
        if self.grade < 1:
            raise ValueError("monster grade must be >= 1")
        if self.level < 1:
            raise ValueError("monster level must be >= 1")


@dataclass(frozen=True, slots=True)
class MonsterDefinition:
    monster_id: MonsterId
    name_id: int
    name: str
    grades: tuple[MonsterGradeDefinition, ...]
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.name_id < 0:
            raise ValueError("monster name_id cannot be negative")
        if not self.name.strip():
            raise ValueError("monster name must not be empty")
        if not self.grades:
            raise ValueError("monster must contain at least one grade")
        grade_numbers = tuple(grade.grade for grade in self.grades)
        if grade_numbers != tuple(sorted(grade_numbers)):
            raise ValueError("monster grades must be ordered")
        if len(set(grade_numbers)) != len(grade_numbers):
            raise ValueError("monster cannot contain duplicate grade numbers")
