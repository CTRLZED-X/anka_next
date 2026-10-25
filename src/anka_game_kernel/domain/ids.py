from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class _SemanticIntId:
    value: int
    MIN_VALUE: ClassVar[int] = 1

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise TypeError(f"{type(self).__name__} requires an int value")
        if self.value < self.MIN_VALUE:
            raise ValueError(
                f"{type(self).__name__} must be >= {self.MIN_VALUE}, got {self.value}"
            )

    def __int__(self) -> int:
        return self.value

    def __index__(self) -> int:
        return self.value

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class MapId(_SemanticIntId):
    pass


@dataclass(frozen=True, slots=True)
class CellId(_SemanticIntId):
    MIN_VALUE: ClassVar[int] = 0


@dataclass(frozen=True, slots=True)
class SpellId(_SemanticIntId):
    MIN_VALUE: ClassVar[int] = 0




@dataclass(frozen=True, slots=True)
class SpellLevelId(_SemanticIntId):
    pass

@dataclass(frozen=True, slots=True)
class EffectId(_SemanticIntId):
    MIN_VALUE: ClassVar[int] = 0


@dataclass(frozen=True, slots=True)
class StateId(_SemanticIntId):
    MIN_VALUE: ClassVar[int] = 0


@dataclass(frozen=True, slots=True)
class CharacteristicId(_SemanticIntId):
    # Dofus fighter characteristic arrays use raw characteristic id 0 in current
    # live traffic (for example jwj actor bootstraps).  Canonical state preserves
    # raw protocol identity, so the Kernel raw-id wrapper must represent zero.
    # Semantic interpretation remains separate and evidence-gated.
    MIN_VALUE: ClassVar[int] = 0


@dataclass(frozen=True, slots=True)
class SpellVariantId(_SemanticIntId):
    pass


@dataclass(frozen=True, slots=True)
class ClassId(_SemanticIntId):
    pass


@dataclass(frozen=True, slots=True)
class MonsterId(_SemanticIntId):
    pass


@dataclass(frozen=True, slots=True)
class CreatureId(_SemanticIntId):
    """Static creature/template identity carried by live fight actors and summons."""

    pass


@dataclass(frozen=True, slots=True)
class SuperAreaId(_SemanticIntId):
    MIN_VALUE: ClassVar[int] = 0


@dataclass(frozen=True, slots=True)
class AreaId(_SemanticIntId):
    MIN_VALUE: ClassVar[int] = 0


@dataclass(frozen=True, slots=True)
class SubAreaId(_SemanticIntId):
    pass


@dataclass(frozen=True, slots=True)
class WorldMapId(_SemanticIntId):
    MIN_VALUE: ClassVar[int] = 0


@dataclass(frozen=True, slots=True)
class _SignedSemanticIntId:
    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise TypeError(f"{type(self).__name__} requires an int value")

    def __int__(self) -> int:
        return self.value

    def __index__(self) -> int:
        return self.value

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class ActorId(_SignedSemanticIntId):
    pass


@dataclass(frozen=True, slots=True)
class TeamId(_SignedSemanticIntId):
    pass


@dataclass(frozen=True, slots=True)
class CompanionId(_SemanticIntId):
    pass


@dataclass(frozen=True, slots=True)
class CompanionSpellId(_SemanticIntId):
    pass


@dataclass(frozen=True, slots=True)
class MonsterRaceId(_SignedSemanticIntId):
    pass


@dataclass(frozen=True, slots=True)
class MonsterSuperRaceId(_SemanticIntId):
    pass
