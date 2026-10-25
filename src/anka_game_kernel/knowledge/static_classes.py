from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from anka_game_kernel.domain.classes import (
    CharacteristicPointCostTier,
    ClassCharacteristicCosts,
    ClassDefinition,
)
from anka_game_kernel.domain.ids import ClassId
from anka_game_kernel.domain.provenance import Provenance, SourceKind, VerificationStatus


class BreedSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: int
    shortNameId: int
    statsPointsForStrength: tuple[tuple[int, int], ...]
    statsPointsForIntelligence: tuple[tuple[int, int], ...]
    statsPointsForChance: tuple[tuple[int, int], ...]
    statsPointsForAgility: tuple[tuple[int, int], ...]
    statsPointsForVitality: tuple[tuple[int, int], ...]
    statsPointsForWisdom: tuple[tuple[int, int], ...]
    name: str


def _curve(raw: tuple[tuple[int, int], ...]) -> tuple[CharacteristicPointCostTier, ...]:
    return tuple(CharacteristicPointCostTier(start, cost) for start, cost in raw)


def load_static_classes(
    directory: str | Path,
    *,
    source_version: str,
    game_version: str | None = None,
) -> tuple[ClassDefinition, ...]:
    path = Path(directory) / "Breeds.json"
    if not path.is_file():
        raise ValueError(f"missing static source file: {path}")
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Breeds.json must contain a JSON object keyed by id")

    definitions: list[ClassDefinition] = []
    for raw_key in sorted(raw, key=int):
        key = int(raw_key)
        source = BreedSource.model_validate(raw[raw_key])
        if key != source.id:
            raise ValueError(f"Breeds.json key {key} does not match record id {source.id}")
        definitions.append(
            ClassDefinition(
                class_id=ClassId(source.id),
                short_name_id=source.shortNameId,
                name=source.name,
                costs=ClassCharacteristicCosts(
                    strength=_curve(source.statsPointsForStrength),
                    intelligence=_curve(source.statsPointsForIntelligence),
                    chance=_curve(source.statsPointsForChance),
                    agility=_curve(source.statsPointsForAgility),
                    vitality=_curve(source.statsPointsForVitality),
                    wisdom=_curve(source.statsPointsForWisdom),
                ),
                provenance=Provenance(
                    source_kind=SourceKind.USER_SUPPLIED_STATIC,
                    source_name="Static",
                    source_version=source_version,
                    source_file="Breeds.json",
                    source_record_id=str(source.id),
                    game_version=game_version,
                    verification_status=VerificationStatus.SOURCE_VALIDATED,
                    source_hash=source_hash,
                    importer_version="static-classes-v1",
                    normalizer_version="static-classes-v1",
                ),
            )
        )
    return tuple(definitions)
