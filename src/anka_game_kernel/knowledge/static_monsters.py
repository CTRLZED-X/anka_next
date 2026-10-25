from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from anka_game_kernel.domain.ids import MonsterId
from anka_game_kernel.domain.monsters import MonsterDefinition, MonsterGradeDefinition
from anka_game_kernel.domain.provenance import Provenance, SourceKind, VerificationStatus


class MonsterGradeSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    grade: int
    level: int


class MonsterSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: int
    nameId: int
    grades: tuple[MonsterGradeSource, ...]
    name: str


def load_static_monsters(
    directory: str | Path,
    *,
    source_version: str,
    game_version: str | None = None,
) -> tuple[MonsterDefinition, ...]:
    path = Path(directory) / "Monsters.json"
    if not path.is_file():
        raise ValueError(f"missing static source file: {path}")
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Monsters.json must contain a JSON object keyed by id")

    definitions: list[MonsterDefinition] = []
    for raw_key in sorted(raw, key=int):
        key = int(raw_key)
        source = MonsterSource.model_validate(raw[raw_key])
        if key != source.id:
            raise ValueError(f"Monsters.json key {key} does not match record id {source.id}")
        definitions.append(
            MonsterDefinition(
                monster_id=MonsterId(source.id),
                name_id=source.nameId,
                name=source.name,
                grades=tuple(
                    MonsterGradeDefinition(grade=item.grade, level=item.level)
                    for item in source.grades
                ),
                provenance=Provenance(
                    source_kind=SourceKind.USER_SUPPLIED_STATIC,
                    source_name="Static",
                    source_version=source_version,
                    source_file="Monsters.json",
                    source_record_id=str(source.id),
                    game_version=game_version,
                    verification_status=VerificationStatus.SOURCE_VALIDATED,
                    source_hash=source_hash,
                    importer_version="static-monsters-v1",
                    normalizer_version="static-monsters-v1",
                ),
            )
        )
    return tuple(definitions)
