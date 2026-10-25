from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from anka_game_kernel.domain.ids import SpellId, SpellLevelId
from anka_game_kernel.domain.provenance import Provenance, SourceKind, VerificationStatus
from anka_game_kernel.domain.spells import SpellDefinition, SpellGradeDefinition
from anka_game_kernel.normalization.state_criteria import parse_states_criterion


class _StaticSourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SpellSource(_StaticSourceModel):
    id: int
    nameId: int
    descriptionId: int
    spellLevels: tuple[int, ...]
    name: str


class SpellLevelSource(_StaticSourceModel):
    id: int
    spellId: int
    grade: int
    apCost: int
    minRange: int
    range: int
    maxCastPerTurn: int
    maxCastPerTarget: int
    minCastInterval: int
    initialCooldown: int
    minPlayerLevel: int
    statesCriterion: str
    castInLine: bool
    castInDiagonal: bool
    castTestLos: bool
    needFreeCell: bool
    needTakenCell: bool
    rangeCanBeBoosted: bool
    canSummon: bool


@dataclass(frozen=True, slots=True, order=True)
class StaticSpellFieldAnomaly:
    level_id: SpellLevelId
    field_name: str
    raw_value: int


@dataclass(frozen=True, slots=True)
class StaticSpellLoadResult:
    spells: tuple[SpellDefinition, ...]
    orphan_level_ids: tuple[SpellLevelId, ...]
    range_anomaly_level_ids: tuple[SpellLevelId, ...]
    field_anomalies: tuple[StaticSpellFieldAnomaly, ...] = ()


def _load_dictionary(path: Path, model_type: type[_StaticSourceModel]) -> dict[int, _StaticSourceModel]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} must contain a JSON object keyed by id")
    result: dict[int, _StaticSourceModel] = {}
    for raw_key, raw_record in raw.items():
        try:
            key = int(raw_key)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path.name} contains non-integer key {raw_key!r}") from exc
        record = model_type.model_validate(raw_record)
        if key != record.id:
            raise ValueError(
                f"{path.name} key {key} does not match record id {record.id}"
            )
        result[key] = record
    return result


def _provenance(
    *,
    source_version: str,
    game_version: str | None,
    source_file: str,
    source_record_id: int,
    source_hash: str,
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
        importer_version="static-spells-v1",
        normalizer_version="static-spells-v1",
    )


def load_static_spells(
    directory: str | Path,
    *,
    source_version: str,
    game_version: str | None = None,
) -> StaticSpellLoadResult:
    root = Path(directory)
    spells_path = root / "Spells.json"
    levels_path = root / "SpellLevels.json"
    if not spells_path.is_file():
        raise ValueError(f"missing static source file: {spells_path}")
    if not levels_path.is_file():
        raise ValueError(f"missing static source file: {levels_path}")

    spell_bytes = spells_path.read_bytes()
    level_bytes = levels_path.read_bytes()
    spell_hash = hashlib.sha256(spell_bytes).hexdigest()
    level_hash = hashlib.sha256(level_bytes).hexdigest()

    spell_sources = _load_dictionary(spells_path, SpellSource)
    level_sources = _load_dictionary(levels_path, SpellLevelSource)

    referenced_level_ids: set[int] = set()
    definitions: list[SpellDefinition] = []
    for raw_spell_id in sorted(spell_sources):
        source = spell_sources[raw_spell_id]
        assert isinstance(source, SpellSource)
        grades: list[SpellGradeDefinition] = []
        seen_grade_numbers: set[int] = set()
        for raw_level_id in source.spellLevels:
            level = level_sources.get(raw_level_id)
            if level is None:
                raise ValueError(
                    f"spell {source.id} references missing SpellLevel {raw_level_id}"
                )
            assert isinstance(level, SpellLevelSource)
            if level.spellId != source.id:
                raise ValueError(
                    f"SpellLevel {level.id} belongs to spell {level.spellId}, expected {source.id}"
                )
            if level.grade in seen_grade_numbers:
                raise ValueError(
                    f"spell {source.id} contains duplicate grade number {level.grade}"
                )
            seen_grade_numbers.add(level.grade)
            referenced_level_ids.add(level.id)
            grades.append(
                SpellGradeDefinition(
                    level_id=SpellLevelId(level.id),
                    spell_id=SpellId(level.spellId),
                    grade=level.grade,
                    ap_cost=level.apCost,
                    min_range=level.minRange,
                    max_range=level.range,
                    max_cast_per_turn=level.maxCastPerTurn,
                    max_cast_per_target=level.maxCastPerTarget,
                    min_cast_interval=level.minCastInterval,
                    initial_cooldown=level.initialCooldown,
                    min_player_level=level.minPlayerLevel,
                    state_criterion=parse_states_criterion(level.statesCriterion),
                    cast_in_line=level.castInLine,
                    cast_in_diagonal=level.castInDiagonal,
                    requires_line_of_sight=level.castTestLos,
                    need_free_cell=level.needFreeCell,
                    need_taken_cell=level.needTakenCell,
                    range_modifiable=level.rangeCanBeBoosted,
                    can_summon=level.canSummon,
                    provenance=_provenance(
                        source_version=source_version,
                        game_version=game_version,
                        source_file="SpellLevels.json",
                        source_record_id=level.id,
                        source_hash=level_hash,
                    ),
                )
            )

        definitions.append(
            SpellDefinition(
                spell_id=SpellId(source.id),
                name_id=source.nameId,
                description_id=source.descriptionId,
                name=source.name,
                grades=tuple(grades),
                provenance=_provenance(
                    source_version=source_version,
                    game_version=game_version,
                    source_file="Spells.json",
                    source_record_id=source.id,
                    source_hash=spell_hash,
                ),
            )
        )

    orphan_level_ids = tuple(
        SpellLevelId(raw_id)
        for raw_id in sorted(set(level_sources) - referenced_level_ids)
    )
    range_anomaly_level_ids = tuple(
        SpellLevelId(raw_id)
        for raw_id, level in sorted(level_sources.items())
        if isinstance(level, SpellLevelSource) and level.range < level.minRange
    )
    field_anomalies = tuple(
        sorted(
            (
                StaticSpellFieldAnomaly(SpellLevelId(raw_id), field_name, raw_value)
                for raw_id, level in level_sources.items()
                if isinstance(level, SpellLevelSource)
                for field_name, raw_value in (
                    ("maxCastPerTurn", level.maxCastPerTurn),
                    ("initialCooldown", level.initialCooldown),
                )
                if raw_value < 0
            ),
            key=lambda item: (int(item.level_id), item.field_name),
        )
    )
    return StaticSpellLoadResult(
        spells=tuple(definitions),
        orphan_level_ids=orphan_level_ids,
        range_anomaly_level_ids=range_anomaly_level_ids,
        field_anomalies=field_anomalies,
    )
