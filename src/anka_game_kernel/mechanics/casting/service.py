from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.mechanics.casting.model import (
    CastAvailabilityContext,
    CastAvailabilitySpec,
)
from anka_game_kernel.results.casting import (
    CastAvailabilityFailureReason,
    CastAvailabilityResult,
)


@dataclass(frozen=True, slots=True)
class CastAvailabilityService:
    def evaluate(
        self,
        spec: CastAvailabilitySpec,
        context: CastAvailabilityContext,
    ) -> CastAvailabilityResult:
        if spec.ap_cost > 0 and context.current_ap is not None and spec.ap_cost > context.current_ap:
            return CastAvailabilityResult.deterministic(
                legal=False,
                failure=CastAvailabilityFailureReason.NOT_ENOUGH_AP,
                cooldown_remaining=context.cooldown_remaining,
                explanation="The caster does not have enough AP for the cast.",
            )
        if (
            spec.max_cast_per_turn > 0
            and context.casts_this_turn is not None
            and context.casts_this_turn >= spec.max_cast_per_turn
        ):
            return CastAvailabilityResult.deterministic(
                legal=False,
                failure=CastAvailabilityFailureReason.MAX_CASTS_PER_TURN,
                cooldown_remaining=context.cooldown_remaining,
                explanation="The spell has reached its positive per-turn cast limit.",
            )
        if (
            spec.max_global_cast_per_turn > 0
            and context.global_casts_this_turn is not None
            and context.global_casts_this_turn >= spec.max_global_cast_per_turn
        ):
            return CastAvailabilityResult.deterministic(
                legal=False,
                failure=CastAvailabilityFailureReason.MAX_GLOBAL_CASTS_PER_TURN,
                cooldown_remaining=context.cooldown_remaining,
                explanation="The spell has reached its positive global-turn cast limit.",
            )
        if context.cooldown_remaining is not None and context.cooldown_remaining > 0:
            return CastAvailabilityResult.deterministic(
                legal=False,
                failure=CastAvailabilityFailureReason.COOLDOWN_ACTIVE,
                cooldown_remaining=context.cooldown_remaining,
                explanation="The spell has a positive cooldown remaining.",
            )
        if (
            spec.max_cast_per_target > 0
            and context.target_id is not None
            and context.casts_on_target_this_turn is not None
            and context.casts_on_target_this_turn >= spec.max_cast_per_target
        ):
            return CastAvailabilityResult.deterministic(
                legal=False,
                failure=CastAvailabilityFailureReason.MAX_CASTS_PER_TARGET,
                cooldown_remaining=context.cooldown_remaining,
                explanation="The spell has reached its positive per-target cast limit.",
            )
        if (
            spec.state_criterion is not None
            and context.active_state_ids is not None
            and not spec.state_criterion.evaluate(context.active_state_ids)
        ):
            return CastAvailabilityResult.deterministic(
                legal=False,
                failure=CastAvailabilityFailureReason.STATE_CRITERION_FAILED,
                cooldown_remaining=context.cooldown_remaining,
                explanation="The caster's active states do not satisfy the spell state criterion.",
            )

        if (
            spec.requires_summon_slot
            and context.summon_slots_remaining is not None
            and context.summon_slots_remaining == 0
        ):
            return CastAvailabilityResult.deterministic(
                legal=False,
                failure=CastAvailabilityFailureReason.NO_SUMMON_SLOT,
                cooldown_remaining=context.cooldown_remaining,
                explanation="The cast requires a summon slot, but none remains.",
            )

        missing_inputs: list[str] = []
        if spec.ap_cost > 0 and context.current_ap is None:
            missing_inputs.append("current_ap")
        if spec.max_cast_per_turn > 0 and context.casts_this_turn is None:
            missing_inputs.append("casts_this_turn")
        if spec.max_global_cast_per_turn > 0 and context.global_casts_this_turn is None:
            missing_inputs.append("global_casts_this_turn")
        if context.cooldown_remaining is None:
            missing_inputs.append("cooldown_remaining")
        if (
            spec.max_cast_per_target > 0
            and context.target_id is not None
            and context.casts_on_target_this_turn is None
        ):
            missing_inputs.append("casts_on_target_this_turn")
        if spec.state_criterion is not None and context.active_state_ids is None:
            missing_inputs.append("active_state_ids")
        if spec.requires_summon_slot and context.summon_slots_remaining is None:
            missing_inputs.append("summon_slots_remaining")
        if missing_inputs:
            return CastAvailabilityResult.incomplete(
                missing_inputs=tuple(missing_inputs),
                explanation="Cast availability requires the missing runtime snapshot values.",
            )

        return CastAvailabilityResult.deterministic(
            legal=True,
            cooldown_remaining=context.cooldown_remaining,
            explanation="All evaluated cast-availability constraints are satisfied.",
        )

    @staticmethod
    def initial_cooldown(spec: CastAvailabilitySpec) -> int:
        return spec.initial_cooldown

    @staticmethod
    def cooldown_after_cast(spec: CastAvailabilitySpec) -> int:
        return spec.min_cast_interval

    @staticmethod
    def cooldown_after_turn(cooldown_remaining: int) -> int:
        if cooldown_remaining < 0:
            raise ValueError("cooldown_remaining cannot be negative")
        return max(0, cooldown_remaining - 1)
