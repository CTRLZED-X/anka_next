from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from anka_game_kernel.config import ExternalGameDataConfig

from anka_game_kernel.domain.ids import AreaId, ClassId, CompanionId, CompanionSpellId, EffectId, MapId, MonsterId, MonsterRaceId, MonsterSuperRaceId, SpellId, SpellVariantId, StateId, SubAreaId, SuperAreaId
from anka_game_kernel.domain.classes import ClassDefinition
from anka_game_kernel.domain.companions import CompanionDefinition, CompanionSpellDefinition
from anka_game_kernel.domain.effects import EffectDefinition
from anka_game_kernel.domain.maps import MapDefinition
from anka_game_kernel.domain.map_locations import MapLocationDefinition
from anka_game_kernel.domain.monsters import MonsterDefinition
from anka_game_kernel.domain.monster_taxonomy import MonsterRaceDefinition, MonsterSuperRaceDefinition
from anka_game_kernel.domain.spell_variants import SpellVariantDefinition
from anka_game_kernel.domain.spells import SpellDefinition
from anka_game_kernel.domain.states import StateDefinition
from anka_game_kernel.domain.world import AreaDefinition, SubAreaDefinition, SuperAreaDefinition
from anka_game_kernel.knowledge.spell_mechanics import SpellMechanicsPack
from anka_game_kernel.knowledge.spell_overlay import SpellMechanicsOverlay
from anka_game_kernel.knowledge.spell_readiness import SpellReadinessService
from anka_game_kernel.knowledge.pack import (
    KnowledgePack,
    build_kernel_knowledge_pack,
    build_mapuse_knowledge_pack,
)
from anka_game_kernel.mechanics.actor_queries import ActorQueryService
from anka_game_kernel.mechanics.aoe.service import AoEService
from anka_game_kernel.mechanics.casting.service import CastAvailabilityService
from anka_game_kernel.mechanics.collision.service import CollisionService
from anka_game_kernel.mechanics.geometry.service import GeometryService
from anka_game_kernel.mechanics.displacement.service import DisplacementService
from anka_game_kernel.mechanics.effect_resolution.service import EffectResolutionService
from anka_game_kernel.mechanics.effect_conditions.service import EffectConditionService
from anka_game_kernel.mechanics.fight.service import FightService
from anka_game_kernel.mechanics.fight.projection import CastActionProjectionService
from anka_game_kernel.mechanics.fight_queries.service import FightQueryService
from anka_game_kernel.mechanics.fight_queries.spell_decisions import SpellDecisionService
from anka_game_kernel.mechanics.los.service import LineOfSightService
from anka_game_kernel.mechanics.movement.service import MovementService
from anka_game_kernel.mechanics.movement.projection import MovementProjectionService
from anka_game_kernel.mechanics.range.service import RangeService
from anka_game_kernel.mechanics.projection.service import FightProjectionService
from anka_game_kernel.mechanics.relocation.service import SwapService, TeleportService
from anka_game_kernel.mechanics.registry import MechanicKey, MechanicRegistry
from anka_game_kernel.mechanics.targeting.service import TargetingService
from anka_game_kernel.mechanics.states.service import StateService
from anka_game_kernel.mechanics.status_queries.service import StatusQueryService
from anka_game_kernel.mechanics.world.service import WorldService
from anka_game_kernel.registries.base import DefinitionRegistry
from anka_game_kernel.errors import ExternalGameDataError, KernelError


