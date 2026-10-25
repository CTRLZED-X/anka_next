from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from anka_game_kernel.domain.ids import CellId
from anka_game_kernel.domain.maps import MapCellDefinition, MapDefinition
from anka_game_kernel.mechanics.geometry.grid import (
    MAP_CELL_COUNT,
    adjacent_cells,
    cell_to_coordinate,
    coordinate_to_cell,
)
from anka_game_kernel.mechanics.movement.model import MovementFailureReason, ReachableCell
from anka_game_kernel.results.movement import MovementResult, ReachableCellsResult


@dataclass(frozen=True, slots=True)
class MovementService:
    """Pure fight-grid path primitives.

    This layer models only canonical four-neighbor movement, static fight
    walkability, and caller-supplied occupancy. It intentionally does not model
    tackle/lock, MP budgets, portals, forced movement, or strategy.
    """

    def shortest_path(
        self,
        map_definition: MapDefinition,
        start_cell: CellId,
        target_cell: CellId,
        *,
        occupied_cells: frozenset[CellId] | None,
        avoid_cells: frozenset[CellId] = frozenset(),
    ) -> MovementResult:
        cells_by_id = {cell.cell_id: cell for cell in map_definition.cells}

        if start_cell not in cells_by_id:
            return MovementResult.incomplete(
                missing_input=f"map_cell:{start_cell}",
                explanation="Movement requires the start cell's static map definition.",
            )
        target_definition = cells_by_id.get(target_cell)
        if target_definition is None:
            return MovementResult.incomplete(
                missing_input=f"map_cell:{target_cell}",
                explanation="Movement requires the target cell's static map definition.",
            )

        if start_cell == target_cell:
            return MovementResult.deterministic(
                reachable=True,
                path=(start_cell,),
                explanation="Start and target are the same cell; no movement is required.",
            )

        target_failure = self._target_failure(target_definition)
        if target_failure is not None:
            return MovementResult.deterministic(
                reachable=False,
                failure=target_failure,
                explanation="The target cell is statically illegal for fight movement.",
            )

        if occupied_cells is None:
            return MovementResult.incomplete(
                missing_input="occupied_cells",
                explanation="Path evaluation requires the runtime occupancy snapshot.",
            )
        if target_cell in occupied_cells:
            return MovementResult.deterministic(
                reachable=False,
                failure=MovementFailureReason.TARGET_OCCUPIED,
                explanation="The target cell is occupied by another runtime actor.",
            )

        blocked_cells = (occupied_cells | avoid_cells) - frozenset({start_cell})
        path = self._bfs(
            cells_by_id,
            start_cell,
            target_cell,
            occupied_cells=blocked_cells,
        )
        if path is not None:
            return MovementResult.deterministic(
                reachable=True,
                path=path,
                explanation="A shortest path exists through canonical fight-walkable cells.",
            )

        if len(cells_by_id) < MAP_CELL_COUNT:
            return MovementResult.incomplete(
                missing_input="complete_map_cells",
                explanation=(
                    "No path exists in the supplied subset, but omitted map cells prevent "
                    "a deterministic no-path conclusion."
                ),
            )

        return MovementResult.deterministic(
            reachable=False,
            failure=MovementFailureReason.NO_PATH,
            explanation="No path exists through canonical fight-walkable, unoccupied cells.",
        )

    def reachable_cells(
        self,
        map_definition: MapDefinition,
        start_cell: CellId,
        *,
        max_steps: int,
        occupied_cells: frozenset[CellId] | None,
    ) -> ReachableCellsResult:
        if isinstance(max_steps, bool) or not isinstance(max_steps, int):
            raise TypeError("max_steps must be an int")
        if max_steps < 0:
            raise ValueError("max_steps cannot be negative")

        cells_by_id = {cell.cell_id: cell for cell in map_definition.cells}
        if start_cell not in cells_by_id:
            return ReachableCellsResult.incomplete(
                missing_input=f"map_cell:{start_cell}",
                explanation="Reachable-cell evaluation requires the start cell's static definition.",
            )

        if max_steps == 0:
            return ReachableCellsResult.deterministic(
                (ReachableCell(distance=0, cell_id=start_cell),),
                explanation="A zero-step movement budget reaches only the origin cell.",
            )

        if occupied_cells is None:
            return ReachableCellsResult.incomplete(
                missing_input="occupied_cells",
                explanation="Reachable-cell evaluation requires the runtime occupancy snapshot.",
            )

        if len(cells_by_id) < MAP_CELL_COUNT:
            return ReachableCellsResult.incomplete(
                missing_input="complete_map_cells",
                explanation="A complete map definition is required to prove the full reachable-cell set.",
            )

        blocked_cells = occupied_cells - frozenset({start_cell})
        queue: deque[CellId] = deque((start_cell,))
        distance: dict[CellId, int] = {start_cell: 0}

        while queue:
            current = queue.popleft()
            current_distance = distance[current]
            if current_distance >= max_steps:
                continue
            for neighbor_coordinate in adjacent_cells(cell_to_coordinate(current)):
                neighbor_cell = coordinate_to_cell(neighbor_coordinate)
                if neighbor_cell in distance:
                    continue
                neighbor_definition = cells_by_id.get(neighbor_cell)
                if neighbor_definition is None:
                    continue
                if not self._can_enter(neighbor_definition, blocked_cells):
                    continue
                distance[neighbor_cell] = current_distance + 1
                queue.append(neighbor_cell)

        reachable = tuple(
            ReachableCell(distance=steps, cell_id=cell_id)
            for cell_id, steps in sorted(distance.items(), key=lambda item: (item[1], int(item[0])))
        )
        return ReachableCellsResult.deterministic(
            reachable,
            explanation="Cells are reachable within the supplied canonical movement-step budget.",
        )

    @staticmethod
    def _target_failure(cell: MapCellDefinition) -> MovementFailureReason | None:
        if not cell.walkable:
            return MovementFailureReason.TARGET_NOT_WALKABLE
        if cell.non_walkable_during_fight:
            return MovementFailureReason.TARGET_NON_WALKABLE_DURING_FIGHT
        return None

    @staticmethod
    def _can_enter(cell: MapCellDefinition, occupied_cells: frozenset[CellId]) -> bool:
        return (
            cell.walkable
            and not cell.non_walkable_during_fight
            and cell.cell_id not in occupied_cells
        )

    def _bfs(
        self,
        cells_by_id: dict[CellId, MapCellDefinition],
        start_cell: CellId,
        target_cell: CellId,
        *,
        occupied_cells: frozenset[CellId],
    ) -> tuple[CellId, ...] | None:
        queue: deque[CellId] = deque((start_cell,))
        previous: dict[CellId, CellId | None] = {start_cell: None}

        while queue:
            current = queue.popleft()
            for neighbor_coordinate in adjacent_cells(cell_to_coordinate(current)):
                neighbor_cell = coordinate_to_cell(neighbor_coordinate)
                if neighbor_cell in previous:
                    continue
                neighbor_definition = cells_by_id.get(neighbor_cell)
                if neighbor_definition is None:
                    continue
                if not self._can_enter(neighbor_definition, occupied_cells):
                    continue

                previous[neighbor_cell] = current
                if neighbor_cell == target_cell:
                    return self._reconstruct(previous, target_cell)
                queue.append(neighbor_cell)

        return None

    @staticmethod
    def _reconstruct(
        previous: dict[CellId, CellId | None],
        target_cell: CellId,
    ) -> tuple[CellId, ...]:
        path: list[CellId] = []
        current: CellId | None = target_cell
        while current is not None:
            path.append(current)
            current = previous[current]
        path.reverse()
        return tuple(path)
