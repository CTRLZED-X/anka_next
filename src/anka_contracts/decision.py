"""P12 immutable, non-executable decision PROBE contracts.

A preview cannot be passed as a physical-input command. No credential,
window address, mouse coordinate, input primitive or execution authority exists.
"""
from __future__ import annotations
from dataclasses import dataclass


def token(s: str) -> bool:
    return type(s) is str and 1 <= len(s) <= 100 and s.isascii() and all(
        c.isalnum() or c in '_.-' for c in s)


@dataclass(frozen=True, slots=True)
class CastProbe:
    session_id: str
    account_id: str
    account_generation: int
    fight_id: str
    minimum_revision: int
    actor_id: int
    spell_id: int
    grade: int
    target_cell: int

    def __post_init__(self) -> None:
        if not all(map(token,(self.session_id,self.account_id,self.fight_id))):
            raise ValueError('DECISION_SCOPE_INVALID')
        valid = (
            type(self.account_generation) is int and self.account_generation >= 0
            and type(self.minimum_revision) is int and self.minimum_revision >= 1
            and type(self.actor_id) is int and self.actor_id != 0 and abs(self.actor_id) < 2**63
            and type(self.spell_id) is int and self.spell_id > 0
            and type(self.grade) is int and 1 <= self.grade <= 10
            and type(self.target_cell) is int and 0 <= self.target_cell <= 100000
        )
        if not valid:raise ValueError('DECISION_PROBE_INVALID')


@dataclass(frozen=True, slots=True)
class CastProbeReport:
    status: str
    scope: CastProbe
    reasons: tuple[str, ...]
    missing_kernel_inputs: tuple[str, ...]
    observed_revision: int | None
    static_spell_name: str | None
    static_ap_cost: int | None
    kernel_legality: str
    # Contract deliberately has no physical-action fields or executable plan.
    preview_only: bool = True
    actionable: bool = False
    authoritative: bool = False

    def to_dict(self) -> dict:
        return {
            'status':self.status,'probe':{
                'session_id':self.scope.session_id,'account_id':self.scope.account_id,
                'account_generation':self.scope.account_generation,
                'fight_id':self.scope.fight_id,'minimum_revision':self.scope.minimum_revision,
                'actor_id':self.scope.actor_id,'spell_id':self.scope.spell_id,
                'grade':self.scope.grade,'target_cell':self.scope.target_cell},
            'reasons':list(self.reasons),'missing_kernel_inputs':list(self.missing_kernel_inputs),
            'observed_revision':self.observed_revision,'static_spell_name':self.static_spell_name,
            'static_ap_cost':self.static_ap_cost,'kernel_legality':self.kernel_legality,
            'preview_only':True,'actionable':False,'authoritative':False,
            'physical_input_permitted':False,
        }

# --- Definitive M1 planning contracts (additive) ---
from dataclasses import field as _field
from typing import Literal as _Literal

PlannerDisposition = _Literal['PLAN','WAIT','NO_ACTION','FAULT']

