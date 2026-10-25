from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path

from anka_game_kernel.domain.ids import (
    AreaId,
    ClassId,
    CompanionId,
    CompanionSpellId,
    EffectId,
    MapId,
    MonsterId,
    MonsterRaceId,
    MonsterSuperRaceId,
    SpellId,
    SpellLevelId,
    SpellVariantId,
    StateId,
    SubAreaId,
    SuperAreaId,
)
from anka_game_kernel.domain.classes import ClassDefinition
from anka_game_kernel.domain.companions import CompanionDefinition, CompanionSpellDefinition
from anka_game_kernel.domain.effects import EffectDefinition
from anka_game_kernel.domain.maps import MapDefinition
from anka_game_kernel.domain.map_locations import MapLocationDefinition
from anka_game_kernel.domain.monsters import MonsterDefinition
from anka_game_kernel.domain.monster_taxonomy import MonsterRaceDefinition, MonsterSuperRaceDefinition
from anka_game_kernel.domain.provenance import Provenance
from anka_game_kernel.domain.spell_variants import SpellVariantDefinition
from anka_game_kernel.domain.spells import SpellDefinition
from anka_game_kernel.domain.states import StateDefinition
from anka_game_kernel.domain.world import AreaDefinition, SubAreaDefinition, SuperAreaDefinition
from anka_game_kernel.knowledge.mapuse import load_mapuse_directory
from anka_game_kernel.knowledge.static_catalog import load_static_catalog
from anka_game_kernel.knowledge.static_classes import load_static_classes
from anka_game_kernel.knowledge.static_companions import load_static_companions
from anka_game_kernel.knowledge.static_monsters import load_static_monsters
from anka_game_kernel.knowledge.static_monster_taxonomy import load_static_monster_taxonomy
from anka_game_kernel.knowledge.static_map_locations import load_active_map_locations
from anka_game_kernel.knowledge.static_world import load_static_world
from anka_game_kernel.knowledge.static_spells import (
    StaticSpellFieldAnomaly,
    load_static_spells,
)
from anka_game_kernel.registries.base import DefinitionRegistry

KNOWLEDGE_SCHEMA_VERSION = "1"


@dataclass(frozen=True, slots=True, order=True)
class SourceFingerprint:
    source_name: str
    source_version: str | None
    source_file: str | None
    source_record_id: str | None
    source_hash: str
    importer_version: str | None
    normalizer_version: str | None


@dataclass(frozen=True, slots=True)
class KnowledgePackManifest:
    schema_version: str
    pack_version: str
    game_version: str | None
    content_hash: str
    sources: tuple[SourceFingerprint, ...]


@dataclass(frozen=True, slots=True)
class SpellKnowledgeDiagnostics:
    orphan_level_ids: tuple[SpellLevelId, ...] = ()
    range_anomaly_level_ids: tuple[SpellLevelId, ...] = ()
    field_anomalies: tuple[StaticSpellFieldAnomaly, ...] = ()


@dataclass(frozen=True, slots=True)
class KnowledgePack:
    manifest: KnowledgePackManifest
    maps: DefinitionRegistry[MapId, MapDefinition]
    map_locations: DefinitionRegistry[MapId, MapLocationDefinition] = field(
        default_factory=lambda: DefinitionRegistry({})
    )
    spells: DefinitionRegistry[SpellId, SpellDefinition] = field(
        default_factory=lambda: DefinitionRegistry({})
    )
    classes: DefinitionRegistry[ClassId, ClassDefinition] = field(
        default_factory=lambda: DefinitionRegistry({})
    )
    companions: DefinitionRegistry[CompanionId, CompanionDefinition] = field(
        default_factory=lambda: DefinitionRegistry({})
    )
    companion_spells: DefinitionRegistry[CompanionSpellId, CompanionSpellDefinition] = field(
        default_factory=lambda: DefinitionRegistry({})
    )
    monsters: DefinitionRegistry[MonsterId, MonsterDefinition] = field(
        default_factory=lambda: DefinitionRegistry({})
    )
    monster_super_races: DefinitionRegistry[MonsterSuperRaceId, MonsterSuperRaceDefinition] = field(
        default_factory=lambda: DefinitionRegistry({})
    )
    monster_races: DefinitionRegistry[MonsterRaceId, MonsterRaceDefinition] = field(
        default_factory=lambda: DefinitionRegistry({})
    )
    super_areas: DefinitionRegistry[SuperAreaId, SuperAreaDefinition] = field(
        default_factory=lambda: DefinitionRegistry({})
    )
    areas: DefinitionRegistry[AreaId, AreaDefinition] = field(
        default_factory=lambda: DefinitionRegistry({})
    )
    sub_areas: DefinitionRegistry[SubAreaId, SubAreaDefinition] = field(
        default_factory=lambda: DefinitionRegistry({})
    )
    states: DefinitionRegistry[StateId, StateDefinition] = field(
        default_factory=lambda: DefinitionRegistry({})
    )
    effects: DefinitionRegistry[EffectId, EffectDefinition] = field(
        default_factory=lambda: DefinitionRegistry({})
    )
    spell_variants: DefinitionRegistry[SpellVariantId, SpellVariantDefinition] = field(
        default_factory=lambda: DefinitionRegistry({})
    )
    spell_diagnostics: SpellKnowledgeDiagnostics | None = None


