from __future__ import annotations

from dataclasses import dataclass, field

from anka_game_kernel.contexts.fight import FightContext
from anka_game_kernel.domain.actors import ActorState
from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.ids import ActorId, CellId, SpellId
from anka_game_kernel.domain.maps import MapDefinition
from anka_game_kernel.domain.spells import SpellGradeDefinition
from anka_game_kernel.mechanics.casting.model import CastAvailabilityContext
from anka_game_kernel.mechanics.fight.model import CastEvaluationContext
from anka_game_kernel.mechanics.fight.service import FightService
from anka_game_kernel.mechanics.geometry.service import GeometryService
from anka_game_kernel.mechanics.los.service import LineOfSightService
from anka_game_kernel.mechanics.movement.service import MovementService
from anka_game_kernel.results.fight import CastEvaluationResult
from anka_game_kernel.results.fight_queries import NearestActorResult
from anka_game_kernel.results.los import LineOfSightResult
from anka_game_kernel.results.movement import MovementResult, ReachableCellsResult


@dataclass(frozen=True, slots=True)
class FightQueryService:
    """Read-only deterministic fight queries over caller-owned snapshots."""

    geometry: GeometryService = field(default_factory=GeometryService)
    movement: MovementService = field(default_factory=MovementService)
    los: LineOfSightService = field(default_factory=LineOfSightService)
    fight: FightService = field(default_factory=FightService)

    def distance(self, first: CellId, second: CellId) -> int:
        return self.geometry.distance(
            self.geometry.cell_to_coordinate(first),
            self.geometry.cell_to_coordinate(second),
        )

    def adjacent_cells(self, cell_id: CellId) -> tuple[CellId, ...]:
        coordinates = self.geometry.adjacent_cells(
            self.geometry.cell_to_coordinate(cell_id)
        )
        return tuple(
            sorted(
                (self.geometry.coordinate_to_cell(item) for item in coordinates),
                key=int,
            )
        )

    def is_hand_to_hand(self, first: CellId, second: CellId) -> bool:
        return self.distance(first, second) == 1

    def cells_aligned(self, first: CellId, second: CellId) -> bool:
        return self.geometry.are_aligned(
            self.geometry.cell_to_coordinate(first),
            self.geometry.cell_to_coordinate(second),
        )

    def cells_in_diagonal(self, first: CellId, second: CellId) -> bool:
        return self.geometry.are_diagonally_aligned(
            self.geometry.cell_to_coordinate(first),
            self.geometry.cell_to_coordinate(second),
        )

    @staticmethod
    def is_walkable(map_definition: MapDefinition, cell_id: CellId) -> bool | None:
        for cell in map_definition.cells:
            if cell.cell_id == cell_id:
                return cell.walkable and not cell.non_walkable_during_fight
        return None

    @staticmethod
    def fighter_at(context: FightContext, cell_id: CellId) -> ActorState | None:
        return context.actor_at(cell_id)

    @staticmethod
    def entities(context: FightContext) -> tuple[ActorState, ...]:
        return context.actors

    @staticmethod
    def entities_count(context: FightContext) -> int:
        return len(context.actors)

    @staticmethod
    def current_round(context: FightContext) -> int | None:
        return context.round_number

    @staticmethod
    def active_actor(context: FightContext) -> ActorState | None:
        if context.active_actor_id is None:
            return None
        return context.actor(context.active_actor_id)

    @staticmethod
    def is_free_cell(context: FightContext, cell_id: CellId) -> bool | None:
        if context.actor_at(cell_id) is not None:
            return False
        if context.occupied_cells is None:
            return None
        return True

    @staticmethod
    def cast_availability_from_context(
        context: FightContext,
        *,
        actor_id: ActorId,
        spell_id: SpellId,
        target_actor_id: ActorId | None = None,
        summon_slots_remaining: int | None = None,
    ) -> CastAvailabilityContext:
        if not isinstance(context, FightContext):
            raise TypeError("context must be a FightContext")
        actor = context.actor(actor_id)
        current_ap = None if actor is None else actor.current_ap
        cooldown_remaining = None if actor is None else actor.cooldown_remaining(spell_id)
        active_state_ids = None if actor is None else actor.active_state_ids

        history = context.current_turn
        history_matches_actor = history is not None and history.actor_id == actor_id
        casts_this_turn = history.cast_count(spell_id) if history_matches_actor else None
        casts_on_target_this_turn = (
            history.cast_count_on_target(spell_id, target_actor_id)
            if history_matches_actor and target_actor_id is not None
            else None
        )
        return CastAvailabilityContext(
            current_ap=current_ap,
            casts_this_turn=casts_this_turn,
            global_casts_this_turn=context.global_cast_count(spell_id),
            cooldown_remaining=cooldown_remaining,
            target_id=None if target_actor_id is None else int(target_actor_id),
            casts_on_target_this_turn=casts_on_target_this_turn,
            active_state_ids=active_state_ids,
            summon_slots_remaining=summon_slots_remaining,
        )

    def shortest_path(
        self,
        map_definition: MapDefinition,
        context: FightContext,
        actor_id: ActorId,
        target_cell: CellId,
        *,
        avoid_cells: frozenset[CellId] = frozenset(),
        ignore_actors: bool = False,
    ) -> MovementResult:
        actor = context.actor(actor_id)
        if actor is None:
            return MovementResult.incomplete(
                missing_input=f"actor:{actor_id}",
                explanation="Path query requires the source actor snapshot.",
            )
        if actor.cell_id is None:
            return MovementResult.incomplete(
                missing_input=f"actor:{actor_id}.cell_id",
                explanation="Path query requires the source actor cell.",
            )
        if not context.require_map(map_definition.map_id):
            return MovementResult.incomplete(
                missing_input="map_id",
                explanation="Path query requires the fight snapshot's canonical map identity.",
            )
        occupied: frozenset[CellId] | None = frozenset()
        if not ignore_actors:
            occupied = (
                None
                if context.occupied_cells is None
                else context.occupied_cells - frozenset({actor.cell_id})
            )
        return self.movement.shortest_path(
            map_definition,
            actor.cell_id,
            target_cell,
            occupied_cells=occupied,
            avoid_cells=avoid_cells,
        )

    def reachable_cells(
        self,
        map_definition: MapDefinition,
        context: FightContext,
        actor_id: ActorId,
        *,
        ignore_actors: bool = False,
    ) -> ReachableCellsResult:
        actor = context.actor(actor_id)
        if actor is None:
            return ReachableCellsResult.incomplete(
                missing_input=f"actor:{actor_id}",
                explanation="Reachable-cell query requires the source actor snapshot.",
            )
        if actor.cell_id is None:
            return ReachableCellsResult.incomplete(
                missing_input=f"actor:{actor_id}.cell_id",
                explanation="Reachable-cell query requires the source actor cell.",
            )
        if actor.current_mp is None:
            return ReachableCellsResult.incomplete(
                missing_input=f"actor:{actor_id}.current_mp",
                explanation="Reachable-cell query requires the actor's current MP.",
            )
        if not context.require_map(map_definition.map_id):
            return ReachableCellsResult.incomplete(
                missing_input="map_id",
                explanation="Reachable-cell query requires the fight snapshot's canonical map identity.",
            )
        occupied: frozenset[CellId] | None = frozenset()
        if not ignore_actors:
            occupied = (
                None
                if context.occupied_cells is None
                else context.occupied_cells - frozenset({actor.cell_id})
            )
        return self.movement.reachable_cells(
            map_definition,
            actor.cell_id,
            max_steps=actor.current_mp,
            occupied_cells=occupied,
        )

    def nearest_enemy(
        self,
        context: FightContext,
        actor_id: ActorId,
    ) -> NearestActorResult:
        return self._nearest_actor(context, actor_id, same_team=False)

    def nearest_ally(
        self,
        context: FightContext,
        actor_id: ActorId,
    ) -> NearestActorResult:
        return self._nearest_actor(context, actor_id, same_team=True)

    def _nearest_actor(
        self,
        context: FightContext,
        actor_id: ActorId,
        *,
        same_team: bool,
    ) -> NearestActorResult:
        source = context.actor(actor_id)
        if source is None:
            return NearestActorResult.incomplete(
                missing_inputs=(f"actor:{actor_id}",),
                explanation="Nearest-actor query requires the source actor snapshot.",
            )
        if source.team_id is None:
            return NearestActorResult.incomplete(
                missing_inputs=(f"actor:{actor_id}.team_id",),
                explanation="Nearest ally/enemy classification requires the source team id.",
            )
        if source.cell_id is None:
            return NearestActorResult.incomplete(
                missing_inputs=(f"actor:{actor_id}.cell_id",),
                explanation="Nearest-actor distance requires the source cell.",
            )

        candidates: list[tuple[int, int, int, ActorState]] = []
        unresolved: list[str] = []
        for actor in context.actors:
            if actor.actor_id == actor_id or actor.alive is False:
                continue
            if actor.team_id is None:
                unresolved.append(f"actor:{actor.actor_id}.team_id")
                continue
            matches = actor.team_id == source.team_id
            if matches != same_team:
                continue
            if actor.cell_id is None:
                unresolved.append(f"actor:{actor.actor_id}.cell_id")
                continue
            distance = self.distance(source.cell_id, actor.cell_id)
            candidates.append((distance, int(actor.cell_id), int(actor.actor_id), actor))

        if unresolved:
            return NearestActorResult.incomplete(
                missing_inputs=tuple(unresolved),
                explanation=(
                    "One or more live actors have unresolved team/position data that could "
                    "change the nearest matching actor."
                ),
            )
        if not candidates:
            return NearestActorResult.no_match()

        distance, _, _, actor = min(candidates)
        assert actor.cell_id is not None
        return NearestActorResult.found(
            actor_id=actor.actor_id,
            cell_id=actor.cell_id,
            distance=distance,
        )

    def line_of_sight(
        self,
        map_definition: MapDefinition,
        context: FightContext,
        first: CellId,
        second: CellId,
    ) -> LineOfSightResult:
        if not context.require_map(map_definition.map_id):
            return LineOfSightResult.incomplete(
                trace=(),
                missing_input="map_id",
                explanation="LoS query requires the fight snapshot's canonical map identity.",
            )
        return self.los.evaluate(
            map_definition,
            first,
            second,
            occupied_cells=context.occupied_cells,
        )

    def evaluate_grade_cast_from_cell(
        self,
        map_definition: MapDefinition,
        context: FightContext,
        actor_id: ActorId,
        grade: SpellGradeDefinition,
        target_cell: CellId,
        *,
        availability: CastAvailabilityContext,
        range_bonus: int | None = None,
    ) -> CastEvaluationResult:
        actor = context.actor(actor_id)
        if actor is None:
            return self._missing_cast_context(f"actor:{actor_id}")
        if actor.cell_id is None:
            return self._missing_cast_context(f"actor:{actor_id}.cell_id")
        resolved_range_bonus = self._resolve_range_bonus(actor, grade, range_bonus)
        if resolved_range_bonus is None:
            return self._missing_cast_context(f"actor:{actor_id}.combat_stats.range_bonus")
        if not context.require_map(map_definition.map_id):
            return self._missing_cast_context("map_id")
        return self._evaluate_grade_cast(
            map_definition,
            grade,
            launch_cell=actor.cell_id,
            target_cell=target_cell,
            availability=availability,
            range_bonus=resolved_range_bonus,
            occupied_cells=context.occupied_cells,
        )

    def evaluate_grade_cast_after_move(
        self,
        map_definition: MapDefinition,
        context: FightContext,
        actor_id: ActorId,
        grade: SpellGradeDefinition,
        *,
        launch_cell: CellId,
        target_cell: CellId,
        availability: CastAvailabilityContext,
        range_bonus: int | None = None,
    ) -> CastEvaluationResult:
        actor = context.actor(actor_id)
        if actor is None:
            return self._missing_cast_context(f"actor:{actor_id}")
        if actor.cell_id is None:
            return self._missing_cast_context(f"actor:{actor_id}.cell_id")
        resolved_range_bonus = self._resolve_range_bonus(actor, grade, range_bonus)
        if resolved_range_bonus is None:
            return self._missing_cast_context(f"actor:{actor_id}.combat_stats.range_bonus")
        if not context.require_map(map_definition.map_id):
            return self._missing_cast_context("map_id")

        if context.occupied_cells is None:
            return self._missing_cast_context("occupied_cells")
        occupied = (
            context.occupied_cells - frozenset({actor.cell_id})
        ) | frozenset({launch_cell})
        return self._evaluate_grade_cast(
            map_definition,
            grade,
            launch_cell=launch_cell,
            target_cell=target_cell,
            availability=availability,
            range_bonus=resolved_range_bonus,
            occupied_cells=occupied,
        )

    def _resolve_range_bonus(
        self,
        actor: ActorState,
        grade: SpellGradeDefinition,
        explicit_range_bonus: int | None,
    ) -> int | None:
        return self.fight.range.resolve_bonus(actor, grade, explicit_range_bonus)

    def _evaluate_grade_cast(
        self,
        map_definition: MapDefinition,
        grade: SpellGradeDefinition,
        *,
        launch_cell: CellId,
        target_cell: CellId,
        availability: CastAvailabilityContext,
        range_bonus: int,
        occupied_cells: frozenset[CellId] | None,
    ) -> CastEvaluationResult:
        return self.fight.evaluate_grade_cast(
            grade,
            CastEvaluationContext(
                map_definition=map_definition,
                caster_cell=launch_cell,
                target_cell=target_cell,
                availability=availability,
                range_bonus=range_bonus,
                occupied_cells=occupied_cells,
            ),
        )

    @staticmethod
    def _missing_cast_context(missing_input: str) -> CastEvaluationResult:
        return CastEvaluationResult(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            missing_inputs=(missing_input,),
            legal=None,
            explanation="Cast query requires the listed caller-owned actor snapshot value.",
        )

