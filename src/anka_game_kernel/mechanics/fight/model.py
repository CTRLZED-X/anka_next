from __future__ import annotations

from dataclasses import dataclass, field

from anka_game_kernel.domain.ids import CellId
from anka_game_kernel.domain.maps import MapDefinition
from anka_game_kernel.mechanics.casting.model import (
    CastAvailabilityContext,
    CastAvailabilitySpec,
)
from anka_game_kernel.mechanics.range.model import RangeSpec
from anka_game_kernel.mechanics.targeting.model import TargetCellSpec


@dataclass(frozen=True, slots=True)
class CastEvaluationSpec:
    availability: CastAvailabilitySpec
    range: RangeSpec
    target_cell: TargetCellSpec = field(default_factory=TargetCellSpec)
    requires_line_of_sight: bool = True


@dataclass(frozen=True, slots=True)
class CastEvaluationContext:
    map_definition: MapDefinition
    caster_cell: CellId
    target_cell: CellId
    availability: CastAvailabilityContext
    range_bonus: int = 0
    # Conservative blocker occupancy; may include unknown-life actors.
    occupied_cells: frozenset[CellId] | None = None
    # Positive occupancy proof; only explicitly alive actors should be included.
    proven_occupied_cells: frozenset[CellId] | None = None

    def __post_init__(self) -> None:
        if self.occupied_cells is not None:
            if not isinstance(self.occupied_cells, frozenset):
                raise TypeError("occupied_cells must be a frozenset of CellId values or None")
            if any(not isinstance(cell_id, CellId) for cell_id in self.occupied_cells):
                raise TypeError("occupied_cells must contain only CellId values")
        if self.proven_occupied_cells is not None:
            if not isinstance(self.proven_occupied_cells, frozenset):
                raise TypeError("proven_occupied_cells must be a frozenset of CellId values or None")
            if any(not isinstance(cell_id, CellId) for cell_id in self.proven_occupied_cells):
                raise TypeError("proven_occupied_cells must contain only CellId values")
            if (
                self.occupied_cells is not None
                and not self.proven_occupied_cells.issubset(self.occupied_cells)
            ):
                raise ValueError("proven_occupied_cells must be a subset of occupied_cells when blocker occupancy is complete")
