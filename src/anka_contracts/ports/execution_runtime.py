"""Ports required by the definitive Execution authority."""
from __future__ import annotations
from typing import Callable,Protocol
from anka_contracts.action import ActionCommand
from anka_contracts.execution import ExecutionClientAttestation,ExecutionStateView,DriverSendReceipt,InputLease
from anka_contracts.mechanics import MechanicsResult

class LatestExecutionStatePort(Protocol):
    def current_for_action(self,command:ActionCommand)->ExecutionStateView: ...
class ExecutionClientPort(Protocol):
    def attest_for_action(self,command:ActionCommand)->ExecutionClientAttestation: ...
class ExecutionMechanicsPort(Protocol):
    def validate_action(self,command:ActionCommand,state:ExecutionStateView)->MechanicsResult: ...
class PhysicalInputDriverPort(Protocol):
    mode:str
    def send(self,command:ActionCommand,client:ExecutionClientAttestation,lease:InputLease,guard:Callable[[],bool])->DriverSendReceipt: ...
from anka_contracts.execution import ExecutionCoordinationPermit
class ExecutionCoordinationPort(Protocol):
    def permit_for_action(self,command:ActionCommand)->ExecutionCoordinationPermit: ...
