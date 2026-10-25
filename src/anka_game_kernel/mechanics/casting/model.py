from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.ids import StateId
from anka_game_kernel.domain.state_criteria import StateCriterion


@dataclass(frozen=True, slots=True)
class CastAvailabilitySpec:
    ap_cost: int
    max_cast_per_turn: int = 0
    max_global_cast_per_turn: int = 0
    max_cast_per_target: int = 0
    min_cast_interval: int = 0
    initial_cooldown: int = 0
    state_criterion: StateCriterion | None = None
    requires_summon_slot: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("ap_cost", self.ap_cost),
            ("max_cast_per_turn", self.max_cast_per_turn),
            ("max_global_cast_per_turn", self.max_global_cast_per_turn),
            ("max_cast_per_target", self.max_cast_per_target),
            ("min_cast_interval", self.min_cast_interval),
            ("initial_cooldown", self.initial_cooldown),
        ):
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.state_criterion is not None and not isinstance(self.state_criterion, StateCriterion):
            raise TypeError("state_criterion must be a canonical StateCriterion or None")


@dataclass(frozen=True, slots=True)
class CastAvailabilityContext:
    current_ap: int | None
    casts_this_turn: int | None
    cooldown_remaining: int | None
    global_casts_this_turn: int | None = None
    target_id: int | None = None
    casts_on_target_this_turn: int | None = None
    active_state_ids: frozenset[StateId] | None = None
    summon_slots_remaining: int | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("current_ap", self.current_ap),
            ("casts_this_turn", self.casts_this_turn),
            ("cooldown_remaining", self.cooldown_remaining),
            ("global_casts_this_turn", self.global_casts_this_turn),
            ("casts_on_target_this_turn", self.casts_on_target_this_turn),
            ("summon_slots_remaining", self.summon_slots_remaining),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.active_state_ids is not None:
            if not isinstance(self.active_state_ids, frozenset):
                raise TypeError("active_state_ids must be a frozenset of StateId values")
            if any(not isinstance(state_id, StateId) for state_id in self.active_state_ids):
                raise TypeError("active_state_ids must contain only StateId values")