@dataclass(frozen=True, slots=True)
class DecisionFrame:
    frame_id: str
    run_id: str
    account_id: str
    fight_epoch: int
    turn_epoch: int
    snapshot_id: str
    canonical_cursor: int
    workflow_goal: str
    # M8 definitive planning context. Defaults preserve the earlier M1 codec.
    client_instance_id: str = ''
    snapshot_semantic_sha256: str = ''
    state_reducer_revision: str = ''
    kernel_ruleset_id: str = ''
    game_data_revision: str = ''
    policy_profile: str = ''
    class_id: int | None = None
    actor_id: int | None = None
    turn_owner_id: int | None = None
    actor_cell: int | None = None
    map_id: int | None = None
    ap: int | None = None
    mp: int | None = None
    proof_statuses: tuple[tuple[str,str], ...] = ()
    available_spells: tuple[tuple[int,int], ...] = ()
    target_cells: tuple[int, ...] = ()
    candidate_move_cells: tuple[int, ...] = ()
    quarantined_action_keys: tuple[str, ...] = ()
    deterministic_seed: int = 0
    budget_steps: int = 128
    # World/fight-entry intent is explicit so pre-fight commands do not overload
    # the current fight_epoch with a future target fight identity.
    route_step: str | None = None
    target_fight_id: str | None = None
    target_fight_epoch: int | None = None
    encounter_id: str | None = None

    def __post_init__(self):
        if not self.frame_id.startswith('frame-') or not self.run_id.startswith('run-') or not self.account_id.startswith('acct-') or not self.snapshot_id.startswith('snap-'):
            raise ValueError('INVALID_DECISION_FRAME_IDENTITY')
        if any(type(v) is not int or v < 0 for v in (self.fight_epoch,self.turn_epoch,self.canonical_cursor)):
            raise ValueError('INVALID_DECISION_FRAME_EPOCH')
        if not self.workflow_goal: raise ValueError('WORKFLOW_GOAL_REQUIRED')
        if self.client_instance_id and not self.client_instance_id.startswith('client-'):raise ValueError('INVALID_DECISION_CLIENT')
        if self.snapshot_semantic_sha256 and (len(self.snapshot_semantic_sha256)!=64 or any(c not in '0123456789abcdef' for c in self.snapshot_semantic_sha256)):raise ValueError('INVALID_DECISION_SNAPSHOT_HASH')
        if self.class_id is not None and (type(self.class_id) is not int or self.class_id<=0):raise ValueError('INVALID_DECISION_CLASS')
        for value,code in ((self.actor_id,'INVALID_DECISION_ACTOR'),(self.turn_owner_id,'INVALID_DECISION_TURN_OWNER')):
            if value is not None and (type(value) is not int or value==0):raise ValueError(code)
        if self.actor_cell is not None and (type(self.actor_cell) is not int or self.actor_cell<0):raise ValueError('INVALID_DECISION_CELL')
        if self.map_id is not None and (type(self.map_id) is not int or self.map_id<=0):raise ValueError('INVALID_DECISION_MAP')
        for value,code in ((self.ap,'INVALID_DECISION_AP'),(self.mp,'INVALID_DECISION_MP')):
            if value is not None and (type(value) is not int or value<0):raise ValueError(code)
        allowed={'KNOWN','UNKNOWN','STALE','CONFLICTING','NOT_OBSERVED'}
        if len({k for k,_ in self.proof_statuses})!=len(self.proof_statuses) or any(type(k) is not str or v not in allowed for k,v in self.proof_statuses):raise ValueError('INVALID_DECISION_PROOF_STATUS')
        if len(set(self.available_spells))!=len(self.available_spells) or any(type(s) is not int or s<=0 or type(g) is not int or g<=0 for s,g in self.available_spells):raise ValueError('INVALID_DECISION_SPELLS')
        if len(set(self.target_cells))!=len(self.target_cells) or any(type(x) is not int or x<0 for x in self.target_cells):raise ValueError('INVALID_DECISION_TARGET_CELLS')
        if len(set(self.candidate_move_cells))!=len(self.candidate_move_cells) or any(type(x) is not int or x<0 for x in self.candidate_move_cells):raise ValueError('INVALID_DECISION_MOVE_CELLS')
        if len(set(self.quarantined_action_keys))!=len(self.quarantined_action_keys) or any(type(x) is not str or len(x)!=64 or any(c not in '0123456789abcdef' for c in x) for x in self.quarantined_action_keys):raise ValueError('INVALID_DECISION_QUARANTINE')
        if type(self.deterministic_seed) is not int or type(self.budget_steps) is not int or self.budget_steps<1 or self.budget_steps>100000:raise ValueError('INVALID_DECISION_BUDGET')
        if self.route_step is not None and self.route_step not in ('U','D','L','R'):raise ValueError('INVALID_DECISION_ROUTE_STEP')
        if self.target_fight_id is not None and (type(self.target_fight_id) is not str or not self.target_fight_id.startswith('fight-')):raise ValueError('INVALID_DECISION_TARGET_FIGHT')
        if self.target_fight_epoch is not None and (type(self.target_fight_epoch) is not int or self.target_fight_epoch<=0):raise ValueError('INVALID_DECISION_TARGET_FIGHT_EPOCH')
        if self.encounter_id is not None and (type(self.encounter_id) is not str or not self.encounter_id.startswith('encounter-')):raise ValueError('INVALID_DECISION_ENCOUNTER')

@dataclass(frozen=True, slots=True)
class ActionPlan:
    plan_id: str
    action_key: str
    kind: str
    semantic_target: tuple[tuple[str,str], ...]
    expected_outcome_proofs: tuple[str, ...]
    basis_snapshot_id: str
    basis_canonical_cursor: int

    def __post_init__(self):
        if not self.plan_id.startswith('plan-') or not self.basis_snapshot_id.startswith('snap-'):
            raise ValueError('INVALID_PLAN_IDENTITY')
        if len(self.action_key)!=64 or any(c not in '0123456789abcdef' for c in self.action_key):
            raise ValueError('INVALID_PLAN_ACTION_KEY')
        if self.kind not in ('CAST','MOVE','READY','END_TURN','JOIN_FIGHT','WORLD_MOVE','START_FIGHT','WAIT'):
            raise ValueError('INVALID_PLAN_KIND')
        if type(self.basis_canonical_cursor) is not int or self.basis_canonical_cursor < 0:
            raise ValueError('INVALID_PLAN_CURSOR')
        if any(type(k) is not str or type(v) is not str for k,v in self.semantic_target):
            raise ValueError('INVALID_PLAN_TARGET')
        if self.kind != 'WAIT' and not self.expected_outcome_proofs:
            raise ValueError('PLAN_OUTCOME_PROOF_REQUIRED')

@dataclass(frozen=True, slots=True)
class PlannerResult:
    disposition: PlannerDisposition
    plan: ActionPlan | None = None
    required_evidence: tuple[str, ...] = ()
    reason: str = ''
    failure_code: str | None = None

    def __post_init__(self):
        if self.disposition not in ('PLAN','WAIT','NO_ACTION','FAULT'):
            raise ValueError('INVALID_PLANNER_DISPOSITION')
        if self.disposition == 'PLAN' and self.plan is None:
            raise ValueError('PLAN_RESULT_REQUIRES_PLAN')
        if self.disposition != 'PLAN' and self.plan is not None:
            raise ValueError('NONPLAN_RESULT_FORBIDS_PLAN')
        if self.disposition == 'WAIT' and not self.required_evidence:
            raise ValueError('WAIT_REQUIRES_EVIDENCE')
        if self.disposition in ('WAIT','NO_ACTION','FAULT') and not self.reason:
            raise ValueError('PLANNER_REASON_REQUIRED')
        if self.disposition == 'FAULT' and not self.failure_code:
            raise ValueError('PLANNER_FAILURE_CODE_REQUIRED')
