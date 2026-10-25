from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.ids import CellId, MapId
from anka_game_kernel.domain.provenance import Provenance


@dataclass(frozen=True, slots=True)
class MapNeighbors:
    top: MapId | None
    right: MapId | None
    left: MapId | None
    bottom: MapId | None


@dataclass(frozen=True, slots=True)
class MapCellDefinition:
    cell_id: CellId
    floor: int
    walkable: bool
    blocks_line_of_sight: bool
    non_walkable_during_fight: bool
    map_change_data: int
    move_zone: int
    speed: int
    linked_zone_roleplay: int
    farm_cell: bool
    havenbag_cell: bool


@dataclass(frozen=True, slots=True)
class MapDefinition:
    map_id: MapId
    neighbors: MapNeighbors
    cells: tuple[MapCellDefinition, ...]
    uses_new_movement_system: bool
    provenance: Provenance