@dataclass(frozen=True, slots=True)
class GameKernel:
    knowledge: KnowledgePack
    spell_mechanics: SpellMechanicsPack | None = None
    external_data: ExternalGameDataConfig | None = None
    geometry: GeometryService = field(default_factory=GeometryService)
    aoe: AoEService = field(default_factory=AoEService)
    los: LineOfSightService = field(default_factory=LineOfSightService)
    movement: MovementService = field(default_factory=MovementService)
    displacement: DisplacementService = field(default_factory=DisplacementService)
    collision: CollisionService = field(default_factory=CollisionService)
    teleport: TeleportService = field(default_factory=TeleportService)
    swap: SwapService = field(default_factory=SwapService)
    state_engine: StateService = field(default_factory=StateService)
    range: RangeService = field(default_factory=RangeService)
    targeting: TargetingService = field(default_factory=TargetingService)
    casting: CastAvailabilityService = field(default_factory=CastAvailabilityService)
    fight: FightService = field(default_factory=FightService)
    fight_queries: FightQueryService = field(default_factory=FightQueryService)
    actor_queries: ActorQueryService = field(default_factory=ActorQueryService)
    status_queries: StatusQueryService = field(default_factory=StatusQueryService)

    @classmethod
    def load(
        cls,
        knowledge_pack: KnowledgePack,
        *,
        spell_mechanics: SpellMechanicsPack | None = None,
    ) -> "GameKernel":
        return cls(knowledge=knowledge_pack, spell_mechanics=spell_mechanics)

    @classmethod
    def start(
        cls,
        config: ExternalGameDataConfig | None = None,
        *,
        spell_mechanics: SpellMechanicsPack | None = None,
    ) -> "GameKernel":
        resolved = (config or ExternalGameDataConfig.from_environment()).validate()
        try:
            knowledge = build_kernel_knowledge_pack(
                mapuse_directory=resolved.mapuse_directory,
                static_directory=resolved.static_directory,
                mapuse_source_version=resolved.mapuse_source_version,
                static_source_version=resolved.static_source_version,
                pack_version=resolved.pack_version,
                game_version=resolved.game_version,
            )
        except (OSError, ValueError, KeyError, KernelError) as exc:
            raise ExternalGameDataError(
                "Failed to load external game data from "
                f"Static={resolved.static_directory} and "
                f"Mapuse={resolved.mapuse_directory}: {exc}"
            ) from exc
        return cls(
            knowledge=knowledge,
            spell_mechanics=spell_mechanics,
            external_data=resolved,
        )

    @classmethod
    def from_mapuse(
        cls,
        directory: str | Path,
        *,
        source_version: str,
        pack_version: str,
        game_version: str | None = None,
    ) -> "GameKernel":
        return cls.load(
            build_mapuse_knowledge_pack(
                directory,
                source_version=source_version,
                pack_version=pack_version,
                game_version=game_version,
            )
        )


    @classmethod
    def from_sources(
        cls,
        *,
        mapuse_directory: str | Path,
        static_directory: str | Path,
        mapuse_source_version: str,
        static_source_version: str,
        pack_version: str,
        game_version: str | None = None,
    ) -> "GameKernel":
        return cls.load(
            build_kernel_knowledge_pack(
                mapuse_directory=mapuse_directory,
                static_directory=static_directory,
                mapuse_source_version=mapuse_source_version,
                static_source_version=static_source_version,
                pack_version=pack_version,
                game_version=game_version,
            )
        )


    @property
    def movement_projection(self) -> MovementProjectionService:
        return MovementProjectionService(
            movement=self.movement,
            projection_service=FightProjectionService(),
        )

    @property
    def action_projection(self) -> CastActionProjectionService:
        return CastActionProjectionService(
            overlay=self.spell_mechanics_overlay,
            fight=self.fight,
            resolver=self.effect_resolver,
            projection_service=FightProjectionService(),
        )

    @property
    def spell_decisions(self) -> SpellDecisionService:
        return SpellDecisionService(
            overlay=self.spell_mechanics_overlay,
            fight=self.fight,
            action_projection=self.action_projection,
        )

    @property
    def effect_resolver(self) -> EffectResolutionService:
        return EffectResolutionService(
            aoe=self.aoe,
            targeting=self.targeting,
            projection_service=FightProjectionService(),
            mechanics=self.mechanics,
            conditions=EffectConditionService(),
        )

    @property
    def spell_mechanics_overlay(self) -> SpellMechanicsOverlay:
        return SpellMechanicsOverlay(
            spells=self.knowledge.spells,
            mechanics_pack=self.spell_mechanics,
            effects=self.knowledge.effects,
            states=self.knowledge.states,
            game_version=self.knowledge.manifest.game_version,
        )

    @property
    def spell_readiness(self) -> SpellReadinessService:
        return SpellReadinessService(
            overlay=self.spell_mechanics_overlay,
            mechanics=self.mechanics,
            resolver=self.effect_resolver,
        )

    @property
    def mechanics(self) -> MechanicRegistry:
        return MechanicRegistry(
            {
                MechanicKey.RANGE: self.range,
                MechanicKey.AOE: self.aoe,
                MechanicKey.LINE_OF_SIGHT: self.los,
                MechanicKey.TARGETING: self.targeting,
                MechanicKey.MOVEMENT: self.movement,
                MechanicKey.PUSH: self.displacement,
                MechanicKey.PULL: self.displacement,
                MechanicKey.RECOIL: self.displacement,
                MechanicKey.COLLISION: self.collision,
                MechanicKey.TELEPORT: self.teleport,
                MechanicKey.SWAP: self.swap,
                MechanicKey.APPLY_STATE: self.state_engine,
                MechanicKey.REMOVE_STATE: self.state_engine,
                MechanicKey.CAST_AVAILABILITY: self.casting,
                MechanicKey.FIGHT_CAST: self.fight,
            }
        )


    @property
    def world(self) -> WorldService:
        return WorldService(maps=self.maps)

    @property
    def maps(self) -> DefinitionRegistry[MapId, MapDefinition]:
        return self.knowledge.maps


    @property
    def map_locations(self) -> DefinitionRegistry[MapId, MapLocationDefinition]:
        return self.knowledge.map_locations

    @property
    def spells(self) -> DefinitionRegistry[SpellId, SpellDefinition]:
        return self.knowledge.spells

    @property
    def classes(self) -> DefinitionRegistry[ClassId, ClassDefinition]:
        return self.knowledge.classes

    @property
    def companions(self) -> DefinitionRegistry[CompanionId, CompanionDefinition]:
        return self.knowledge.companions

    @property
    def companion_spells(
        self,
    ) -> DefinitionRegistry[CompanionSpellId, CompanionSpellDefinition]:
        return self.knowledge.companion_spells


    @property
    def monsters(self) -> DefinitionRegistry[MonsterId, MonsterDefinition]:
        return self.knowledge.monsters

    @property
    def monster_super_races(
        self,
    ) -> DefinitionRegistry[MonsterSuperRaceId, MonsterSuperRaceDefinition]:
        return self.knowledge.monster_super_races

    @property
    def monster_races(
        self,
    ) -> DefinitionRegistry[MonsterRaceId, MonsterRaceDefinition]:
        return self.knowledge.monster_races


    @property
    def super_areas(self) -> DefinitionRegistry[SuperAreaId, SuperAreaDefinition]:
        return self.knowledge.super_areas

    @property
    def areas(self) -> DefinitionRegistry[AreaId, AreaDefinition]:
        return self.knowledge.areas

    @property
    def sub_areas(self) -> DefinitionRegistry[SubAreaId, SubAreaDefinition]:
        return self.knowledge.sub_areas

    @property
    def states(self) -> DefinitionRegistry[StateId, StateDefinition]:
        return self.knowledge.states

    @property
    def effects(self) -> DefinitionRegistry[EffectId, EffectDefinition]:
        return self.knowledge.effects

    @property
    def spell_variants(self) -> DefinitionRegistry[SpellVariantId, SpellVariantDefinition]:
        return self.knowledge.spell_variants

