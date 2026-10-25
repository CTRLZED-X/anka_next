from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.contexts.projection import FightProjection, ProjectionChange
from anka_game_kernel.domain.ids import ActorId, CellId
from anka_game_kernel.domain.live_requirements import LiveObservationRequirement
from anka_game_kernel.domain.spell_effects import SpellEffectOccurrence
from anka_game_kernel.mechanics.aoe.model import AreaSpec
from anka_game_kernel.results.base import MechanicResult


@dataclass(frozen=True, slots=True)
class EffectStepResult(MechanicResult):
    occurrence: SpellEffectOccurrence | None = None
    effective_area: AreaSpec | None = None
    affected_cells: tuple[CellId, ...] = ()
    eligible_actor_ids: tuple[ActorId, ...] = ()
    mechanic_results: tuple[MechanicResult, ...] = ()
    projection_changes: tuple[ProjectionChange, ...] = ()
    live_requirements: tuple[LiveObservationRequirement, ...] = ()


@dataclass(frozen=True, slots=True)
class EffectResolutionResult(MechanicResult):
    steps: tuple[EffectStepResult, ...] = ()
    projection: FightProjection | None = None
    live_requirements: tuple[LiveObservationRequirement, ...] = ()
