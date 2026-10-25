from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.ids import CellId
from anka_game_kernel.results.base import MechanicResult


@dataclass(frozen=True, slots=True)
class AoEResult(MechanicResult):
    center: CellId = CellId(0)
    cells: tuple[CellId, ...] = ()

    @classmethod
    def deterministic(cls, *, center: CellId, cells: tuple[CellId, ...]) -> "AoEResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            center=center,
            cells=cells,
        )
