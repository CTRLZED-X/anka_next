from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.ids import MapId, SubAreaId, WorldMapId
from anka_game_kernel.domain.provenance import Provenance


@dataclass(frozen=True, slots=True, order=True)
class WorldCoordinate:
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class MapAccessRules:
    outdoor: bool
    show_name_on_fingerpost: bool
    has_priority_on_worldmap: bool
    allow_prism: bool
    is_transition: bool
    map_has_template: bool
    has_public_paddock: bool
    allow_challenge: bool
    allow_aggression: bool
    allow_teleport_to: bool
    allow_teleport_from: bool
    allow_exchanges: bool
    allow_human_vendor: bool
    allow_tax_collector: bool
    allow_soul_capture: bool
    allow_soul_summon: bool
    allow_tavern_regen: bool
    allow_tomb_mode: bool
    allow_teleport_everywhere: bool
    allow_fight_challenges: bool
    allow_monster_respawn: bool
    allow_monster_fight: bool
    allow_mount: bool
    allow_object_disposal: bool
    is_under_water: bool
    allow_pvp_1v1: bool
    allow_pvp_3v3: bool
    allow_monster_aggression: bool


@dataclass(frozen=True, slots=True)
class MapLocationDefinition:
    map_id: MapId
    coordinate: WorldCoordinate
    name_id: int
    sub_area_id: SubAreaId
    world_map_id: WorldMapId | None
    tactical_mode_template_id: int
    access: MapAccessRules
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.name_id < 0:
            raise ValueError("map-location name_id cannot be negative")
        if self.tactical_mode_template_id < 0:
            raise ValueError("tactical_mode_template_id cannot be negative")

    @property
    def allow_monster_fight(self) -> bool:
        return self.access.allow_monster_fight

    @property
    def allow_fight_challenges(self) -> bool:
        return self.access.allow_fight_challenges
