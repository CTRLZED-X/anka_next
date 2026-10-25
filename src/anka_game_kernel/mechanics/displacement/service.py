from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.ids import CellId
from anka_game_kernel.domain.maps import MapCellDefinition, MapDefinition
from anka_game_kernel.mechanics.displacement.model import DisplacementBlockReason
from anka_game_kernel.mechanics.geometry.grid import (
    cell_to_coordinate,
    coordinate_to_cell,
    direction8_between,
    neighbor,
    neighbors8,
    transition_side_cells,
)
from anka_game_kernel.results.displacement import (
    DisplacementResult,
    LinearDisplacementPlanResult,
)


@dataclass(frozen=True, slots=True)
class DisplacementService:
    """Resolve an explicit forced-movement cell path against static and live blockers.

    Path generation is intentionally outside this service. Callers provide an ordered
    sequence of canonical adjacent destination cells. This keeps push/pull direction
    rules separate from collision/path resolution until those semantics are verified.
    """

    def plan_push(
        self,
        *,
        source_cell: CellId,
        target_cell: CellId,
        distance: int,
    ) -> LinearDisplacementPlanResult:
        return self._plan_linear(
            source_cell=source_cell,
            target_cell=target_cell,
            distance=distance,
            toward_source=False,
        )

    def plan_pull(
        self,
        *,
        source_cell: CellId,
        target_cell: CellId,
        distance: int,
    ) -> LinearDisplacementPlanResult:
        return self._plan_linear(
            source_cell=source_cell,
            target_cell=target_cell,
            distance=distance,
            toward_source=True,
        )

    @staticmethod
    def _plan_linear(
        *,
        source_cell: CellId,
        target_cell: CellId,
        distance: int,
        toward_source: bool,
    ) -> LinearDisplacementPlanResult:
        if isinstance(distance, bool) or not isinstance(distance, int):
            raise TypeError("distance must be an int")
        if distance < 0:
            raise ValueError("distance cannot be negative")
        if distance == 0:
            return LinearDisplacementPlanResult.deterministic(
                path=(),
                requested_distance=0,
                explanation="Zero-distance displacement requires no direction or path.",
            )

        source = cell_to_coordinate(source_cell)
        target = cell_to_coordinate(target_cell)
        if source == target:
            return LinearDisplacementPlanResult.unsupported(
                requested_distance=distance,
                explanation="Positive displacement has no defined direction when source and target share a cell.",
            )

        direction = (
            direction8_between(target, source)
            if toward_source
            else direction8_between(source, target)
        )

        current = target
        path: list[CellId] = []
        for _ in range(distance):
            candidate = neighbor(current, direction)
            if candidate is None:
                return LinearDisplacementPlanResult.deterministic(
                    path=tuple(path),
                    requested_distance=distance,
                    boundary_reached=True,
                    explanation="The requested 8-direction displacement reaches the canonical map boundary.",
                )
            path.append(coordinate_to_cell(candidate))
            current = candidate

        return LinearDisplacementPlanResult.deterministic(
            path=tuple(path),
            requested_distance=distance,
            explanation="The client-quantized 8-direction displacement path is fully inside the canonical map.",
        )

    def resolve_push(
        self,
        map_definition: MapDefinition,
        *,
        source_cell: CellId,
        target_cell: CellId,
        distance: int,
        occupied_cells: frozenset[CellId] | None,
    ) -> DisplacementResult:
        plan = self.plan_push(
            source_cell=source_cell,
            target_cell=target_cell,
            distance=distance,
        )
        return self._resolve_linear_plan(
            map_definition,
            target_cell=target_cell,
            plan=plan,
            occupied_cells=occupied_cells,
        )

    def resolve_pull(
        self,
        map_definition: MapDefinition,
        *,
        source_cell: CellId,
        target_cell: CellId,
        distance: int,
        occupied_cells: frozenset[CellId] | None,
    ) -> DisplacementResult:
        plan = self.plan_pull(
            source_cell=source_cell,
            target_cell=target_cell,
            distance=distance,
        )
        return self._resolve_linear_plan(
            map_definition,
            target_cell=target_cell,
            plan=plan,
            occupied_cells=occupied_cells,
        )

    def _resolve_linear_plan(
        self,
        map_definition: MapDefinition,
        *,
        target_cell: CellId,
        plan: LinearDisplacementPlanResult,
        occupied_cells: frozenset[CellId] | None,
    ) -> DisplacementResult:
        if plan.certainty is not Certainty.DETERMINISTIC:
            return DisplacementResult.unsupported(
                explanation=plan.explanation
                or "The requested displacement direction is not supported.",
            )

        resolved = self.resolve_path(
            map_definition,
            target_cell,
            plan.path,
            occupied_cells=occupied_cells,
        )
        if resolved.completed is not True:
            return resolved
        if plan.boundary_reached:
            return DisplacementResult.deterministic(
                completed=False,
                traversed_cells=resolved.traversed_cells,
                failure=DisplacementBlockReason.MAP_BOUNDARY,
                explanation="Forced displacement reaches the canonical map boundary.",
            )
        return resolved

    def resolve_path(
        self,
        map_definition: MapDefinition,
        start_cell: CellId,
        candidate_cells: tuple[CellId, ...],
        *,
        occupied_cells: frozenset[CellId] | None,
    ) -> DisplacementResult:
        cells_by_id = {cell.cell_id: cell for cell in map_definition.cells}
        if start_cell not in cells_by_id:
            return DisplacementResult.incomplete(
                missing_input=f"map_cell:{start_cell}",
                traversed_cells=(),
                explanation="Forced displacement requires the start cell's static definition.",
            )

        self._validate_adjacent_path(start_cell, candidate_cells)
        traversed: list[CellId] = [start_cell]
        runtime_occupied = (
            occupied_cells - frozenset({start_cell})
            if occupied_cells is not None
            else None
        )

        previous_cell = start_cell
        for cell_id in candidate_cells:
            cell = cells_by_id.get(cell_id)
            if cell is None:
                return DisplacementResult.incomplete(
                    missing_input=f"map_cell:{cell_id}",
                    traversed_cells=tuple(traversed),
                    explanation="Forced displacement requires every candidate cell's static definition.",
                )

            static_failure = self._static_block_reason(cell)
            if static_failure is not None:
                return DisplacementResult.deterministic(
                    completed=False,
                    traversed_cells=tuple(traversed),
                    blocked_cell=cell_id,
                    failure=static_failure,
                    explanation="Forced displacement stops immediately before a static fight obstacle.",
                )

            side_cell_ids = tuple(
                coordinate_to_cell(side)
                for side in transition_side_cells(
                    cell_to_coordinate(previous_cell),
                    cell_to_coordinate(cell_id),
                )
            )
            for side_cell_id in side_cell_ids:
                side_definition = cells_by_id.get(side_cell_id)
                if side_definition is None:
                    return DisplacementResult.incomplete(
                        missing_input=f"map_cell:{side_cell_id}",
                        traversed_cells=tuple(traversed),
                        explanation=(
                            "Diagonal forced displacement requires both side-cell static definitions."
                        ),
                    )
                side_failure = self._static_block_reason(side_definition)
                if side_failure is not None:
                    return DisplacementResult.deterministic(
                        completed=False,
                        traversed_cells=tuple(traversed),
                        blocked_cell=side_cell_id,
                        failure=side_failure,
                        explanation=(
                            "Forced displacement stops before a diagonal transition whose side passage is statically blocked."
                        ),
                    )

            if runtime_occupied is None:
                return DisplacementResult.incomplete(
                    missing_input="occupied_cells",
                    traversed_cells=tuple(traversed),
                    explanation=(
                        "Forced displacement requires runtime occupancy for the destination and any diagonal side passage."
                    ),
                )
            if cell_id in runtime_occupied:
                return DisplacementResult.deterministic(
                    completed=False,
                    traversed_cells=tuple(traversed),
                    blocked_cell=cell_id,
                    failure=DisplacementBlockReason.OCCUPIED,
                    explanation="Forced displacement stops immediately before an occupied cell.",
                )
            for side_cell_id in side_cell_ids:
                if side_cell_id in runtime_occupied:
                    return DisplacementResult.deterministic(
                        completed=False,
                        traversed_cells=tuple(traversed),
                        blocked_cell=side_cell_id,
                        failure=DisplacementBlockReason.OCCUPIED,
                        explanation=(
                            "Forced displacement stops before a diagonal transition whose side passage is occupied."
                        ),
                    )

            traversed.append(cell_id)
            previous_cell = cell_id

        return DisplacementResult.deterministic(
            completed=True,
            traversed_cells=tuple(traversed),
            explanation="All requested forced-movement steps are statically legal and unoccupied.",
        )

    @staticmethod
    def _static_block_reason(
        cell: MapCellDefinition,
    ) -> DisplacementBlockReason | None:
        if not cell.walkable:
            return DisplacementBlockReason.STATIC_NOT_WALKABLE
        if cell.non_walkable_during_fight:
            return DisplacementBlockReason.NON_WALKABLE_DURING_FIGHT
        return None

    @staticmethod
    def _validate_adjacent_path(
        start_cell: CellId,
        candidate_cells: tuple[CellId, ...],
    ) -> None:
        previous = start_cell
        for cell_id in candidate_cells:
            valid_neighbors = {
                coordinate_to_cell(coordinate)
                for coordinate in neighbors8(cell_to_coordinate(previous))
            }
            if cell_id not in valid_neighbors:
                raise ValueError(
                    f"forced displacement path step {previous}->{cell_id} is not an adjacent Direction8 step"
                )
            previous = cell_id
