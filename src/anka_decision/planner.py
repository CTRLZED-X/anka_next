"""Definitive M8 deterministic semantic planners.

Decision owns proposals only.  It never imports Windows/Protocol/Execution and
never emits pixels.  Kernel results are mechanics evidence, not input permits.
"""
from __future__ import annotations
from dataclasses import asdict
from hashlib import sha256
import json

from anka_decision.policies import order_proven_spells
from anka_contracts.decision import DecisionFrame,ActionPlan,PlannerResult

class DecisionPlanningError(ValueError):pass

def _canonical_target(target):
    return tuple(sorted((str(k),str(v)) for k,v in target))

def action_key(frame:DecisionFrame,kind:str,target:tuple[tuple[str,str],...])->str:
    obj={'run_id':frame.run_id,'account_id':frame.account_id,'fight_epoch':frame.fight_epoch,'turn_epoch':frame.turn_epoch,
         'snapshot_id':frame.snapshot_id,'snapshot_hash':frame.snapshot_semantic_sha256,'policy':frame.policy_profile,
         'kind':kind,'target':list(_canonical_target(target))}
    return sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def _plan(frame,kind,target,proofs):
    target=_canonical_target(target);key=action_key(frame,kind,target)
    pid='plan-'+sha256((frame.frame_id+':'+key).encode()).hexdigest()[:32]
    return ActionPlan(pid,key,kind,target,tuple(proofs),frame.snapshot_id,frame.canonical_cursor)

def frame_to_dict(frame:DecisionFrame)->dict:
    d=asdict(frame)
    for name in ('proof_statuses','available_spells'):
        d[name]=[list(x) for x in d[name]]
    for name in ('target_cells','candidate_move_cells','quarantined_action_keys'):d[name]=list(d[name])
    return d

def frame_from_dict(obj:dict)->DecisionFrame:
    d=dict(obj)
    for name in ('proof_statuses','available_spells'):d[name]=tuple(tuple(x) for x in d.get(name,()))
    for name in ('target_cells','candidate_move_cells','quarantined_action_keys'):d[name]=tuple(d.get(name,()))
    return DecisionFrame(**d)

def plan_to_dict(plan:ActionPlan)->dict:
    d=asdict(plan);d['semantic_target']=[list(x) for x in plan.semantic_target];d['expected_outcome_proofs']=list(plan.expected_outcome_proofs);return d

def plan_from_dict(obj:dict)->ActionPlan:
    d=dict(obj);d['semantic_target']=tuple(tuple(x) for x in d['semantic_target']);d['expected_outcome_proofs']=tuple(d['expected_outcome_proofs']);return ActionPlan(**d)

