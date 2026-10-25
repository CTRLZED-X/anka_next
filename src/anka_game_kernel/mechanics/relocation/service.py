from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.contexts.fight import FightContext
from anka_game_kernel.domain.actors import ActorState
from anka_game_kernel.domain.ids import CellId
from anka_game_kernel.domain.maps import MapDefinition
from anka_game_kernel.mechanics.relocation.model import (
    RelocationFailureReason,
    TeleportSpec,
)
from anka_game_kernel.results.relocation import SwapResult, TeleportResult


@dataclass(frozen=True, slots=True)
class TeleportService:
    """Pure rule-parameterized teleport destination validation."""

    def evaluate(
        self,
        map_definition: MapDefinition,
        actor: ActorState,
        destination_cell: CellId,
        spec: TeleportSpec,
        *,
        fight_context: FightContext | None,
    ) -> TeleportResult:
        source_cell = actor.cell_id
        if source_cell is None:
            return TeleportResult.incomplete(
                missing_input="source_cell",
                source_cell=None,
                destination_cell=destination_cell,
                explanation="Teleport evaluation requires the actor's current source cell.",
            )

        cells_by_id = {cell.cell_id: cell for cell in map_definition.cells}
        destination = cells_by_id.get(destination_cell)
        if destination is None:
            return TeleportResult.incomplete(
                missing_input=f"map_cell:{destination_cell}",
                source_cell=source_cell,
                destination_cell=destination_cell,
                explanation="Teleport evaluation requires the destination cell's static map definition.",
            )

        if spec.require_walkable and not destination.walkable:
            return TeleportResult.deterministic(
                legal=False,
                source_cell=source_cell,
                destination_cell=destination_cell,
                failure=RelocationFailureReason.DESTINATION_NOT_WALKABLE,
                explanation="The teleport rule requires a statically walkable destination.",
            )
        if spec.require_fight_walkable and destination.non_walkable_during_fight:
            return TeleportResult.deterministic(
                legal=False,
                source_cell=source_cell,
                destination_cell=destination_cell,
                failure=RelocationFailureReason.DESTINATION_NON_WALKABLE_DURING_FIGHT,
                explanation="The teleport rule rejects cells marked non-walkable during fights.",
            )

        if spec.require_unoccupied:
            if fight_context is None:
                return TeleportResult.incomplete(
                    missing_input="fight_context",
                    source_cell=source_cell,
                    destination_cell=destination_cell,
                    explanation="Teleport occupancy validation requires a caller-owned fight snapshot.",
                )
            occupied_cells = fight_context.occupied_cells
            if occupied_cells is None:
                return TeleportResult.incomplete(
                    missing_input="occupied_cells",
                    source_cell=source_cell,
                    destination_cell=destination_cell,
                    explanation="Teleport occupancy validation requires complete live actor positions.",
                )
            occupied_by_others = occupied_cells - frozenset({source_cell})
            if destination_cell in occupied_by_others:
                return TeleportResult.deterministic(
                    legal=False,
                    source_cell=source_cell,
                    destination_cell=destination_cell,
                    failure=RelocationFailureReason.DESTINATION_OCCUPIED,
                    explanation="The teleport rule requires an unoccupied destination cell.",
                )

        return TeleportResult.deterministic(
            legal=True,
            source_cell=source_cell,
            destination_cell=destination_cell,
            explanation="The destination satisfies every explicit teleport rule.",
        )


@dataclass(frozen=True, slots=True)
class SwapService:
    """Pure two-actor position-swap primitive.

    Spell-specific restrictions belong to targeting/state rules. This primitive
    only proves that both actor positions are known and represented by the map.
    """

    def evaluate(
        self,
        map_definition: MapDefinition,
        first_actor: ActorState,
        second_actor: ActorState,
    ) -> SwapResult:
        if first_actor.cell_id is None:
            return SwapResult.incomplete(
                missing_input="first_actor.cell_id",
                explanation="Swap evaluation requires the first actor's current cell.",
            )
        if second_actor.cell_id is None:
            return SwapResult.incomplete(
                missing_input="second_actor.cell_id",
                explanation="Swap evaluation requires the second actor's current cell.",
            )

        known_cells = {cell.cell_id for cell in map_definition.cells}
        if first_actor.cell_id not in known_cells:
            return SwapResult.incomplete(
                missing_input=f"map_cell:{first_actor.cell_id}",
                explanation="Swap evaluation requires the first actor cell's static map definition.",
            )
        if second_actor.cell_id not in known_cells:
            return SwapResult.incomplete(
                missing_input=f"map_cell:{second_actor.cell_id}",
                explanation="Swap evaluation requires the second actor cell's static map definition.",
            )

        return SwapResult.deterministic(
            first_destination=second_actor.cell_id,
            second_destination=first_actor.cell_id,
            explanation="Both actor positions are known; the swap exchanges their cells without mutating caller state.",
        )
