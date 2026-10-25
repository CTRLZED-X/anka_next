"""M11 deterministic no-OS-input driver and typed external-boundary failures."""
from __future__ import annotations
from anka_contracts.action import ActionCommand
from anka_contracts.execution import DriverSendReceipt,ExecutionClientAttestation,InputLease

class InputDriverFailure(RuntimeError):
    def __init__(self,code:str,*,may_have_sent:bool):super().__init__(code);self.code=code;self.may_have_sent=may_have_sent

class FakePhysicalInputDriver:
    """Executes the production driver contract without any OS input."""
    mode='FAKE_ONLY'
    CASES=frozenset({'sent','not-sent','raise-before','raise-after','may-have-sent','guard-twice'})
    def __init__(self,scenario='sent'):
        if scenario not in self.CASES:raise ValueError('UNKNOWN_FAKE_DRIVER_SCENARIO')
        self.scenario=scenario;self.call_count=0;self.action_ids=[]
    def send(self,command:ActionCommand,client:ExecutionClientAttestation,lease:InputLease,guard):
        if not guard():return DriverSendReceipt(command.action_id,'NOT_SENT',0,'FINAL_GUARD_REJECTED_BEFORE_FAKE_SEND')
        self.call_count+=1;self.action_ids.append(command.action_id)
        if self.scenario=='raise-before':raise InputDriverFailure('FAKE_DRIVER_PROVEN_BEFORE_SEND',may_have_sent=False)
        if self.scenario=='not-sent':return DriverSendReceipt(command.action_id,'NOT_SENT',0,'FAKE_PROVEN_NOT_SENT')
        if self.scenario=='guard-twice' and not guard():return DriverSendReceipt(command.action_id,'NOT_SENT',0,'MID_PATH_GUARD_REJECTED_BEFORE_SEND')
        if self.scenario=='raise-after':raise InputDriverFailure('FAKE_DRIVER_FAILURE_AFTER_POSSIBLE_SEND',may_have_sent=True)
        if self.scenario=='may-have-sent':return DriverSendReceipt(command.action_id,'MAY_HAVE_SENT',0,'FAKE_AMBIGUOUS_BOUNDARY')
        return DriverSendReceipt(command.action_id,'SENT',0,'FAKE_SEND_ACCEPTED')