class DeterministicPlanner:
    """Small policy shell around the stable M8 contracts.

    The planner intentionally uses explicit frame-provided, proof-bearing inputs.
    More sophisticated legacy tactical scoring can be migrated behind this API
    without changing Workflow, Coordination or Execution.
    """
    def __init__(self,kernel_queries,policies=None,observer=None):self.kernel=kernel_queries;self.policies=dict(policies or {});self._observer=observer

    def _record(self,name:str,frame:DecisionFrame,**kwargs)->None:
        if self._observer is None:return
        kwargs.setdefault('account_id',frame.account_id);kwargs.setdefault('fight_epoch',frame.fight_epoch if frame.fight_epoch>0 else None);kwargs.setdefault('turn_epoch',frame.turn_epoch)
        try:self._observer.record(name,owner_system='anka_decision',**kwargs)
        except Exception:pass
    def _proofs(self,frame):return dict(frame.proof_statuses)
    def _wait(self,*evidence,reason):return PlannerResult('WAIT',required_evidence=tuple(dict.fromkeys(evidence)),reason=reason)

    def plan(self,frame:DecisionFrame)->PlannerResult:
        if not isinstance(frame,DecisionFrame):raise TypeError('DECISION_FRAME_REQUIRED')
        self._record('decision.frame_created',frame,boundary='decision.frame',canonical_cursor=frame.canonical_cursor,
                     payload={'frame_id':frame.frame_id,'workflow_goal':frame.workflow_goal,'snapshot_id':frame.snapshot_id,'snapshot_sha256':frame.snapshot_semantic_sha256,'proof_statuses':list(frame.proof_statuses)})
        goal=frame.workflow_goal.upper()
        if goal in ('FIGHT_TURN','COMBAT_TURN'):result=self._fight(frame)
        elif goal in ('PLACEMENT','FIGHT_PLACEMENT'):result=self._placement(frame)
        elif goal in ('WORLD_MOVE','PATROL_STEP'):result=self._world(frame)
        elif goal in ('FIGHT_ENTRY','START_FIGHT'):result=self._fight_entry(frame)
        elif goal in ('JOIN_FIGHT','PARTY_JOIN'):result=self._join_fight(frame)
        elif goal=='READY':result=self._simple(frame,'READY',(('phase','placement'),),('READY_OR_PHASE_CONFIRMED',))
        else:result=PlannerResult('NO_ACTION',reason='DECISION_WORKFLOW_GOAL_UNSUPPORTED')
        payload={'frame_id':frame.frame_id,'disposition':result.disposition,'reason':result.reason}
        if result.plan is not None:payload.update({'plan_id':result.plan.plan_id,'kind':result.plan.kind,'action_key':result.plan.action_key})
        if result.required_evidence:payload['required_evidence']=list(result.required_evidence)
        self._record('decision.plan_result',frame,boundary='decision.plan',failure_code=result.failure_code,payload=payload)
        return result

    def _required_known(self,frame,names):
        proofs=self._proofs(frame);missing=[]
        for name in names:
            if proofs.get(name)!='KNOWN':missing.append(name)
        return tuple(missing)

    def _simple(self,frame,kind,target,proofs):
        plan=_plan(frame,kind,target,proofs)
        if plan.action_key in frame.quarantined_action_keys:return PlannerResult('NO_ACTION',reason='DECISION_ACTION_KEY_QUARANTINED')
        return PlannerResult('PLAN',plan=plan)

    def _fight(self,frame):
        missing=self._required_known(frame,('fight_phase','turn_owner','actor_cell','ap','mp','loadout','targets'))
        if missing:return self._wait(*missing,reason='DECISION_REQUIRED_FIGHT_EVIDENCE_MISSING')
        if frame.actor_id is None or frame.turn_owner_id is None:return self._wait('actor_identity','turn_owner',reason='DECISION_ACTOR_OR_TURN_UNKNOWN')
        if frame.actor_id!=frame.turn_owner_id:return self._wait('turn_owner',reason='DECISION_NOT_ACTOR_TURN')
        if frame.ap is None or frame.mp is None or frame.actor_cell is None:return self._wait('actor_resources','actor_cell',reason='DECISION_REQUIRED_VALUE_MISSING')
        if not frame.available_spells:return self._wait('loadout',reason='DECISION_NO_PROVEN_AVAILABLE_SPELLS')
        if not frame.target_cells:return self._wait('targets',reason='DECISION_NO_PROVEN_TARGETS')
        steps=0;unknown=[];saw_legal_quarantined=False
        # Input order is explicit policy order. Old CRA/ENU priorities are retained
        # as provenance data; a current loadout must prove what is actually available.
        policy=self.policies.get(frame.policy_profile)
        if policy is not None and frame.class_id is not None and policy.class_id!=frame.class_id:
            return PlannerResult('FAULT',reason='DECISION_POLICY_CLASS_MISMATCH',failure_code='POLICY_CLASS_MISMATCH')
        for spell_id,grade in order_proven_spells(frame.available_spells,policy):
            for cell in frame.target_cells:
                steps+=1
                if steps>frame.budget_steps:return self._wait('planner_budget',reason='DECISION_BUDGET_EXHAUSTED')
                plan=_plan(frame,'CAST',(('spell_id',str(spell_id)),('grade',str(grade)),('target_cell',str(cell))),('SPELL_CAST_CONFIRMED','RESOURCE_DELTA_OR_TURN_PROGRESS'))
                verdict=self.kernel.validate_plan(frame,plan)
                if verdict.status=='ILLEGAL':continue
                if verdict.status=='INDETERMINATE':unknown.append(verdict.reason);continue
                if plan.action_key in frame.quarantined_action_keys:saw_legal_quarantined=True;continue
                return PlannerResult('PLAN',plan=plan)
        if unknown:return self._wait(*tuple(sorted(set(unknown))),reason='DECISION_KERNEL_INDETERMINATE')
        # A prior NOT_SENT plan must never spin forever on the same key. Safe turn
        # conclusion is semantic only here; Coordination/Execution still revalidate.
        end=_plan(frame,'END_TURN',(('actor_id',str(frame.actor_id)),),('TURN_OWNER_CHANGED',))
        if end.action_key not in frame.quarantined_action_keys:return PlannerResult('PLAN',plan=end)
        return PlannerResult('NO_ACTION',reason='DECISION_ALL_ACTION_KEYS_QUARANTINED' if saw_legal_quarantined else 'DECISION_NO_LEGAL_ACTION')

    def _placement(self,frame):
        missing=self._required_known(frame,('fight_phase','actor_cell'))
        if missing:return self._wait(*missing,reason='DECISION_PLACEMENT_EVIDENCE_MISSING')
        if not frame.candidate_move_cells:return PlannerResult('NO_ACTION',reason='DECISION_NO_PLACEMENT_CANDIDATE')
        unknown=[]
        for i,cell in enumerate(frame.candidate_move_cells,1):
            if i>frame.budget_steps:return self._wait('planner_budget',reason='DECISION_BUDGET_EXHAUSTED')
            
            if frame.map_id is None:return self._wait('fight_map',reason='DECISION_PLACEMENT_MAP_UNKNOWN')
            plan=_plan(frame,'MOVE',(('map_id',str(frame.map_id)),('target_cell',str(cell))),('ACTOR_CELL_CHANGED',))
            verdict=self.kernel.validate_plan(frame,plan)
            if verdict.status=='LEGAL' and plan.action_key not in frame.quarantined_action_keys:return PlannerResult('PLAN',plan=plan)
            if verdict.status=='INDETERMINATE':unknown.append(verdict.reason)
        if unknown:return self._wait(*tuple(sorted(set(unknown))),reason='DECISION_KERNEL_INDETERMINATE')
        return PlannerResult('NO_ACTION',reason='DECISION_NO_LEGAL_PLACEMENT')

    def _world(self,frame):
        missing=self._required_known(frame,('world_map','actor_cell'))
        if missing:return self._wait(*missing,reason='DECISION_WORLD_EVIDENCE_MISSING')
        if not frame.candidate_move_cells:return PlannerResult('NO_ACTION',reason='DECISION_NO_ROUTE_STEP')
        # World policy expresses a semantic route step only. Execution/Client own
        # projection/input and Workflow owns whether this step is still desired.
        target=[('target_cell',str(frame.candidate_move_cells[0]))]
        if frame.route_step is not None:target.append(('route_step',frame.route_step))
        plan=_plan(frame,'WORLD_MOVE',tuple(target),('WORLD_MAP_OR_CELL_CHANGED',))
        if plan.action_key in frame.quarantined_action_keys:return PlannerResult('NO_ACTION',reason='DECISION_ACTION_KEY_QUARANTINED')
        return PlannerResult('PLAN',plan=plan)

    def _fight_entry(self,frame):
        missing=self._required_known(frame,('world_map','actor_cell','encounter_target'))
        if missing:return self._wait(*missing,reason='DECISION_FIGHT_ENTRY_EVIDENCE_MISSING')
        if frame.encounter_id is None or frame.map_id is None:
            return self._wait('encounter_target',reason='DECISION_FIGHT_ENTRY_TARGET_UNKNOWN')
        target=(('encounter_id',frame.encounter_id),('map_id',str(frame.map_id)))
        return self._simple(frame,'START_FIGHT',target,('FIGHT_ENTRY_CONFIRMED',))

    def _join_fight(self,frame):
        missing=self._required_known(frame,('world_map','actor_cell','fight_identity','join_target'))
        if missing:return self._wait(*missing,reason='DECISION_JOIN_EVIDENCE_MISSING')
        if frame.target_fight_id is None or frame.target_fight_epoch is None:
            return self._wait('fight_identity','join_target',reason='DECISION_JOIN_TARGET_UNKNOWN')
        target=(('target_fight_id',frame.target_fight_id),('target_fight_epoch',str(frame.target_fight_epoch)))
        if frame.map_id is not None:target+=(('map_id',str(frame.map_id)),)
        return self._simple(frame,'JOIN_FIGHT',target,('FIGHT_JOIN_CONFIRMED',))
