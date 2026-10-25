from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.ids import AreaId, SubAreaId, SuperAreaId, WorldMapId
from anka_game_kernel.domain.provenance import Provenance


@dataclass(frozen=True, slots=True)
class SuperAreaDefinition:
    super_area_id: SuperAreaId
    name_id: int
    world_map_id: WorldMapId
    name: str
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.name_id < 0:
            raise ValueError("super-area name_id cannot be negative")
        if not self.name.strip():
            raise ValueError("super-area name must not be empty")


@dataclass(frozen=True, slots=True)
class AreaDefinition:
    area_id: AreaId
    name_id: int
    super_area_id: SuperAreaId
    name: str
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.name_id < 0:
            raise ValueError("area name_id cannot be negative")
        if not self.name.strip():
            raise ValueError("area name must not be empty")


@dataclass(frozen=True, slots=True)
class SubAreaDefinition:
    sub_area_id: SubAreaId
    name_id: int
    area_id: AreaId
    name: str
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.name_id < 0:
            raise ValueError("sub-area name_id cannot be negative")
        if not self.name.strip():
            raise ValueError("sub-area name must not be empty")
