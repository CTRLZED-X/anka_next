from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.contexts.projection import FightProjection
from anka_game_kernel.results.base import MechanicResult
from anka_game_kernel.results.movement import MovementResult


@dataclass(frozen=True, slots=True)
class MovementActionProjectionResult(MechanicResult):
    legal: bool | None = None
    projection_complete: bool = False
    movement: MovementResult | None = None
    projection: FightProjection | None = None
