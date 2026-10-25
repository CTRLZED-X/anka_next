"""Immutable P13 synthetic map-research contracts. Not an action/actuation protocol."""
from __future__ import annotations
from dataclasses import dataclass
from anka_contracts.decision import CastProbe


@dataclass(frozen=True, slots=True)
class MapResearchRequest:
    scope: CastProbe
    geometry_map_id: int
    target_cells: tuple[int, ...]
    movement_target_cell: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scope, CastProbe):
            raise TypeError('MAP_RESEARCH_CAST_SCOPE_REQUIRED')
        if type(self.geometry_map_id) is not int or self.geometry_map_id <= 0:
            raise ValueError('MAP_RESEARCH_MAP_ID_INVALID')
        if (not isinstance(self.target_cells, tuple) or not 1 <= len(self.target_cells) <= 16
            or any(type(cell) is not int or not 0 <= cell < 560 for cell in self.target_cells)
            or len(set(self.target_cells)) != len(self.target_cells)
            or self.scope.target_cell not in self.target_cells):
            raise ValueError('MAP_RESEARCH_TARGET_SET_INVALID')
        if self.movement_target_cell is not None and (
            type(self.movement_target_cell) is not int or not 0 <= self.movement_target_cell < 560
        ):
            raise ValueError('MAP_RESEARCH_MOVEMENT_TARGET_INVALID')


@dataclass(frozen=True, slots=True)
class MapResearchReport:
    status: str
    reasons: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    evaluated_cells: tuple[tuple[int, str, tuple[str, ...]], ...]
    reachable_cells: tuple[tuple[int, int], ...]
    movement_target_path: tuple[int, ...]
    movement_target_status: str
    # Required constants: impossible to reinterpret an offline probe as a permit.
    actionable: bool = False
    authoritative: bool = False
    preview_only: bool = True

    def to_dict(self) -> dict:
        return {
            'status': self.status, 'reasons': list(self.reasons),
            'missing_inputs': list(self.missing_inputs),
            'evaluated_cells': [
                {'cell_id': cell, 'kernel_legality': legality, 'details': list(details)}
                for cell, legality, details in self.evaluated_cells
            ],
            'reachable_cells': [{'cell_id': cell, 'steps': steps} for cell, steps in self.reachable_cells],
            'movement_target_path': list(self.movement_target_path),
            'movement_target_status': self.movement_target_status,
            'actionable': False, 'authoritative': False, 'preview_only': True,
            'physical_input_permitted': False,
        }
