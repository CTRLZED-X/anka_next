"""Canonical Dofus cell-grid geometry."""

from anka_game_kernel.mechanics.geometry.directions import Direction8
from anka_game_kernel.mechanics.geometry.grid import (
    MAP_CELL_COUNT,
    MAP_HEIGHT,
    MAP_WIDTH,
    GridCoordinate,
    adjacent_cells,
    are_aligned,
    are_diagonally_aligned,
    cell_distance,
    cell_to_coordinate,
    direction8_between,
    coordinate_to_cell,
    is_in_map,
    neighbor,
    neighbors8,
    point_symmetry,
    transition_side_cells,
)

__all__ = [
    "Direction8",
    "GridCoordinate",
    "MAP_CELL_COUNT",
    "MAP_HEIGHT",
    "MAP_WIDTH",
    "adjacent_cells",
    "are_aligned",
    "are_diagonally_aligned",
    "cell_distance",
    "cell_to_coordinate",
    "direction8_between",
    "coordinate_to_cell",
    "is_in_map",
    "neighbor",
    "neighbors8",
    "point_symmetry",
    "transition_side_cells",
]
