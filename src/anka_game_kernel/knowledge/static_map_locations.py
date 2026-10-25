from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from anka_game_kernel.domain.ids import MapId, SubAreaId, WorldMapId
from anka_game_kernel.domain.map_locations import MapAccessRules, MapLocationDefinition, WorldCoordinate
from anka_game_kernel.domain.provenance import Provenance, SourceKind, VerificationStatus


class MapPositionSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: int
    posX: int
    posY: int
    nameId: int
    subAreaId: int
    worldMap: int
    tacticalModeTemplateId: int
    outdoor: bool
    showNameOnFingerpost: bool
    hasPriorityOnWorldmap: bool
    allowPrism: bool
    isTransition: bool
    mapHasTemplate: bool
    hasPublicPaddock: bool
    allowChallenge: bool
    allowAggression: bool
    allowTeleportTo: bool
    allowTeleportFrom: bool
    allowExchanges: bool
    allowHumanVendor: bool
    allowTaxCollector: bool
    allowSoulCapture: bool
    allowSoulSummon: bool
    allowTavernRegen: bool
    allowTombMode: bool
    allowTeleportEverywhere: bool
    allowFightChallenges: bool
    allowMonsterRespawn: bool
    allowMonsterFight: bool
    allowMount: bool
    allowObjectDisposal: bool
    isUnderWater: bool
    allowPvp1V1: bool
    allowPvp3V3: bool
    allowMonsterAggression: bool


def load_active_map_locations(
    directory: str | Path,
    *,
    source_version: str,
    map_ids: frozenset[MapId],
    known_sub_area_ids: frozenset[SubAreaId],
    game_version: str | None = None,
) -> tuple[MapLocationDefinition, ...]:
    path = Path(directory) / "MapPositions.json"
    if not path.is_file():
        raise ValueError(f"missing static source file: {path}")
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("MapPositions.json must contain a JSON object keyed by id")

    known_sub_raw = {int(item) for item in known_sub_area_ids}
    definitions: list[MapLocationDefinition] = []
    for map_id in sorted(map_ids, key=int):
        raw_id = int(map_id)
        raw_record = raw.get(str(raw_id))
        if raw_record is None:
            raise ValueError(f"active map {raw_id} is missing from MapPositions.json")
        source = MapPositionSource.model_validate(raw_record)
        if source.id != raw_id:
            raise ValueError(
                f"MapPositions.json key {raw_id} does not match record id {source.id}"
            )
        if source.subAreaId not in known_sub_raw:
            raise ValueError(
                f"active map {raw_id} references unknown sub area {source.subAreaId}"
            )
        if source.worldMap < -1:
            raise ValueError(
                f"active map {raw_id} has unsupported worldMap sentinel {source.worldMap}"
            )
        world_map_id = None if source.worldMap == -1 else WorldMapId(source.worldMap)
        definitions.append(
            MapLocationDefinition(
                map_id=map_id,
                coordinate=WorldCoordinate(source.posX, source.posY),
                name_id=source.nameId,
                sub_area_id=SubAreaId(source.subAreaId),
                world_map_id=world_map_id,
                tactical_mode_template_id=source.tacticalModeTemplateId,
                access=MapAccessRules(
                    outdoor=source.outdoor,
                    show_name_on_fingerpost=source.showNameOnFingerpost,
                    has_priority_on_worldmap=source.hasPriorityOnWorldmap,
                    allow_prism=source.allowPrism,
                    is_transition=source.isTransition,
                    map_has_template=source.mapHasTemplate,
                    has_public_paddock=source.hasPublicPaddock,
                    allow_challenge=source.allowChallenge,
                    allow_aggression=source.allowAggression,
                    allow_teleport_to=source.allowTeleportTo,
                    allow_teleport_from=source.allowTeleportFrom,
                    allow_exchanges=source.allowExchanges,
                    allow_human_vendor=source.allowHumanVendor,
                    allow_tax_collector=source.allowTaxCollector,
                    allow_soul_capture=source.allowSoulCapture,
                    allow_soul_summon=source.allowSoulSummon,
                    allow_tavern_regen=source.allowTavernRegen,
                    allow_tomb_mode=source.allowTombMode,
                    allow_teleport_everywhere=source.allowTeleportEverywhere,
                    allow_fight_challenges=source.allowFightChallenges,
                    allow_monster_respawn=source.allowMonsterRespawn,
                    allow_monster_fight=source.allowMonsterFight,
                    allow_mount=source.allowMount,
                    allow_object_disposal=source.allowObjectDisposal,
                    is_under_water=source.isUnderWater,
                    allow_pvp_1v1=source.allowPvp1V1,
                    allow_pvp_3v3=source.allowPvp3V3,
                    allow_monster_aggression=source.allowMonsterAggression,
                ),
                provenance=Provenance(
                    source_kind=SourceKind.USER_SUPPLIED_STATIC,
                    source_name="Static",
                    source_version=source_version,
                    source_file="MapPositions.json",
                    source_record_id=str(raw_id),
                    game_version=game_version,
                    verification_status=VerificationStatus.SOURCE_VALIDATED,
                    source_hash=source_hash,
                    importer_version="static-map-locations-v1",
                    normalizer_version="static-map-locations-v1",
                ),
            )
        )
    return tuple(definitions)
