from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from anka_game_kernel.domain.ids import AreaId, SubAreaId, SuperAreaId, WorldMapId
from anka_game_kernel.domain.provenance import Provenance, SourceKind, VerificationStatus
from anka_game_kernel.domain.world import AreaDefinition, SubAreaDefinition, SuperAreaDefinition


class _Source(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SuperAreaSource(_Source):
    id: int
    nameId: int
    worldmapId: int
    name: str


class AreaSource(_Source):
    id: int
    nameId: int
    superAreaId: int
    name: str


class SubAreaSource(_Source):
    id: int
    nameId: int
    areaId: int
    name: str


@dataclass(frozen=True, slots=True)
class StaticWorldLoadResult:
    super_areas: tuple[SuperAreaDefinition, ...]
    areas: tuple[AreaDefinition, ...]
    sub_areas: tuple[SubAreaDefinition, ...]


def _load(path: Path, model_type: type[_Source]) -> dict[int, _Source]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} must contain a JSON object keyed by id")
    result: dict[int, _Source] = {}
    for raw_key, raw_record in raw.items():
        key = int(raw_key)
        source = model_type.model_validate(raw_record)
        if source.id != key:
            raise ValueError(f"{path.name} key {key} does not match record id {source.id}")
        result[key] = source
    return result


def _prov(source_version: str, game_version: str | None, filename: str, record_id: int, digest: str) -> Provenance:
    return Provenance(
        source_kind=SourceKind.USER_SUPPLIED_STATIC,
        source_name="Static",
        source_version=source_version,
        source_file=filename,
        source_record_id=str(record_id),
        game_version=game_version,
        verification_status=VerificationStatus.SOURCE_VALIDATED,
        source_hash=digest,
        importer_version="static-world-v1",
        normalizer_version="static-world-v1",
    )


def load_static_world(
    directory: str | Path,
    *,
    source_version: str,
    game_version: str | None = None,
) -> StaticWorldLoadResult:
    root = Path(directory)
    paths = {name: root / name for name in ("SuperAreas.json", "Areas.json", "SubAreas.json")}
    for path in paths.values():
        if not path.is_file():
            raise ValueError(f"missing static source file: {path}")
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
    super_sources = _load(paths["SuperAreas.json"], SuperAreaSource)
    area_sources = _load(paths["Areas.json"], AreaSource)
    sub_sources = _load(paths["SubAreas.json"], SubAreaSource)

    for source in area_sources.values():
        assert isinstance(source, AreaSource)
        if source.superAreaId not in super_sources:
            raise ValueError(f"area {source.id} references unknown super area {source.superAreaId}")
    for source in sub_sources.values():
        assert isinstance(source, SubAreaSource)
        if source.areaId not in area_sources:
            raise ValueError(f"sub-area {source.id} references unknown area {source.areaId}")

    super_areas = tuple(
        SuperAreaDefinition(
            super_area_id=SuperAreaId(source.id),
            name_id=source.nameId,
            world_map_id=WorldMapId(source.worldmapId),
            name=source.name,
            provenance=_prov(source_version, game_version, "SuperAreas.json", source.id, hashes["SuperAreas.json"]),
        )
        for key in sorted(super_sources)
        for source in (super_sources[key],)
        if isinstance(source, SuperAreaSource)
    )
    areas = tuple(
        AreaDefinition(
            area_id=AreaId(source.id),
            name_id=source.nameId,
            super_area_id=SuperAreaId(source.superAreaId),
            name=source.name,
            provenance=_prov(source_version, game_version, "Areas.json", source.id, hashes["Areas.json"]),
        )
        for key in sorted(area_sources)
        for source in (area_sources[key],)
        if isinstance(source, AreaSource)
    )
    sub_areas = tuple(
        SubAreaDefinition(
            sub_area_id=SubAreaId(source.id),
            name_id=source.nameId,
            area_id=AreaId(source.areaId),
            name=source.name,
            provenance=_prov(source_version, game_version, "SubAreas.json", source.id, hashes["SubAreas.json"]),
        )
        for key in sorted(sub_sources)
        for source in (sub_sources[key],)
        if isinstance(source, SubAreaSource)
    )
    return StaticWorldLoadResult(super_areas=super_areas, areas=areas, sub_areas=sub_areas)
