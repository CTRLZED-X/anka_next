from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AbstractSet
from dataclasses import dataclass

from anka_game_kernel.domain.ids import StateId


class StateCriterion(ABC):
    @abstractmethod
    def evaluate(self, active_state_ids: AbstractSet[StateId]) -> bool:
        """Evaluate this canonical criterion against caller-owned active states."""


@dataclass(frozen=True, slots=True)
class StatePresentCriterion(StateCriterion):
    state_id: StateId

    def evaluate(self, active_state_ids: AbstractSet[StateId]) -> bool:
        return self.state_id in active_state_ids


@dataclass(frozen=True, slots=True)
class StateAbsentCriterion(StateCriterion):
    state_id: StateId

    def evaluate(self, active_state_ids: AbstractSet[StateId]) -> bool:
        return self.state_id not in active_state_ids


@dataclass(frozen=True, slots=True)
class AllStateCriteria(StateCriterion):
    criteria: tuple[StateCriterion, ...]

    def __post_init__(self) -> None:
        if not self.criteria:
            raise ValueError("AllStateCriteria requires at least one criterion")

    def evaluate(self, active_state_ids: AbstractSet[StateId]) -> bool:
        return all(criterion.evaluate(active_state_ids) for criterion in self.criteria)


@dataclass(frozen=True, slots=True)
class AnyStateCriteria(StateCriterion):
    criteria: tuple[StateCriterion, ...]

    def __post_init__(self) -> None:
        if not self.criteria:
            raise ValueError("AnyStateCriteria requires at least one criterion")

    def evaluate(self, active_state_ids: AbstractSet[StateId]) -> bool:
        return any(criterion.evaluate(active_state_ids) for criterion in self.criteria)
