from typing import Protocol
from anka_contracts.decision import DecisionFrame, PlannerResult
class DecisionPlanner(Protocol):
    def plan(self, frame: DecisionFrame) -> PlannerResult: ...
