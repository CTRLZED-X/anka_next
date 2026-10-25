from __future__ import annotations

from dataclasses import dataclass, field

from anka_game_kernel.domain.ids import CellId
from anka_game_kernel.mechanics.aoe.model import AreaShape, AreaSpec
from anka_game_kernel.mechanics.geometry import GridCoordinate
from anka_game_kernel.mechanics.geometry.service import GeometryService
from anka_game_kernel.mechanics.geometry.grid import MAP_CELL_COUNT
from anka_game_kernel.results.aoe import AoEResult


@dataclass(frozen=True, slots=True)
class AoEService:
    """Pure canonical area-of-effect geometry, including verified directional shapes."""

    geometry: GeometryService = field(default_factory=GeometryService)

    def cells(
        self,
        center: CellId,
        spec: AreaSpec,
        *,
        origin: CellId | None = None,
    ) -> AoEResult:
        if spec.shape is AreaShape.GLOBAL:
            return AoEResult.deterministic(
                center=center,
                cells=tuple(CellId(raw) for raw in range(MAP_CELL_COUNT)),
            )

        if spec.shape is AreaShape.OUTSIDE_LOZENGE:
            center_coord = self.geometry.cell_to_coordinate(center)
            excluded = self._lozenge(center_coord, spec.min_radius, spec.radius)
            excluded_cells = {self.geometry.coordinate_to_cell(coord) for coord in excluded}
            return AoEResult.deterministic(
                center=center,
                cells=tuple(
                    CellId(raw) for raw in range(MAP_CELL_COUNT) if CellId(raw) not in excluded_cells
                ),
            )

        center_coord = self.geometry.cell_to_coordinate(center)
        origin_coord = None if origin is None else self.geometry.cell_to_coordinate(origin)
        coordinates = self._coordinates(center_coord, spec, origin=origin_coord)
        cell_ids = tuple(
            sorted(
                (self.geometry.coordinate_to_cell(coord) for coord in coordinates),
                key=int,
            )
        )
        return AoEResult.deterministic(center=center, cells=cell_ids)

    def _coordinates(
        self,
        center: GridCoordinate,
        spec: AreaSpec,
        *,
        origin: GridCoordinate | None = None,
    ) -> set[GridCoordinate]:
        if spec.shape is AreaShape.POINT:
            return {center}
        if spec.shape is AreaShape.LOZENGE:
            return self._lozenge(center, spec.min_radius, spec.radius)
        if spec.shape is AreaShape.SQUARE:
            return self._square(center, spec.min_radius, spec.radius)
        if spec.shape is AreaShape.CROSS:
            return self._cross(center, spec.min_radius, spec.radius, diagonal=False)
        if spec.shape is AreaShape.DIAGONAL:
            return self._cross(center, spec.min_radius, spec.radius, diagonal=True)
        if spec.shape is AreaShape.FORK:
            return self._fork(center, spec.min_radius, spec.radius, origin=origin)
        if spec.shape is AreaShape.CONE:
            return self._cone(center, spec.min_radius, spec.radius, origin=origin)
        if spec.shape is AreaShape.LINE:
            return self._line(center, spec.min_radius, spec.radius, origin=origin)
        raise AssertionError(f"unsupported area shape: {spec.shape}")


    def _line(
        self,
        center: GridCoordinate,
        min_radius: int,
        radius: int,
        *,
        origin: GridCoordinate | None,
    ) -> set[GridCoordinate]:
        """Directional Dofus line zone beginning on the selected cell.

        For ``LINE`` only, ``radius`` is the zone size in cells as shown by the
        client tooltip (for example ``ligne de 4 cases`` => radius=4). The line
        starts on ``center`` and extends directly away from ``origin``. This is
        intentionally distinct from cast-range line constraints.
        """
        if origin is None:
            raise ValueError("LINE area requires an origin cell")
        if origin == center:
            raise ValueError("LINE area origin must differ from center")
        if radius < 1:
            raise ValueError("LINE area size must be >= 1")

        if origin.x == center.x:
            forward = (0, 1 if center.y > origin.y else -1)
        elif origin.y == center.y:
            forward = (1 if center.x > origin.x else -1, 0)
        else:
            raise ValueError("LINE area origin and center must be canonically aligned")

        result: set[GridCoordinate] = set()
        first_index = max(0, min_radius)
        for index in range(first_index, radius):
            self._add_if_in_map(
                GridCoordinate(center.x + forward[0] * index, center.y + forward[1] * index),
                result,
            )
        return result

    def _cone(
        self,
        center: GridCoordinate,
        min_radius: int,
        radius: int,
        *,
        origin: GridCoordinate | None,
    ) -> set[GridCoordinate]:
        """Canonical line-oriented cone expanding away from the cast origin.

        At depth d from the selected center, the row is 2*d+1 cells wide.
        This matches the in-game size-2 cone used by Flèche Ralentissante.
        """
        if origin is None:
            raise ValueError("CONE area requires an origin cell")
        if origin == center:
            raise ValueError("CONE area origin must differ from center")

        if origin.x == center.x:
            forward = (0, 1 if center.y > origin.y else -1)
            side = (1, 0)
        elif origin.y == center.y:
            forward = (1 if center.x > origin.x else -1, 0)
            side = (0, 1)
        else:
            raise ValueError("CONE area origin and center must be canonically aligned")

        result: set[GridCoordinate] = set()
        for depth in range(0, radius + 1):
            if depth < min_radius:
                continue
            base = GridCoordinate(
                center.x + forward[0] * depth,
                center.y + forward[1] * depth,
            )
            for lateral in range(-depth, depth + 1):
                self._add_if_in_map(
                    GridCoordinate(
                        base.x + side[0] * lateral,
                        base.y + side[1] * lateral,
                    ),
                    result,
                )
        return result

    def _fork(
        self,
        center: GridCoordinate,
        min_radius: int,
        radius: int,
        *,
        origin: GridCoordinate | None,
    ) -> set[GridCoordinate]:
        """Dofus directional fork: selected cell plus three forward prongs.

        The client ``F`` zone is *not* a T shape.  Relative to the exact
        caster->selected-cell orientation, each depth contributes three cells
        that continue forward and fan one 45-degree sector to either side.
        This mirrors the client/SpellZone ``fillForkCells`` algorithm and is
        intentionally direction-sensitive.  ``min_radius`` is not used by the
        Dofus fork primitive; the selected center is always part of the zone.
        """
        if origin is None:
            raise ValueError("FORK area requires an origin cell")
        if origin == center:
            raise ValueError("FORK area origin must differ from center")
        if not (
            self.geometry.are_aligned(origin, center)
            or self.geometry.are_diagonally_aligned(origin, center)
        ):
            raise ValueError("FORK area origin and center must be exactly direction-aligned")

        # Dofus Direction8 ordering is shared by Kernel geometry and the client:
        # E, SE, S, SW, W, NW, N, NE.  Reproduce the reference fork formula
        # rather than deriving a perpendicular T, because the latter produced
        # false-positive impact cells in live fight 93 (R5.137).
        from anka_game_kernel.mechanics.geometry.grid import direction8_between

        direction = int(direction8_between(origin, center))
        sign = -1 if direction in {3, 5} else 1
        vertical_triplet = direction in {1, 5}

        result: set[GridCoordinate] = set()
        self._add_if_in_map(center, result)
        for step in range(1, radius + 1):
            if vertical_triplet:
                candidates = (
                    GridCoordinate(center.x + step * sign, center.y - step),
                    GridCoordinate(center.x + step * sign, center.y),
                    GridCoordinate(center.x + step * sign, center.y + step),
                )
            else:
                candidates = (
                    GridCoordinate(center.x - step, center.y + step * sign),
                    GridCoordinate(center.x, center.y + step * sign),
                    GridCoordinate(center.x + step, center.y + step * sign),
                )
            for candidate in candidates:
                self._add_if_in_map(candidate, result)
        return result

    def _square(
        self,
        center: GridCoordinate,
        min_radius: int,
        radius: int,
    ) -> set[GridCoordinate]:
        """Axis-aligned logical square using Chebyshev distance.

        Dofus tooltip ``carré de taille 1`` is the selected cell plus its
        eight immediate logical-grid neighbours (a 3x3 footprint).
        """
        result: set[GridCoordinate] = set()
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                distance = max(abs(dx), abs(dy))
                if distance < min_radius:
                    continue
                self._add_if_in_map(GridCoordinate(center.x + dx, center.y + dy), result)
        return result

    def _lozenge(
        self,
        center: GridCoordinate,
        min_radius: int,
        radius: int,
    ) -> set[GridCoordinate]:
        result: set[GridCoordinate] = set()
        for dx in range(-radius, radius + 1):
            remaining = radius - abs(dx)
            for dy in range(-remaining, remaining + 1):
                distance = abs(dx) + abs(dy)
                if distance < min_radius:
                    continue
                self._add_if_in_map(
                    GridCoordinate(center.x + dx, center.y + dy),
                    result,
                )
        return result

    def _cross(
        self,
        center: GridCoordinate,
        min_radius: int,
        radius: int,
        *,
        diagonal: bool,
    ) -> set[GridCoordinate]:
        result: set[GridCoordinate] = set()
        if min_radius == 0:
            result.add(center)

        for step in range(max(1, min_radius), radius + 1):
            if diagonal:
                offsets = (
                    (step, step),
                    (step, -step),
                    (-step, step),
                    (-step, -step),
                )
            else:
                offsets = (
                    (step, 0),
                    (-step, 0),
                    (0, step),
                    (0, -step),
                )
            for dx, dy in offsets:
                self._add_if_in_map(
                    GridCoordinate(center.x + dx, center.y + dy),
                    result,
                )
        return result

    def _add_if_in_map(
        self,
        coordinate: GridCoordinate,
        container: set[GridCoordinate],
    ) -> None:
        if self.geometry.is_in_map(coordinate):
            container.add(coordinate)
