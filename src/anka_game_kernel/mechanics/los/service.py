from __future__ import annotations

from dataclasses import dataclass
from math import hypot, inf
from typing import AbstractSet

from anka_game_kernel.domain.ids import CellId
from anka_game_kernel.domain.maps import MapDefinition
from anka_game_kernel.mechanics.geometry import (
    GridCoordinate,
    cell_to_coordinate,
    coordinate_to_cell,
)
from anka_game_kernel.results.los import LineOfSightResult


@dataclass(frozen=True, slots=True)
class LineOfSightService:
    """Dofus2 line-of-sight tracing on the canonical 560-cell grid.

    The trace mirrors the client Dofus2Line stepping algorithm: each cell is
    represented by its canonical integer (x, y) position, X/Y crossing agents
    advance toward the target, and ties advance both axes. The origin is
    excluded and the target is included.
    """

    _TIE_EPSILON = 0.0001

    def evaluate(
        self,
        map_definition: MapDefinition,
        origin: CellId,
        target: CellId,
        *,
        occupied_cells: AbstractSet[CellId] | None,
    ) -> LineOfSightResult:
        trace = self._dofus2_trace(origin, target)

        if not trace:
            return LineOfSightResult.deterministic(visible=True, trace=())

        cells_by_id = {cell.cell_id: cell for cell in map_definition.cells}

        if occupied_cells is None:
            for current in trace:
                current_definition = cells_by_id.get(current)
                if current_definition is None:
                    return LineOfSightResult.incomplete(
                        trace=trace,
                        missing_input=f"map.cells[{int(current)}]",
                    )
                if current_definition.blocks_line_of_sight:
                    return LineOfSightResult.deterministic(
                        visible=False,
                        trace=trace,
                        static_blocker=current,
                        explanation="A static map cell blocks line of sight.",
                    )
            if len(trace) <= 1:
                return LineOfSightResult.deterministic(visible=True, trace=trace)
            return LineOfSightResult.incomplete(
                trace=trace,
                missing_input="occupied_cells",
                explanation=(
                    "LoS geometry and static cells are known, but the runtime "
                    "occupancy snapshot is required for intermediate cells."
                ),
            )

        for index, current in enumerate(trace):
            if index > 0:
                previous = trace[index - 1]
                if previous in occupied_cells:
                    return LineOfSightResult.deterministic(
                        visible=False,
                        trace=trace,
                        occupied_blocker=previous,
                        explanation="A runtime entity blocks the traced line before the target.",
                    )

            current_definition = cells_by_id.get(current)
            if current_definition is None:
                return LineOfSightResult.incomplete(
                    trace=trace,
                    missing_input=f"map.cells[{int(current)}]",
                )

            if current_definition.blocks_line_of_sight:
                return LineOfSightResult.deterministic(
                    visible=False,
                    trace=trace,
                    static_blocker=current,
                    explanation="A static map cell blocks line of sight.",
                )

        return LineOfSightResult.deterministic(visible=True, trace=trace)

    @classmethod
    def _dofus2_trace(
        cls,
        origin: CellId,
        target: CellId,
    ) -> tuple[CellId, ...]:
        if origin == target:
            return ()

        start = cell_to_coordinate(origin)
        end = cell_to_coordinate(target)
        current_x = start.x
        current_y = start.y

        delta_x = end.x - start.x
        delta_y = end.y - start.y
        distance = hypot(delta_x, delta_y)

        x_step = inf if delta_x == 0 else distance / abs(delta_x)
        y_step = inf if delta_y == 0 else distance / abs(delta_y)
        x_agent = x_step / 2.0
        y_agent = y_step / 2.0
        x_sign = -1 if end.x < start.x else 1
        y_sign = -1 if end.y < start.y else 1

        trace: list[CellId] = []
        while current_x != end.x or current_y != end.y:
            if abs(x_agent - y_agent) < cls._TIE_EPSILON:
                x_agent += x_step
                y_agent += y_step
                current_x += x_sign
                current_y += y_sign
            elif x_agent < y_agent:
                x_agent += x_step
                current_x += x_sign
            else:
                y_agent += y_step
                current_y += y_sign

            trace.append(
                coordinate_to_cell(GridCoordinate(current_x, current_y))
            )

        return tuple(trace)
