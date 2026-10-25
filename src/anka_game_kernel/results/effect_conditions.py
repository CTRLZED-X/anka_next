from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.results.base import MechanicResult


@dataclass(frozen=True, slots=True)
class EffectConditionResult(MechanicResult):
    matches: bool | None = None
