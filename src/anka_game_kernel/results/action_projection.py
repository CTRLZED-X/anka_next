from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.contexts.projection import FightProjection
from anka_game_kernel.domain.live_requirements import LiveObservationRequirement
from anka_game_kernel.results.base import MechanicResult
from anka_game_kernel.results.effect_resolution import EffectResolutionResult
from anka_game_kernel.results.fight import CastEvaluationResult


@dataclass(frozen=True, slots=True)
class CastActionProjectionResult(MechanicResult):
    legal: bool | None = None
    projection_complete: bool = False
    cast_evaluation: CastEvaluationResult | None = None
    projection: FightProjection | None = None
    effect_resolution: EffectResolutionResult | None = None
    live_requirements: tuple[LiveObservationRequirement, ...] = ()
