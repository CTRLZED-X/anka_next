from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from anka_game_kernel.domain.ids import CellId


class MovementFailureReason(StrEnum):
    TARGET_NOT_WALKABLE = "target_not_walkable"
    TARGET_NON_WALKABLE_DURING_FIGHT = "target_non_walkable_during_fight"
    TARGET_OCCUPIED = "target_occupied"
    NO_PATH = "no_path"


@dataclass(frozen=True, slots=True, order=True)
class ReachableCell:
    """A fight-walkable cell and its canonical shortest movement distance."""

    distance: int
    cell_id: CellId

    def __post_init__(self) -> None:
        if isinstance(self.distance, bool) or not isinstance(self.distance, int):
            raise TypeError("distance must be an int")
        if self.distance < 0:
            raise ValueError("distance cannot be negative")
