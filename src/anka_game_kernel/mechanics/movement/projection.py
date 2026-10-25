from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.contexts.fight import FightContext
from anka_game_kernel.contexts.projection import FightProjection
from anka_game_kernel.contexts.turn_history import MovementRecord
from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.ids import ActorId, CellId
from anka_game_kernel.mechanics.geometry.grid import adjacent_cells, cell_to_coordinate, coordinate_to_cell
from anka_game_kernel.domain.maps import MapDefinition
from anka_game_kernel.mechanics.movement.service import MovementService
from anka_game_kernel.mechanics.projection.service import FightProjectionService
from anka_game_kernel.results.movement_projection import MovementActionProjectionResult


@dataclass(frozen=True, slots=True)
class MovementProjectionService:
    movement: MovementService
    projection_service: FightProjectionService

    def project_move_to(
        self,
        *,
        map_definition: MapDefinition,
        context: FightContext,
        actor_id: ActorId,
        target_cell: CellId,
    ) -> MovementActionProjectionResult:
        projection = FightProjection.from_context(context)
        if not context.require_map(map_definition.map_id):
            return MovementActionProjectionResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                missing_inputs=("map_id",), legal=None, projection_complete=False,
                projection=projection,
                explanation="Movement projection requires the fight snapshot's canonical map identity.",
            )
        actor = context.actor(actor_id)
        if actor is None:
            return MovementActionProjectionResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                missing_inputs=(f"actor:{int(actor_id)}",), legal=None, projection_complete=False,
                projection=projection, explanation="Movement projection requires the actor snapshot.",
            )
        if actor.cell_id is None:
            return MovementActionProjectionResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                missing_inputs=(f"actor:{int(actor_id)}:cell",), legal=None, projection_complete=False,
                projection=projection, explanation="Movement projection requires the actor cell.",
            )

        occupied_cells = context.occupied_cells
        movement = self.movement.shortest_path(
            map_definition,
            actor.cell_id,
            target_cell,
            occupied_cells=(
                None
                if occupied_cells is None
                else occupied_cells - frozenset({actor.cell_id})
            ),
        )
        if movement.certainty is not Certainty.DETERMINISTIC or movement.reachable is not True:
            return MovementActionProjectionResult(
                certainty=movement.certainty,
                missing_inputs=movement.missing_inputs,
                legal=False if movement.reachable is False else None, projection_complete=False,
                movement=movement,
                projection=projection,
                explanation=movement.explanation,
            )
        if movement.path and len(movement.path) > 1:
            tackle_result = self._tackle_risk(context, actor_id, movement.path)
            if tackle_result is not None:
                return MovementActionProjectionResult(
                    certainty=tackle_result[0],
                    missing_inputs=tackle_result[1],
                    legal=None,
                    projection_complete=False,
                    movement=movement,
                    projection=projection,
                    explanation=tackle_result[2],
                )

        if actor.current_mp is None:
            return MovementActionProjectionResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                missing_inputs=("current_mp",), legal=None, projection_complete=False, movement=movement,
                projection=projection,
                explanation="Verified path exists, but current MP is missing from the caller snapshot.",
            )
        if context.current_turn is None or context.current_turn.actor_id != actor_id:
            return MovementActionProjectionResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                missing_inputs=("current_turn",), legal=None, projection_complete=False, movement=movement,
                projection=projection,
                explanation="Movement history projection requires the active actor's current turn history.",
            )

        cost = movement.step_count
        assert cost is not None
        if cost > actor.current_mp:
            return MovementActionProjectionResult(
                certainty=Certainty.DETERMINISTIC,
                legal=False, projection_complete=False,
                movement=movement,
                projection=projection,
                explanation="The verified path cost exceeds the caller-supplied current MP.",
            )

        reactive_missing: list[str] = []
        for modifier in context.per_mp_used_modifiers:
            if modifier.actor_id != actor_id or modifier.remaining_triggers <= 0:
                continue
            if modifier.range_delta_per_mp:
                if actor.combat_stats is None or actor.combat_stats.range_bonus is None:
                    reactive_missing.append(
                        f"actor:{int(actor_id)}:combat_stats.range_bonus"
                    )
            if modifier.characteristic_delta_per_mp:
                if (
                    actor.semantic_characteristics is None
                    or actor.semantic_characteristics.get(modifier.characteristic) is None
                ):
                    reactive_missing.append(
                        f"actor:{int(actor_id)}:semantic_characteristics:{modifier.characteristic.value}"
                    )
        if reactive_missing:
            return MovementActionProjectionResult(
                certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                missing_inputs=tuple(dict.fromkeys(reactive_missing)),
                legal=None,
                projection_complete=False,
                movement=movement,
                projection=projection,
                explanation=(
                    "Movement is geometrically valid, but reactive per-MP modifiers require "
                    "the caller-owned range/semantic characteristic snapshot."
                ),
            )

        projection = self.projection_service.spend_mp(projection, actor_id, cost)
        if target_cell != actor.cell_id:
            projection = self.projection_service.move_actor(projection, actor_id, target_cell)
        projection = self.projection_service.append_movement(
            projection,
            MovementRecord(actor_id=actor_id, path=movement.path, mp_spent=cost),
        )
        projection = self.projection_service.apply_per_mp_used_modifiers(
            projection,
            actor_id,
            cost,
        )
        return MovementActionProjectionResult(
            certainty=Certainty.DETERMINISTIC,
            legal=True, projection_complete=True,
            movement=movement,
            projection=projection,
            explanation=(
                "Verified path cost, final cell, MP spend, and movement history were projected "
                "without mutating caller-owned fight state."
            ),
        )
    @staticmethod
    def _tackle_risk(
        context: FightContext,
        actor_id: ActorId,
        path: tuple[CellId, ...],
    ) -> tuple[Certainty, tuple[str, ...], str] | None:
        mover = context.actor(actor_id)
        if mover is None:
            return None
        departure_cells = path[:-1]
        adjacent_ids: set[CellId] = set()
        for cell in departure_cells:
            for coord in adjacent_cells(cell_to_coordinate(cell)):
                adjacent_ids.add(coordinate_to_cell(coord))
        for other in context.actors:
            if other.actor_id == actor_id or other.alive is False or other.cell_id not in adjacent_ids:
                continue
            if other.alive is None:
                return (
                    Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                    (f"actor:{int(other.actor_id)}:alive",),
                    "Movement may cross a tackle zone, but the adjacent actor's alive state is unknown.",
                )
            missing: list[str] = []
            if mover.team_id is None:
                missing.append(f"actor:{int(actor_id)}:team_id")
            if other.team_id is None:
                missing.append(f"actor:{int(other.actor_id)}:team_id")
            if missing:
                return (
                    Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                    tuple(missing),
                    "Movement may cross a tackle zone, but team classification is incomplete.",
                )
            if mover.team_id != other.team_id:
                return (
                    Certainty.UNSUPPORTED,
                    ("mechanic:tackle_lock",),
                    "Potential tackle/lock interaction is detected on the path; exact current tackle semantics are intentionally unsupported, so movement projection fails closed.",
                )
        return None

