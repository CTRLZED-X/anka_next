from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.actors import ActorState
from anka_game_kernel.domain.ids import CellId
from anka_game_kernel.domain.spells import SpellGradeDefinition
from anka_game_kernel.mechanics.geometry.grid import (
    are_aligned,
    are_diagonally_aligned,
    cell_distance,
    cell_to_coordinate,
)
from anka_game_kernel.mechanics.range.model import RangeFailureReason, RangeSpec
from anka_game_kernel.results.range import RangeResult


@dataclass(frozen=True, slots=True)
class RangeService:
    """Pure spell-cast distance and alignment evaluator."""

    @staticmethod
    def resolve_bonus(
        actor: ActorState,
        grade: SpellGradeDefinition,
        explicit_range_bonus: int | None = None,
    ) -> int | None:
        """Resolve effective caller PO input without inventing missing live state."""
        if explicit_range_bonus is not None:
            if isinstance(explicit_range_bonus, bool) or not isinstance(explicit_range_bonus, int):
                raise TypeError("range_bonus must be an int or None")
            return explicit_range_bonus
        if not grade.range_modifiable:
            return 0
        if actor.combat_stats is None:
            return None
        return actor.combat_stats.range_bonus

    def evaluate(
        self,
        origin: CellId,
        target: CellId,
        spec: RangeSpec,
        *,
        range_bonus: int = 0,
    ) -> RangeResult:
        origin_coord = cell_to_coordinate(origin)
        target_coord = cell_to_coordinate(target)
        distance = cell_distance(origin_coord, target_coord)
        effective_max = spec.max_range
        if spec.modifiable:
            effective_max = max(spec.min_range, spec.max_range + range_bonus)

        if distance < spec.min_range:
            return RangeResult.deterministic(
                legal=False,
                distance=distance,
                effective_min_range=spec.min_range,
                effective_max_range=effective_max,
                failure=RangeFailureReason.MIN_RANGE,
            )
        if distance > effective_max:
            return RangeResult.deterministic(
                legal=False,
                distance=distance,
                effective_min_range=spec.min_range,
                effective_max_range=effective_max,
                failure=RangeFailureReason.MAX_RANGE,
            )

        aligned = are_aligned(origin_coord, target_coord)
        diagonal = are_diagonally_aligned(origin_coord, target_coord)

        if spec.cast_in_line and spec.cast_in_diagonal:
            if not (aligned or diagonal):
                return RangeResult.deterministic(
                    legal=False,
                    distance=distance,
                    effective_min_range=spec.min_range,
                    effective_max_range=effective_max,
                    failure=RangeFailureReason.NOT_IN_LINE_OR_DIAGONAL,
                )
        elif spec.cast_in_line and not aligned:
            return RangeResult.deterministic(
                legal=False,
                distance=distance,
                effective_min_range=spec.min_range,
                effective_max_range=effective_max,
                failure=RangeFailureReason.NOT_IN_LINE,
            )
        elif spec.cast_in_diagonal and not diagonal:
            return RangeResult.deterministic(
                legal=False,
                distance=distance,
                effective_min_range=spec.min_range,
                effective_max_range=effective_max,
                failure=RangeFailureReason.NOT_IN_DIAGONAL,
            )

        return RangeResult.deterministic(
            legal=True,
            distance=distance,
            effective_min_range=spec.min_range,
            effective_max_range=effective_max,
        )
