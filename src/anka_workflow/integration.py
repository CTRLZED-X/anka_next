"""Ports-only planning/execution integration used by Workflow and Q6 zero-input tests.

The controller plans before asking for authority.  This is intentional: actions that
create the first turn (placement/Ready) cannot depend on a combat turn permit.
Authorization is requested for the exact semantic scope selected by Decision and is
revalidated again by Execution immediately before the external boundary.
"""
from __future__ import annotations
from hashlib import sha256
from anka_contracts.action import ActionCommand
from anka_contracts.decision import DecisionFrame
from anka_contracts.ports.action_executor import ActionExecutor
from anka_contracts.ports.decision_planner import DecisionPlanner
from anka_contracts.ports.party_coordinator import PartyCoordinator
from anka_contracts.workflow import WorkflowActionDispatch


def _scope_for_plan(frame: DecisionFrame, kind: str) -> str:
    goal=frame.workflow_goal.upper()
    if kind in ('CAST','END_TURN'):
        return 'TURN'
    if kind=='MOVE':
        return 'PLACEMENT' if goal in ('PLACEMENT','FIGHT_PLACEMENT') else 'TURN'
    if kind=='READY':
        return 'READY'
    if kind=='JOIN_FIGHT':
        return 'JOIN'
    if kind=='WORLD_MOVE':
        return 'WORLD'
    if kind=='START_FIGHT':
        return 'FIGHT_ENTRY'
    raise ValueError('UNSUPPORTED_ACTION_AUTHORITY_SCOPE:'+kind)


class WorkflowTurnController:
    def __init__(self, planner: DecisionPlanner, executor: ActionExecutor, coordinator: PartyCoordinator, observer=None, authority=None):
        self._planner=planner;self._executor=executor;self._coord=coordinator;self._observer=observer;self._authority=authority or coordinator

    def _record(self,name:str,**kwargs)->None:
        if self._observer is None:return
        try:self._observer.record(name,owner_system='anka_workflow',**kwargs)
        except Exception:pass

    def _permit(self,party_id:str,frame:DecisionFrame,plan,scope:str):
        permit_for_plan=getattr(self._authority,'permit_for_plan',None)
        if callable(permit_for_plan):
            return permit_for_plan(party_id,frame,plan,scope)
        action_permit=getattr(self._authority,'action_permit',None)
        if callable(action_permit):
            return action_permit(party_id,frame.account_id,scope)
        # Backwards compatibility is safe only for the original TURN scope.
        if scope=='TURN':
            return self._coord.turn_permit(party_id,frame.account_id)
        return None

    def request(self, party_id:str, frame:DecisionFrame)->WorkflowActionDispatch:
        result=self._planner.plan(frame)
        if result.disposition=='WAIT':return WorkflowActionDispatch('WAIT',result.reason)
        if result.disposition=='NO_ACTION':return WorkflowActionDispatch('NO_ACTION',result.reason)
        if result.disposition=='FAULT':return WorkflowActionDispatch('FAULT',result.failure_code or result.reason)
        plan=result.plan
        assert plan is not None
        try:scope=_scope_for_plan(frame,plan.kind)
        except ValueError as exc:return WorkflowActionDispatch('FAULT',str(exc))

        def blocked(status:str,reason:str,severity='WARNING'):
            self._record('workflow.action_authorization_blocked',severity=severity,boundary='workflow.action_authorization',
                         failure_code=reason,account_id=frame.account_id,fight_epoch=frame.fight_epoch if frame.fight_epoch>0 else None,
                         turn_epoch=frame.turn_epoch,payload={'scope':scope,'kind':plan.kind,'workflow_goal':frame.workflow_goal,
                         'plan_id':plan.plan_id,'action_key':plan.action_key,'reason':reason})
            return WorkflowActionDispatch(status,reason)

        permit=self._permit(party_id,frame,plan,scope)
        if permit is None:
            return blocked('WAIT','COORDINATION_'+scope+'_AUTHORITY_UNAVAILABLE')
        if not permit.allowed:
            return blocked('WAIT','COORDINATION_'+permit.reason)
        if scope=='JOIN':
            try:target_epoch=int(dict(plan.semantic_target)['target_fight_epoch'])
            except (KeyError,TypeError,ValueError):return blocked('FAULT','JOIN_TARGET_FIGHT_EPOCH_INVALID','ERROR')
            if permit.fight_epoch!=target_epoch:
                return blocked('WAIT','COORDINATION_PERMIT_TARGET_FIGHT_EPOCH_MISMATCH')
        elif permit.fight_epoch!=frame.fight_epoch:
            return blocked('WAIT','COORDINATION_PERMIT_FIGHT_EPOCH_MISMATCH')
        if scope=='TURN' and permit.turn_epoch!=frame.turn_epoch:
            return blocked('WAIT','COORDINATION_PERMIT_TURN_EPOCH_MISMATCH')

        action_id='action-'+sha256((frame.run_id+plan.plan_id+plan.action_key).encode()).hexdigest()[:24]
        trace_id='trace-'+sha256((frame.run_id+frame.frame_id+action_id).encode()).hexdigest()[:24]
        self._record('workflow.action_requested',boundary='workflow.action_authorization',account_id=frame.account_id,
                     fight_epoch=frame.fight_epoch if frame.fight_epoch>0 else None,turn_epoch=frame.turn_epoch,trace_id=trace_id,action_id=action_id,
                     payload={'scope':scope,'kind':plan.kind,'workflow_goal':frame.workflow_goal,'plan_id':plan.plan_id,'action_key':plan.action_key})
        if scope=='READY':
            self._record('ready.requested',boundary='workflow.ready_request',account_id=frame.account_id,
                         fight_epoch=frame.fight_epoch,turn_epoch=frame.turn_epoch,trace_id=trace_id,action_id=action_id,
                         payload={'scope':scope,'plan_id':plan.plan_id,'action_key':plan.action_key})

        command=ActionCommand(action_id,frame.run_id,frame.account_id,frame.client_instance_id,frame.fight_epoch,frame.turn_epoch,
            plan.action_key,plan.kind,plan.basis_canonical_cursor,plan.semantic_target,plan.expected_outcome_proofs,
            basis_snapshot_id=frame.snapshot_id,party_id=party_id,basis_party_generation=permit.party_generation,
            basis_permit_generation=permit.permit_generation,actor_id=frame.actor_id,authority_scope=scope,trace_id=trace_id)
        outcome=self._executor.submit(command)
        self._record('workflow.action_dispatch_result',boundary='workflow.execution_dispatch',account_id=frame.account_id,
                     fight_epoch=frame.fight_epoch if frame.fight_epoch>0 else None,turn_epoch=frame.turn_epoch,trace_id=trace_id,action_id=action_id,
                     severity='SAFETY' if outcome.status in ('UNCERTAIN','TERMINAL_UNRESOLVED') else 'INFO',
                     failure_code=outcome.reason if outcome.status in ('UNCERTAIN','TERMINAL_UNRESOLVED','REJECTED_NOT_SENT') else None,
                     payload={'scope':scope,'kind':plan.kind,'outcome_status':outcome.status,'outcome_reason':outcome.reason,
                              'retry_eligible':outcome.retry_eligible,'evidence_ids':list(outcome.evidence_ids)})
        if outcome.action_id != action_id:
            return WorkflowActionDispatch('FAULT','EXECUTION_OUTCOME_ACTION_MISMATCH')
        return WorkflowActionDispatch('SUBMITTED','EXECUTION_OUTCOME_RETURNED',action_id,outcome.status,plan.action_key)
