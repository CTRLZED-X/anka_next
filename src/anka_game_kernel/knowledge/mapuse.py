from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from anka_game_kernel.domain.ids import CellId, MapId
from anka_game_kernel.domain.maps import MapCellDefinition, MapDefinition, MapNeighbors
from anka_game_kernel.domain.provenance import Provenance


class _MapuseSourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class MapuseCellSource(_MapuseSourceModel):
    linked_zone_roleplay: int = Field(alias="_linkedZoneRP")
    floor: int = Field(alias="Floor")
    map_change_data: int = Field(alias="MapChangeData")
    move_zone: int = Field(alias="MoveZone")
    speed: int = Field(alias="Speed")
    walkable: bool
    farm_cell: bool = Field(alias="_farmcell")
    allows_line_of_sight: bool = Field(alias="Los")
    non_walkable_during_fight: bool = Field(alias="NonWalkableDuringFight")
    havenbag_cell: bool = Field(alias="HavenbagCell")


class MapuseElementSource(_MapuseSourceModel):
    identifier: int = Field(alias="Identifier")


class MapuseLayerCellSource(_MapuseSourceModel):
    cell_id: int = Field(alias="CellId")
    elements: tuple[MapuseElementSource, ...] = Field(alias="Elements")


class MapuseLayerSource(_MapuseSourceModel):
    cells: tuple[MapuseLayerCellSource, ...] = Field(alias="Cells")


class MapuseMapSource(_MapuseSourceModel):
    map_id: int = Field(alias="Id")
    top_neighbour_id: int = Field(alias="TopNeighbourId")
    right_neighbour_id: int = Field(alias="RightNeighbourId")
    left_neighbour_id: int = Field(alias="LeftNeighbourId")
    bottom_neighbour_id: int = Field(alias="BottomNeighbourId")
    cells_count: int = Field(alias="CellsCount")
    uses_new_movement_system: bool = Field(alias="IsUsingNewMovementSystem")
    cells: tuple[MapuseCellSource, ...] = Field(alias="Cells")
    layers: tuple[MapuseLayerSource, ...] = Field(alias="Layers")
    cell_monster: tuple[Any, ...] = Field(alias="cellmonster")
    walkable_backup: tuple[bool, ...] = Field(alias="walkableBackup")

    @model_validator(mode="after")
    def validate_internal_consistency(self) -> "MapuseMapSource":
        if self.cells_count != len(self.cells):
            raise ValueError(
                f"CellsCount={self.cells_count} does not match Cells length={len(self.cells)}"
            )
        if len(self.walkable_backup) != len(self.cells):
            raise ValueError(
                "walkableBackup length does not match Cells length"
            )
        source_walkable = tuple(cell.walkable for cell in self.cells)
        if self.walkable_backup != source_walkable:
            raise ValueError("walkableBackup does not match Cells.walkable")
        for layer in self.layers:
            for cell in layer.cells:
                if cell.cell_id < 0 or cell.cell_id >= self.cells_count:
                    raise ValueError(
                        f"Layer CellId={cell.cell_id} is outside map cell range"
                    )
        return self


def _optional_map_id(value: int) -> MapId | None:
    return None if value <= 0 else MapId(value)


def normalize_mapuse_map(
    source: MapuseMapSource,
    provenance: Provenance,
) -> MapDefinition:
    cells = tuple(
        MapCellDefinition(
            cell_id=CellId(cell_id),
            floor=cell.floor,
            walkable=cell.walkable,
            blocks_line_of_sight=not cell.allows_line_of_sight,
            non_walkable_during_fight=cell.non_walkable_during_fight,
            map_change_data=cell.map_change_data,
            move_zone=cell.move_zone,
            speed=cell.speed,
            linked_zone_roleplay=cell.linked_zone_roleplay,
            farm_cell=cell.farm_cell,
            havenbag_cell=cell.havenbag_cell,
        )
        for cell_id, cell in enumerate(source.cells)
    )
    return MapDefinition(
        map_id=MapId(source.map_id),
        neighbors=MapNeighbors(
            top=_optional_map_id(source.top_neighbour_id),
            right=_optional_map_id(source.right_neighbour_id),
            left=_optional_map_id(source.left_neighbour_id),
            bottom=_optional_map_id(source.bottom_neighbour_id),
        ),
        cells=cells,
        uses_new_movement_system=source.uses_new_movement_system,
        provenance=provenance,
    )


def load_mapuse_directory(
    directory: str | "Path",
    *,
    source_version: str,
    game_version: str | None = None,
) -> tuple[MapDefinition, ...]:
    import hashlib
    import json
    from pathlib import Path

    from anka_game_kernel.domain.provenance import SourceKind, VerificationStatus

    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"Mapuse directory does not exist: {root}")

    normalized: list[MapDefinition] = []
    seen_ids: set[int] = set()
    for path in sorted(root.glob("map_*.json")):
        raw_bytes = path.read_bytes()
        data = json.loads(raw_bytes.decode("utf-8"))
        source = MapuseMapSource.model_validate(data)
        if source.map_id in seen_ids:
            raise ValueError(f"duplicate map id {source.map_id} in Mapuse directory")
        seen_ids.add(source.map_id)

        provenance = Provenance(
            source_kind=SourceKind.USER_SUPPLIED_STATIC,
            source_name="Mapuse",
            source_version=source_version,
            source_file=path.name,
            source_record_id=str(source.map_id),
            game_version=game_version,
            verification_status=VerificationStatus.SOURCE_VALIDATED,
            source_hash=hashlib.sha256(raw_bytes).hexdigest(),
            importer_version="mapuse-v1",
            normalizer_version="mapuse-v1",
        )
        normalized.append(normalize_mapuse_map(source, provenance))

    normalized.sort(key=lambda item: int(item.map_id))
    return tuple(normalized)
