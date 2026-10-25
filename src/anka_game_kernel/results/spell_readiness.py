from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from anka_game_kernel.domain.ids import SpellId
from anka_game_kernel.domain.live_requirements import LiveRequirementKind
from anka_game_kernel.domain.spell_effects import SpellEffectBranch
from anka_game_kernel.results.base import MechanicResult


class SpellReadinessBlocker(StrEnum):
    NO_MECHANICS = "no_mechanics"
    BRANCH_UNKNOWN = "branch_unknown"
    EFFECT_AREA_UNKNOWN = "effect_area_unknown"
    EFFECT_TARGET_UNKNOWN = "effect_target_unknown"
    UNRESOLVED_SEMANTICS = "unresolved_semantics"
    NON_IMMEDIATE_TRIGGER = "non_immediate_trigger"
    DELAYED_EFFECT = "delayed_effect"
    MECHANIC_UNREGISTERED = "mechanic_unregistered"
    RESOLVER_ADAPTER_UNSUPPORTED = "resolver_adapter_unsupported"
    LINE_OF_SIGHT_UNSUPPORTED = "line_of_sight_unsupported"
    MULTI_TARGET_DISPLACEMENT_UNSUPPORTED = "multi_target_displacement_unsupported"
    DISPLACEMENT_DIRECTION_UNSUPPORTED = "displacement_direction_unsupported"


@dataclass(frozen=True, slots=True)
class SpellGradeReadinessReport(MechanicResult):
    spell_id: SpellId | None = None
    grade: int | None = None
    branch: SpellEffectBranch = SpellEffectBranch.NORMAL
    effect_count: int | None = None
    structurally_ready: bool = False
    projection_ready: bool = False
    live_requirements: tuple[LiveRequirementKind, ...] = ()
    unsupported_blockers: tuple[SpellReadinessBlocker, ...] = ()
    unknown_blockers: tuple[SpellReadinessBlocker, ...] = ()
    # Compatibility field retained for R7/R8 callers. Under V2 it mirrors
    # projection_ready; live-authoritative results do not make it false.
    prediction_ready: bool = False
    blockers: tuple[SpellReadinessBlocker, ...] = ()
