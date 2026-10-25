from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from anka_game_kernel.domain.effects import EffectDefinition
from anka_game_kernel.domain.ids import EffectId, SpellId, SpellVariantId, StateId
from anka_game_kernel.domain.provenance import Provenance, SourceKind, VerificationStatus
from anka_game_kernel.domain.spell_variants import SpellVariantDefinition
from anka_game_kernel.domain.states import StateDefinition


class _StaticSourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StateSource(_StaticSourceModel):
    id: int
    nameId: int
    name: str


class EffectSource(_StaticSourceModel):
    id: int
    descriptionId: int
    effectPowerRate: float
    name: str


class SpellVariantSource(_StaticSourceModel):
    id: int
    spellIds: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class StaticCatalogLoadResult:
    states: tuple[StateDefinition, ...]
    effects: tuple[EffectDefinition, ...]
    spell_variants: tuple[SpellVariantDefinition, ...]


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
            raise ValueError(f"{path.name} key {key} does not match record id {record.id}")
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
        importer_version="static-catalog-v1",
        normalizer_version="static-catalog-v1",
    )


def load_static_catalog(
    directory: str | Path,
    *,
    source_version: str,
    known_spell_ids: frozenset[SpellId],
    game_version: str | None = None,
) -> StaticCatalogLoadResult:
    root = Path(directory)
    states_path = root / "SpellStates.json"
    effects_path = root / "Effects.json"
    variants_path = root / "SpellVariants.json"
    for path in (states_path, effects_path, variants_path):
        if not path.is_file():
            raise ValueError(f"missing static source file: {path}")

    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (states_path, effects_path, variants_path)
    }
    state_sources = _load_dictionary(states_path, StateSource)
    effect_sources = _load_dictionary(effects_path, EffectSource)
    variant_sources = _load_dictionary(variants_path, SpellVariantSource)

    states = tuple(
        StateDefinition(
            state_id=StateId(source.id),
            name_id=source.nameId,
            name=source.name,
            provenance=_provenance(
                source_version=source_version,
                game_version=game_version,
                source_file="SpellStates.json",
                source_record_id=source.id,
                source_hash=hashes["SpellStates.json"],
            ),
        )
        for raw_id in sorted(state_sources)
        for source in (state_sources[raw_id],)
        if isinstance(source, StateSource)
    )

    effects = tuple(
        EffectDefinition(
            effect_id=EffectId(source.id),
            description_id=source.descriptionId,
            effect_power_rate=source.effectPowerRate,
            name=source.name,
            provenance=_provenance(
                source_version=source_version,
                game_version=game_version,
                source_file="Effects.json",
                source_record_id=source.id,
                source_hash=hashes["Effects.json"],
            ),
        )
        for raw_id in sorted(effect_sources)
        for source in (effect_sources[raw_id],)
        if isinstance(source, EffectSource)
    )

    known_raw_spell_ids = {int(spell_id) for spell_id in known_spell_ids}
    seen_spell_membership: dict[int, int] = {}
    variants: list[SpellVariantDefinition] = []
    for raw_id in sorted(variant_sources):
        source = variant_sources[raw_id]
        assert isinstance(source, SpellVariantSource)
        for raw_spell_id in source.spellIds:
            if raw_spell_id not in known_raw_spell_ids:
                raise ValueError(
                    f"spell variant {source.id} references unknown spell {raw_spell_id}"
                )
            previous = seen_spell_membership.get(raw_spell_id)
            if previous is not None:
                raise ValueError(
                    f"spell {raw_spell_id} appears in multiple variant groups "
                    f"{previous} and {source.id}"
                )
            seen_spell_membership[raw_spell_id] = source.id
        variants.append(
            SpellVariantDefinition(
                variant_id=SpellVariantId(source.id),
                spell_ids=tuple(SpellId(value) for value in source.spellIds),
                provenance=_provenance(
                    source_version=source_version,
                    game_version=game_version,
                    source_file="SpellVariants.json",
                    source_record_id=source.id,
                    source_hash=hashes["SpellVariants.json"],
                ),
            )
        )

    return StaticCatalogLoadResult(
        states=states,
        effects=effects,
        spell_variants=tuple(variants),
    )
