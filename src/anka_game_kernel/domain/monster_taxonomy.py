from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.ids import MonsterRaceId, MonsterSuperRaceId
from anka_game_kernel.domain.provenance import Provenance


@dataclass(frozen=True, slots=True)
class MonsterSuperRaceDefinition:
    super_race_id: MonsterSuperRaceId
    name_id: int
    name: str
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.name_id < 0:
            raise ValueError("monster super-race name_id cannot be negative")
        if not self.name.strip():
            raise ValueError("monster super-race name must not be empty")


@dataclass(frozen=True, slots=True)
class MonsterRaceDefinition:
    race_id: MonsterRaceId
    name_id: int
    name: str
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.name_id < 0:
            raise ValueError("monster race name_id cannot be negative")
        if not self.name.strip():
            raise ValueError("monster race name must not be empty")
