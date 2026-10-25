from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from anka_game_kernel.domain.companions import (
    CompanionDefinition,
    CompanionSpellDefinition,
    CompanionSpellGradeThreshold,
)
from anka_game_kernel.domain.ids import CompanionId, CompanionSpellId, SpellId
from anka_game_kernel.domain.provenance import Provenance, SourceKind, VerificationStatus


class CompanionSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: int
    nameId: int
    spells: tuple[int, ...]
    name: str


class CompanionSpellSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: int
    spellId: int
    companionId: int
    gradeByLevel: str


@dataclass(frozen=True, slots=True)
class StaticCompanionLoad:
    companions: tuple[CompanionDefinition, ...]
    spells: tuple[CompanionSpellDefinition, ...]


def _read_object(path: Path) -> tuple[dict[str, object], str]:
    if not path.is_file():
        raise ValueError(f"missing static source file: {path}")
    raw_bytes = path.read_bytes()
    source_hash = hashlib.sha256(raw_bytes).hexdigest()
    raw = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} must contain a JSON object keyed by id")
    return raw, source_hash


def _provenance(
    *,
    source_file: str,
    source_record_id: int,
    source_hash: str,
    source_version: str,
    game_version: str | None,
) -> Provenance:
    return Provenance(
        source_kind=SourceKind.USER_SUPPLIED_STATIC,
        source_name="Static",
        source_version=source_version,
        source_file=source_file,
        source_record_id=str(source_record_id),
        game_version=game_version,
        verification_status=VerificationStatus.SOURCE_VALIDATED,
        source_hash=source_hash,
        importer_version="static-companions-v1",
        normalizer_version="static-companions-v1",
    )


def _parse_grade_by_level(raw: str, *, companion_spell_id: int) -> tuple[CompanionSpellGradeThreshold, ...]:
    try:
        pairs = tuple(
            CompanionSpellGradeThreshold(
                grade=int(chunk.split(",")[0]),
                minimum_level=int(chunk.split(",")[1]),
            )
            for chunk in raw.split(";")
            if chunk
        )
    except (ValueError, IndexError) as exc:
        raise ValueError(
            f"CompanionSpells.json record {companion_spell_id} has invalid gradeByLevel"
        ) from exc
    if not pairs:
        raise ValueError(
            f"CompanionSpells.json record {companion_spell_id} has empty gradeByLevel"
        )
    # The domain object performs ordering/uniqueness checks.
    return pairs


def load_static_companions(
    directory: str | Path,
    *,
    source_version: str,
    known_spell_ids: frozenset[SpellId],
    game_version: str | None = None,
) -> StaticCompanionLoad:
    directory = Path(directory)
    companion_raw, companion_hash = _read_object(directory / "Companions.json")
    spell_raw, spell_hash = _read_object(directory / "CompanionSpells.json")

    companion_sources: dict[CompanionId, CompanionSource] = {}
    for raw_key in sorted(companion_raw, key=int):
        key = int(raw_key)
        source = CompanionSource.model_validate(companion_raw[raw_key])
        if key != source.id:
            raise ValueError(
                f"Companions.json key {key} does not match record id {source.id}"
            )
        companion_sources[CompanionId(source.id)] = source

    links_by_companion: dict[CompanionId, list[CompanionSpellId]] = defaultdict(list)
    spell_definitions: list[CompanionSpellDefinition] = []
    for raw_key in sorted(spell_raw, key=int):
        key = int(raw_key)
        source = CompanionSpellSource.model_validate(spell_raw[raw_key])
        if key != source.id:
            raise ValueError(
                f"CompanionSpells.json key {key} does not match record id {source.id}"
            )
        companion_id = CompanionId(source.companionId)
        if companion_id not in companion_sources:
            raise ValueError(
                f"CompanionSpells.json record {source.id} references unknown companion {source.companionId}"
            )
        spell_id = SpellId(source.spellId)
        if spell_id not in known_spell_ids:
            raise ValueError(
                f"CompanionSpells.json record {source.id} references unknown spell {source.spellId}"
            )
        companion_spell_id = CompanionSpellId(source.id)
        links_by_companion[companion_id].append(companion_spell_id)
        spell_definitions.append(
            CompanionSpellDefinition(
                companion_spell_id=companion_spell_id,
                companion_id=companion_id,
                spell_id=spell_id,
                grade_by_level=_parse_grade_by_level(
                    source.gradeByLevel,
                    companion_spell_id=source.id,
                ),
                provenance=_provenance(
                    source_file="CompanionSpells.json",
                    source_record_id=source.id,
                    source_hash=spell_hash,
                    source_version=source_version,
                    game_version=game_version,
                ),
            )
        )

    companions: list[CompanionDefinition] = []
    for companion_id, source in sorted(companion_sources.items(), key=lambda item: int(item[0])):
        listed = tuple(CompanionSpellId(raw_id) for raw_id in source.spells)
        actual = tuple(sorted(links_by_companion.get(companion_id, ()), key=int))
        if tuple(sorted(listed, key=int)) != actual:
            raise ValueError(
                f"Companion {int(companion_id)} spell-link list does not match CompanionSpells.json"
            )
        companions.append(
            CompanionDefinition(
                companion_id=companion_id,
                name_id=source.nameId,
                name=source.name,
                companion_spell_ids=listed,
                provenance=_provenance(
                    source_file="Companions.json",
                    source_record_id=source.id,
                    source_hash=companion_hash,
                    source_version=source_version,
                    game_version=game_version,
                ),
            )
        )

    return StaticCompanionLoad(
        companions=tuple(companions),
        spells=tuple(spell_definitions),
    )
