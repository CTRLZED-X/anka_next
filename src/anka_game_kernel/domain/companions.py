from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.ids import CompanionId, CompanionSpellId, SpellId
from anka_game_kernel.domain.provenance import Provenance


@dataclass(frozen=True, slots=True, order=True)
class CompanionSpellGradeThreshold:
    grade: int
    minimum_level: int

    def __post_init__(self) -> None:
        if self.grade < 1:
            raise ValueError("companion spell grade must be >= 1")
        if self.minimum_level < 0:
            raise ValueError("companion spell minimum level cannot be negative")


@dataclass(frozen=True, slots=True)
class CompanionSpellDefinition:
    companion_spell_id: CompanionSpellId
    companion_id: CompanionId
    spell_id: SpellId
    grade_by_level: tuple[CompanionSpellGradeThreshold, ...]
    provenance: Provenance

    def __post_init__(self) -> None:
        if not self.grade_by_level:
            raise ValueError("companion spell must contain at least one grade threshold")
        grades = tuple(item.grade for item in self.grade_by_level)
        levels = tuple(item.minimum_level for item in self.grade_by_level)
        if grades != tuple(sorted(grades)) or len(set(grades)) != len(grades):
            raise ValueError("companion spell grade thresholds must be unique and ordered")
        if any(a >= b for a, b in zip(levels, levels[1:])):
            raise ValueError("companion spell minimum levels must increase strictly")


@dataclass(frozen=True, slots=True)
class CompanionDefinition:
    companion_id: CompanionId
    name_id: int
    name: str
    companion_spell_ids: tuple[CompanionSpellId, ...]
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.name_id < 0:
            raise ValueError("companion name_id cannot be negative")
        if not self.name.strip():
            raise ValueError("companion name must not be empty")
        if len(set(self.companion_spell_ids)) != len(self.companion_spell_ids):
            raise ValueError("companion cannot contain duplicate companion-spell ids")
