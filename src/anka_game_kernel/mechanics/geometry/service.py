from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.ids import CellId
from anka_game_kernel.mechanics.geometry.directions import Direction8
from anka_game_kernel.mechanics.geometry.grid import (
    GridCoordinate,
    adjacent_cells,
    are_aligned,
    are_diagonally_aligned,
    cell_distance,
    cell_to_coordinate,
    coordinate_to_cell,
    is_in_map,
    neighbor,
    neighbors8,
    point_symmetry,
)


@dataclass(frozen=True, slots=True)
class GeometryService:
    """Stateless public facade delegating to the canonical geometry functions."""

    def cell_to_coordinate(self, cell_id: CellId) -> GridCoordinate:
        return cell_to_coordinate(cell_id)

    def coordinate_to_cell(self, coordinate: GridCoordinate) -> CellId:
        return coordinate_to_cell(coordinate)

    def is_in_map(self, coordinate: GridCoordinate) -> bool:
        return is_in_map(coordinate)

    def distance(self, first: GridCoordinate, second: GridCoordinate) -> int:
        return cell_distance(first, second)

    def neighbor(
        self,
        coordinate: GridCoordinate,
        direction: Direction8,
    ) -> GridCoordinate | None:
        return neighbor(coordinate, direction)

    def neighbors8(self, coordinate: GridCoordinate) -> tuple[GridCoordinate, ...]:
        return neighbors8(coordinate)

    def adjacent_cells(self, coordinate: GridCoordinate) -> tuple[GridCoordinate, ...]:
        return adjacent_cells(coordinate)

    def are_aligned(self, first: GridCoordinate, second: GridCoordinate) -> bool:
        return are_aligned(first, second)

    def are_diagonally_aligned(
        self,
        first: GridCoordinate,
        second: GridCoordinate,
    ) -> bool:
        return are_diagonally_aligned(first, second)

    def point_symmetry(
        self,
        point: GridCoordinate,
        center: GridCoordinate,
    ) -> GridCoordinate | None:
        return point_symmetry(point, center)
