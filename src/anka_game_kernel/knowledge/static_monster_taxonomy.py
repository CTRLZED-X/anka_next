from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from anka_game_kernel.domain.ids import MonsterRaceId, MonsterSuperRaceId
from anka_game_kernel.domain.monster_taxonomy import (
    MonsterRaceDefinition,
    MonsterSuperRaceDefinition,
)
from anka_game_kernel.domain.provenance import Provenance, SourceKind, VerificationStatus


class _TaxonomySource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: int
    nameId: int
    name: str


@dataclass(frozen=True, slots=True)
class StaticMonsterTaxonomyLoad:
    super_races: tuple[MonsterSuperRaceDefinition, ...]
    races: tuple[MonsterRaceDefinition, ...]


def _load(path: Path) -> tuple[dict[str, object], str]:
    if not path.is_file():
        raise ValueError(f"missing static source file: {path}")
    raw_bytes = path.read_bytes()
    raw = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} must contain a JSON object keyed by id")
    return raw, hashlib.sha256(raw_bytes).hexdigest()


def _provenance(*, file: str, record_id: int, source_hash: str, source_version: str, game_version: str | None) -> Provenance:
    return Provenance(
        source_kind=SourceKind.USER_SUPPLIED_STATIC,
        source_name="Static",
        source_version=source_version,
        source_file=file,
        source_record_id=str(record_id),
        game_version=game_version,
        verification_status=VerificationStatus.SOURCE_VALIDATED,
        source_hash=source_hash,
        importer_version="static-monster-taxonomy-v1",
        normalizer_version="static-monster-taxonomy-v1",
    )


def load_static_monster_taxonomy(
    directory: str | Path,
    *,
    source_version: str,
    game_version: str | None = None,
) -> StaticMonsterTaxonomyLoad:
    directory = Path(directory)
    super_raw, super_hash = _load(directory / "MonsterSuperRaces.json")
    race_raw, race_hash = _load(directory / "MonsterRaces.json")

    super_defs: list[MonsterSuperRaceDefinition] = []
    for raw_key in sorted(super_raw, key=int):
        key = int(raw_key)
        source = _TaxonomySource.model_validate(super_raw[raw_key])
        if key != source.id:
            raise ValueError(f"MonsterSuperRaces.json key {key} does not match record id {source.id}")
        super_defs.append(
            MonsterSuperRaceDefinition(
                super_race_id=MonsterSuperRaceId(source.id),
                name_id=source.nameId,
                name=source.name,
                provenance=_provenance(
                    file="MonsterSuperRaces.json",
                    record_id=source.id,
                    source_hash=super_hash,
                    source_version=source_version,
                    game_version=game_version,
                ),
            )
        )

    race_defs: list[MonsterRaceDefinition] = []
    for raw_key in sorted(race_raw, key=int):
        key = int(raw_key)
        source = _TaxonomySource.model_validate(race_raw[raw_key])
        if key != source.id:
            raise ValueError(f"MonsterRaces.json key {key} does not match record id {source.id}")
        race_defs.append(
            MonsterRaceDefinition(
                race_id=MonsterRaceId(source.id),
                name_id=source.nameId,
                name=source.name,
                provenance=_provenance(
                    file="MonsterRaces.json",
                    record_id=source.id,
                    source_hash=race_hash,
                    source_version=source_version,
                    game_version=game_version,
                ),
            )
        )

    return StaticMonsterTaxonomyLoad(tuple(super_defs), tuple(race_defs))
