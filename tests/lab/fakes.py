"""M1 fakes/virtual time/fault hooks for cross-system contract verification."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable

from anka_contracts.action import ActionCommand, ActionOutcome
from anka_contracts.client import ClientIdentity, ProjectionEvidence
from anka_contracts.decision import ActionPlan, DecisionFrame
from anka_contracts.mechanics import MechanicsResult
from anka_contracts.state import StateSnapshotIdentity


class VirtualClock:
    def __init__(self, start_ns: int = 0):
        if type(start_ns) is not int or start_ns < 0: raise ValueError('INVALID_VIRTUAL_CLOCK')
        self._now = start_ns
    def monotonic_ns(self) -> int: return self._now
    def advance_ns(self, amount: int) -> int:
        if type(amount) is not int or amount < 0: raise ValueError('INVALID_CLOCK_ADVANCE')
        self._now += amount; return self._now


class InjectedFault(RuntimeError): pass

class FaultInjector:
    def __init__(self, *points: str): self._points=set(points); self.hit=[]
    def __call__(self, point: str) -> None:
        self.hit.append(point)
        if point in self._points: raise InjectedFault(point)


@dataclass
class FakeStateReader:
    snapshots: dict[str, StateSnapshotIdentity]
    calls: list[str] = field(default_factory=list)
    def current_snapshot(self, account_id: str) -> StateSnapshotIdentity:
        self.calls.append(account_id)
        return self.snapshots[account_id]


@dataclass
class FakeKernelQueries:
    result: MechanicsResult
    calls: list[tuple[DecisionFrame, ActionPlan]] = field(default_factory=list)
    def validate_plan(self, frame: DecisionFrame, plan: ActionPlan) -> MechanicsResult:
        self.calls.append((frame,plan)); return self.result


@dataclass
class FakeClientProjection:
    identities: dict[str, ClientIdentity]
    projections: dict[tuple[str,str,str], ProjectionEvidence]
    identity_calls: list[str] = field(default_factory=list)
    projection_calls: list[tuple[str,str,str]] = field(default_factory=list)
    def identity(self, account_id: str) -> ClientIdentity:
        self.identity_calls.append(account_id); return self.identities[account_id]
    def project(self, account_id: str, target_kind: str, target_identity: str) -> ProjectionEvidence:
        key=(account_id,target_kind,target_identity); self.projection_calls.append(key); return self.projections[key]


@dataclass
class FakeActionExecutor:
    outcome: ActionOutcome
    commands: list[ActionCommand] = field(default_factory=list)
    def submit(self, command: ActionCommand) -> ActionOutcome:
        self.commands.append(command); return self.outcome


class CountingInputDriver:
    """Verification-only fake; never imports or calls an OS input API."""
    def __init__(self, fault: Callable[[str],None] | None = None):
        self.calls=[]; self.fault=fault
    def send(self, operation: str, target: tuple[int,int] | None = None) -> str:
        if self.fault: self.fault('before_fake_send')
        self.calls.append((operation,target))
        if self.fault: self.fault('after_fake_send')
        return 'FAKE_ACCEPTED_NO_OS_INPUT'
