"""Small M1 producer/consumer contract walk using only verification fakes."""
from __future__ import annotations
from dataclasses import dataclass
from anka_contracts.action import ActionCommand, ActionOutcome
from anka_contracts.client import ClientIdentity, ProjectionEvidence
from anka_contracts.decision import ActionPlan, DecisionFrame
from anka_contracts.evidence import EvidencePointer
from anka_contracts.mechanics import MechanicsResult
from anka_contracts.state import FieldProof, StateSnapshotIdentity
from tests.lab.fakes import FakeStateReader, FakeKernelQueries, FakeClientProjection, FakeActionExecutor, CountingInputDriver

@dataclass(frozen=True, slots=True)
class ZeroInputStackResult:
    state_reads: int
    kernel_queries: int
    identity_reads: int
    projection_reads: int
    execution_submissions: int
    physical_input_count: int
    outcome_status: str

def run_zero_input_contract_stack() -> ZeroInputStackResult:
    evidence=EvidencePointer('evidence-zero-input','AUTHORITY_COMMITTED','anka_canonical','cursor:7','a'*64,'fight:2')
    snapshot=StateSnapshotIdentity('snap-zero','run-zero','acct-cra','client-cra',1,2,3,7,9,'b'*64,
        'historical-test-build','adapter-test','reducer-test','kernel-test','data-test','HEALTHY',
        (FieldProof('turn_owner','PROVEN',(evidence,),''),))
    frame=DecisionFrame('frame-zero','run-zero','acct-cra',2,3,'snap-zero',7,'FIGHT_PROGRESS')
    plan=ActionPlan('plan-zero','c'*64,'END_TURN',(),('NEXT_TURN_OWNER',),'snap-zero',7)
    command=ActionCommand('action-zero','run-zero','acct-cra','client-cra',2,3,'c'*64,'END_TURN',7,(),('NEXT_TURN_OWNER',),100)
    identity=ClientIdentity('client-cra','acct-cra',10,20,30,1,'PROVEN',9,'PROVEN',None,1280,649,96)
    projection=ProjectionEvidence('client-cra',1,None,1,'control','END_TURN',100,200,5,True)

    state=FakeStateReader({'acct-cra':snapshot})
    kernel=FakeKernelQueries(MechanicsResult('LEGAL'))
    client=FakeClientProjection({'acct-cra':identity},{('acct-cra','control','END_TURN'):projection})
    executor=FakeActionExecutor(ActionOutcome('action-zero',None,'REJECTED_NOT_SENT',(),True))
    driver=CountingInputDriver()

    assert state.current_snapshot('acct-cra').snapshot_id == frame.snapshot_id
    assert kernel.validate_plan(frame,plan).status == 'LEGAL'
    assert client.identity('acct-cra').window_generation == 1
    assert client.project('acct-cra','control','END_TURN').valid
    outcome=executor.submit(command)
    # The M1 stack intentionally never invokes the fake driver: it proves the
    # contracts can collaborate without accidentally creating an input authority.
    return ZeroInputStackResult(len(state.calls),len(kernel.calls),len(client.identity_calls),
        len(client.projection_calls),len(executor.commands),len(driver.calls),outcome.status)