def _fingerprint_from_provenance(provenance: Provenance) -> SourceFingerprint:
    if provenance.source_hash is None:
        raise ValueError(
            f"source {provenance.source_name}/{provenance.source_file} lacks a source hash"
        )
    # Knowledge-pack sources are file-level fingerprints. Record-level provenance
    # remains on every canonical definition, but is intentionally not duplicated
    # tens of thousands of times in the manifest.
    return SourceFingerprint(
        source_name=provenance.source_name,
        source_version=provenance.source_version,
        source_file=provenance.source_file,
        source_record_id=None,
        source_hash=provenance.source_hash,
        importer_version=provenance.importer_version,
        normalizer_version=provenance.normalizer_version,
    )


def _source_fingerprints(
    maps: tuple[MapDefinition, ...],
    spells: tuple[SpellDefinition, ...] = (),
) -> tuple[SourceFingerprint, ...]:
    fingerprints: set[SourceFingerprint] = set()
    for map_definition in maps:
        fingerprints.add(_fingerprint_from_provenance(map_definition.provenance))
    for spell_definition in spells:
        fingerprints.add(_fingerprint_from_provenance(spell_definition.provenance))
        for grade in spell_definition.grades:
            fingerprints.add(_fingerprint_from_provenance(grade.provenance))
    return tuple(sorted(fingerprints))


def _additional_source_fingerprints(*definitions: object) -> tuple[SourceFingerprint, ...]:
    fingerprints: set[SourceFingerprint] = set()
    for definition in definitions:
        provenance = getattr(definition, "provenance", None)
        if not isinstance(provenance, Provenance):
            raise TypeError("canonical definition lacks Provenance")
        fingerprints.add(_fingerprint_from_provenance(provenance))
    return tuple(sorted(fingerprints))


