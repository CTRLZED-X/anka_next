from __future__ import annotations

from dataclasses import dataclass, field

from anka_game_kernel.domain.ids import StateId


@dataclass(frozen=True, slots=True)
class StateTransitionSpec:
    apply: frozenset[StateId] = field(default_factory=frozenset)
    remove: frozenset[StateId] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if any(not isinstance(state_id, StateId) for state_id in self.apply):
            raise TypeError("apply must contain only StateId values")
        if any(not isinstance(state_id, StateId) for state_id in self.remove):
            raise TypeError("remove must contain only StateId values")
        overlap = self.apply & self.remove
        if overlap:
            raise ValueError("a state cannot be present in both apply and remove")