def _manifest_hash(
    *,
    pack_version: str,
    game_version: str | None,
    sources: tuple[SourceFingerprint, ...],
) -> str:
    payload = {
        "schema_version": KNOWLEDGE_SCHEMA_VERSION,
        "pack_version": pack_version,
        "game_version": game_version,
        "sources": [asdict(source) for source in sources],
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _manifest(
    *,
    pack_version: str,
    game_version: str | None,
    sources: tuple[SourceFingerprint, ...],
) -> KnowledgePackManifest:
    return KnowledgePackManifest(
        schema_version=KNOWLEDGE_SCHEMA_VERSION,
        pack_version=pack_version,
        game_version=game_version,
        content_hash=_manifest_hash(
            pack_version=pack_version,
            game_version=game_version,
            sources=sources,
        ),
        sources=sources,
    )


def build_mapuse_knowledge_pack(
    directory: str | Path,
    *,
    source_version: str,
    pack_version: str,
    game_version: str | None = None,
) -> KnowledgePack:
    maps = load_mapuse_directory(
        directory,
        source_version=source_version,
        game_version=game_version,
    )
    registry = DefinitionRegistry.from_items(maps, key=lambda item: item.map_id)
    sources = _source_fingerprints(maps)
    return KnowledgePack(
        manifest=_manifest(
            pack_version=pack_version,
            game_version=game_version,
            sources=sources,
        ),
        maps=registry,
    )


def build_kernel_knowledge_pack(
    *,
    mapuse_directory: str | Path,
    static_directory: str | Path,
    mapuse_source_version: str,
    static_source_version: str,
    pack_version: str,
    game_version: str | None = None,
) -> KnowledgePack:
    maps = load_mapuse_directory(
        mapuse_directory,
        source_version=mapuse_source_version,
        game_version=game_version,
    )
    spell_load = load_static_spells(
        static_directory,
        source_version=static_source_version,
        game_version=game_version,
    )
    catalog_load = load_static_catalog(
        static_directory,
        source_version=static_source_version,
        game_version=game_version,
        known_spell_ids=frozenset(spell.spell_id for spell in spell_load.spells),
    )
    classes = load_static_classes(
        static_directory,
        source_version=static_source_version,
        game_version=game_version,
    )
    companion_load = load_static_companions(
        static_directory,
        source_version=static_source_version,
        game_version=game_version,
        known_spell_ids=frozenset(spell.spell_id for spell in spell_load.spells),
    )
    monsters = load_static_monsters(
        static_directory,
        source_version=static_source_version,
        game_version=game_version,
    )
    monster_taxonomy = load_static_monster_taxonomy(
        static_directory,
        source_version=static_source_version,
        game_version=game_version,
    )
    world = load_static_world(
        static_directory,
        source_version=static_source_version,
        game_version=game_version,
    )
    map_locations = load_active_map_locations(
        static_directory,
        source_version=static_source_version,
        game_version=game_version,
        map_ids=frozenset(map_definition.map_id for map_definition in maps),
        known_sub_area_ids=frozenset(item.sub_area_id for item in world.sub_areas),
    )
    map_registry = DefinitionRegistry.from_items(maps, key=lambda item: item.map_id)
    map_location_registry = DefinitionRegistry.from_items(
        map_locations,
        key=lambda item: item.map_id,
    )
    spell_registry = DefinitionRegistry.from_items(
        spell_load.spells,
        key=lambda item: item.spell_id,
    )
    class_registry = DefinitionRegistry.from_items(
        classes,
        key=lambda item: item.class_id,
    )
    companion_registry = DefinitionRegistry.from_items(
        companion_load.companions,
        key=lambda item: item.companion_id,
    )
    companion_spell_registry = DefinitionRegistry.from_items(
        companion_load.spells,
        key=lambda item: item.companion_spell_id,
    )
    monster_registry = DefinitionRegistry.from_items(
        monsters,
        key=lambda item: item.monster_id,
    )
    monster_super_race_registry = DefinitionRegistry.from_items(
        monster_taxonomy.super_races,
        key=lambda item: item.super_race_id,
    )
    monster_race_registry = DefinitionRegistry.from_items(
        monster_taxonomy.races,
        key=lambda item: item.race_id,
    )
    super_area_registry = DefinitionRegistry.from_items(
        world.super_areas,
        key=lambda item: item.super_area_id,
    )
    area_registry = DefinitionRegistry.from_items(
        world.areas,
        key=lambda item: item.area_id,
    )
    sub_area_registry = DefinitionRegistry.from_items(
        world.sub_areas,
        key=lambda item: item.sub_area_id,
    )
    state_registry = DefinitionRegistry.from_items(
        catalog_load.states,
        key=lambda item: item.state_id,
    )
    effect_registry = DefinitionRegistry.from_items(
        catalog_load.effects,
        key=lambda item: item.effect_id,
    )
    variant_registry = DefinitionRegistry.from_items(
        catalog_load.spell_variants,
        key=lambda item: item.variant_id,
    )
    sources = tuple(sorted(set(
        _source_fingerprints(maps, spell_load.spells)
        + _additional_source_fingerprints(
            *map_locations,
            *classes,
            *companion_load.companions,
            *companion_load.spells,
            *monsters,
            *monster_taxonomy.super_races,
            *monster_taxonomy.races,
            *world.super_areas,
            *world.areas,
            *world.sub_areas,
            *catalog_load.states,
            *catalog_load.effects,
            *catalog_load.spell_variants,
        )
    )))
    return KnowledgePack(
        manifest=_manifest(
            pack_version=pack_version,
            game_version=game_version,
            sources=sources,
        ),
        maps=map_registry,
        map_locations=map_location_registry,
        spells=spell_registry,
        classes=class_registry,
        companions=companion_registry,
        companion_spells=companion_spell_registry,
        monsters=monster_registry,
        monster_super_races=monster_super_race_registry,
        monster_races=monster_race_registry,
        super_areas=super_area_registry,
        areas=area_registry,
        sub_areas=sub_area_registry,
        states=state_registry,
        effects=effect_registry,
        spell_variants=variant_registry,
        spell_diagnostics=SpellKnowledgeDiagnostics(
            orphan_level_ids=spell_load.orphan_level_ids,
            range_anomaly_level_ids=spell_load.range_anomaly_level_ids,
            field_anomalies=spell_load.field_anomalies,
        ),
    )
