"""Versioned mission/run transition contract."""
from __future__ import annotations
from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class WorkflowTransition:
    transition_id: str
    run_id: str
    old_phase: str
    new_phase: str
    trigger: str
    evidence_ids: tuple[str, ...]
    fight_epoch: int | None
    expected_next_evidence: tuple[str, ...]
    recovery_budget_remaining: int
    terminal: bool

    def __post_init__(self):
        if not self.transition_id.startswith("transition-") or not self.run_id.startswith("run-"):
            raise ValueError("INVALID_WORKFLOW_IDENTITY")
        if any(type(x) is not str or not x for x in (self.old_phase,self.new_phase,self.trigger)):
            raise ValueError("INVALID_WORKFLOW_PHASE")
        if self.fight_epoch is not None and (type(self.fight_epoch) is not int or self.fight_epoch < 0):
            raise ValueError("INVALID_WORKFLOW_FIGHT_EPOCH")
        if type(self.recovery_budget_remaining) is not int or self.recovery_budget_remaining < 0 or type(self.terminal) is not bool:
            raise ValueError("INVALID_WORKFLOW_BUDGET")

# --- Definitive M10 workflow contracts ---
from typing import Literal as _Literal

WorkflowPhase = _Literal['CREATED','PREFLIGHT','WORLD','ENCOUNTER_SELECTED','FIGHT_ENTRY','PARTY_JOIN','PLACEMENT','READY','FIGHT_ACTIVE','FIGHT_END_RECONCILIATION','WORLD_REENTRY','RECOVERING','COMPLETED','STOPPED','BLOCKED']
FightResult = _Literal['VICTORY','DEFEAT','UNKNOWN','ABORTED']

@dataclass(frozen=True, slots=True)
class MissionConfigSpec:
    route_id: str
    min_monsters: int
    max_monsters: int
    target_wins: int
    max_attempts: int
    stop_on_loss: bool
    stop_on_unknown: bool
    config_sha256: str

    def __post_init__(self):
        if type(self.route_id) is not str or not self.route_id:
            raise ValueError('INVALID_MISSION_ROUTE')
        if any(type(v) is not int for v in (self.min_monsters,self.max_monsters,self.target_wins,self.max_attempts)):
            raise ValueError('INVALID_MISSION_INTEGER')
        if not (1<=self.min_monsters<=self.max_monsters<=8 and 1<=self.target_wins<=self.max_attempts<=1000):
            raise ValueError('INVALID_MISSION_BUDGET')
        if type(self.stop_on_loss) is not bool or type(self.stop_on_unknown) is not bool:
            raise ValueError('INVALID_MISSION_STOP_POLICY')
        if len(self.config_sha256)!=64 or any(c not in '0123456789abcdef' for c in self.config_sha256):
            raise ValueError('INVALID_MISSION_CONFIG_HASH')


@dataclass(frozen=True, slots=True)
class RoutePlan:
    route_id: str
    start_x: int
    start_y: int
    steps: tuple[str, ...]
    loop: bool
    source_sha256: str

    def __post_init__(self):
        if type(self.route_id) is not str or not self.route_id or not self.steps:
            raise ValueError('INVALID_ROUTE_PLAN')
        if any(step not in ('U','D','L','R') for step in self.steps) or type(self.loop) is not bool:
            raise ValueError('INVALID_ROUTE_STEPS')
        if len(self.source_sha256)!=64 or any(c not in '0123456789abcdef' for c in self.source_sha256):
            raise ValueError('INVALID_ROUTE_SOURCE_HASH')


@dataclass(frozen=True, slots=True)
class EffectiveMissionPlan:
    plan_id: str
    config: MissionConfigSpec
    route: RoutePlan
    watchdog_budget_ticks: int
    recovery_budget: int

    def __post_init__(self):
        if not self.plan_id.startswith('missionplan-'):
            raise ValueError('INVALID_MISSION_PLAN_ID')
        if type(self.watchdog_budget_ticks) is not int or not 1<=self.watchdog_budget_ticks<=100000:
            raise ValueError('INVALID_WATCHDOG_BUDGET')
        if type(self.recovery_budget) is not int or not 0<=self.recovery_budget<=100:
            raise ValueError('INVALID_RECOVERY_BUDGET')


@dataclass(frozen=True, slots=True)
class EncounterCandidate:
    encounter_id: str
    monster_count: int
    map_id: int

    def __post_init__(self):
        if not self.encounter_id.startswith('encounter-') or type(self.monster_count) is not int or not 1<=self.monster_count<=8 or type(self.map_id) is not int or self.map_id<=0:
            raise ValueError('INVALID_ENCOUNTER_CANDIDATE')


@dataclass(frozen=True, slots=True)
class WorkflowSignal:
    signal_id: str
    kind: str
    monotonic_tick: int
    evidence_ids: tuple[str, ...] = ()
    fight_epoch: int | None = None
    fight_result: FightResult | None = None
    action_id: str | None = None
    action_status: str | None = None
    encounter_id: str | None = None
    encounter_map_id: int | None = None
    recovery_generation: int | None = None

    def __post_init__(self):
        allowed={'START','PREFLIGHT_OK','WORLD_OBSERVED','ROUTE_STEP_PROVEN','ENCOUNTER_SELECTED','FIGHT_ENTRY_PROVEN','PARTY_JOIN_PROVEN','PLACEMENT_PROVEN','READY_PROVEN','FIRST_TURN_PROVEN','ACTION_SUBMITTED','ACTION_OUTCOME','FIGHT_ENDED','FIGHT_OUTCOME','WORLD_REENTRY_PROVEN','HEARTBEAT','WATCHDOG','RECOVERY_SUCCEEDED','RECOVERY_FAILED','STOP_REQUESTED'}
        if not self.signal_id.startswith('wfsig-') or self.kind not in allowed:
            raise ValueError('INVALID_WORKFLOW_SIGNAL')
        if type(self.monotonic_tick) is not int or self.monotonic_tick<0:
            raise ValueError('INVALID_WORKFLOW_TICK')
        if self.fight_epoch is not None and (type(self.fight_epoch) is not int or self.fight_epoch<=0):
            raise ValueError('INVALID_WORKFLOW_SIGNAL_FIGHT')
        if self.kind=='FIGHT_OUTCOME' and self.fight_result is None:
            raise ValueError('WORKFLOW_OUTCOME_REQUIRED')
        if self.fight_result is not None and self.kind!='FIGHT_OUTCOME':
            raise ValueError('WORKFLOW_OUTCOME_EXTRANEOUS')
        if self.kind in ('ACTION_SUBMITTED','ACTION_OUTCOME') and (self.action_id is None or not self.action_id.startswith('action-')):
            raise ValueError('WORKFLOW_ACTION_ID_REQUIRED')
        if self.action_status is not None and self.kind!='ACTION_OUTCOME':
            raise ValueError('WORKFLOW_ACTION_STATUS_EXTRANEOUS')
        if self.kind=='ACTION_OUTCOME' and self.action_status not in ('REJECTED_NOT_SENT','PENDING','CONFIRMED_UNSETTLED','SETTLED_SUCCESS','PROVEN_FAILURE','UNCERTAIN','TERMINAL_UNRESOLVED'):
            raise ValueError('INVALID_WORKFLOW_ACTION_STATUS')
        if (self.encounter_id is None) != (self.encounter_map_id is None):
            raise ValueError('WORKFLOW_ENCOUNTER_BINDING_INCOMPLETE')
        if self.encounter_id is not None:
            if self.kind!='ENCOUNTER_SELECTED' or not self.encounter_id.startswith('encounter-') or type(self.encounter_map_id) is not int or self.encounter_map_id<=0:
                raise ValueError('INVALID_WORKFLOW_ENCOUNTER_BINDING')
        if len(set(self.evidence_ids))!=len(self.evidence_ids) or any(type(x) is not str or not x for x in self.evidence_ids):
            raise ValueError('INVALID_WORKFLOW_EVIDENCE')
        if self.recovery_generation is not None:
            if type(self.recovery_generation) is not int or self.recovery_generation<=0:
                raise ValueError('INVALID_WORKFLOW_RECOVERY_GENERATION')
            if self.kind not in ('RECOVERY_SUCCEEDED','RECOVERY_FAILED'):
                raise ValueError('WORKFLOW_RECOVERY_GENERATION_EXTRANEOUS')


@dataclass(frozen=True, slots=True)
class WorkflowSnapshot:
    run_id: str
    phase: WorkflowPhase
    fight_epoch: int
    attempts: int
    wins: int
    losses: int
    unknowns: int
    aborted: int
    route_index: int
    pending_action_id: str | None
    counted_fight_epochs: tuple[int, ...]
    started_fight_epochs: tuple[int, ...]
    processed_signal_ids: tuple[str, ...]
    progress_generation: int
    progress_token: str
    phase_started_tick: int
    watchdog_deadline_tick: int | None
    recovery_budget_remaining: int
    resume_phase: str | None
    expected_next_evidence: tuple[str, ...]
    terminal_reason: str | None = None
    goal_reached_pending_reentry: bool = False
    plan_id: str = ''
    selected_encounter_id: str | None = None
    selected_encounter_map_id: int | None = None
    recovery_generation: int | None = None
    active_recovery_generation: int | None = None
    last_processed_tick: int | None = None

    def __post_init__(self):
        if not self.run_id.startswith('run-') or self.phase not in ('CREATED','PREFLIGHT','WORLD','ENCOUNTER_SELECTED','FIGHT_ENTRY','PARTY_JOIN','PLACEMENT','READY','FIGHT_ACTIVE','FIGHT_END_RECONCILIATION','WORLD_REENTRY','RECOVERING','COMPLETED','STOPPED','BLOCKED'):
            raise ValueError('INVALID_WORKFLOW_SNAPSHOT')
        if not isinstance(self.plan_id,str) or not self.plan_id.startswith('missionplan-'):
            raise ValueError('INVALID_WORKFLOW_PLAN_BINDING')
        nums=(self.fight_epoch,self.attempts,self.wins,self.losses,self.unknowns,self.aborted,self.route_index,self.progress_generation,self.phase_started_tick,self.recovery_budget_remaining)
        if any(type(v) is not int or v<0 for v in nums):
            raise ValueError('INVALID_WORKFLOW_COUNTER')
        if self.attempts != self.wins+self.losses+self.unknowns+self.aborted:
            # Started fights are tracked independently. attempts here means reconciled attempts/outcomes.
            raise ValueError('WORKFLOW_COUNTER_MISMATCH')
        if len(self.progress_token)!=64 or any(c not in '0123456789abcdef' for c in self.progress_token):
            raise ValueError('INVALID_WORKFLOW_PROGRESS_TOKEN')
        if self.watchdog_deadline_tick is not None and (type(self.watchdog_deadline_tick) is not int or self.watchdog_deadline_tick<self.phase_started_tick):
            raise ValueError('INVALID_WORKFLOW_DEADLINE')
        if len(set(self.counted_fight_epochs))!=len(self.counted_fight_epochs) or len(set(self.started_fight_epochs))!=len(self.started_fight_epochs) or len(set(self.processed_signal_ids))!=len(self.processed_signal_ids):
            raise ValueError('INVALID_WORKFLOW_IDEMPOTENCE_SET')
        if self.pending_action_id is not None and not self.pending_action_id.startswith('action-'):
            raise ValueError('INVALID_WORKFLOW_PENDING_ACTION')
        if self.phase in ('COMPLETED','STOPPED','BLOCKED') and self.terminal_reason is None:
            raise ValueError('TERMINAL_WORKFLOW_REQUIRES_REASON')
        if (self.selected_encounter_id is None) != (self.selected_encounter_map_id is None):
            raise ValueError('WORKFLOW_SELECTED_ENCOUNTER_INCOMPLETE')
        if self.selected_encounter_id is not None and (not self.selected_encounter_id.startswith('encounter-') or type(self.selected_encounter_map_id) is not int or self.selected_encounter_map_id<=0):
            raise ValueError('INVALID_WORKFLOW_SELECTED_ENCOUNTER')
        if self.recovery_generation is not None and (type(self.recovery_generation) is not int or self.recovery_generation<0):
            raise ValueError('INVALID_WORKFLOW_RECOVERY_GENERATION')
        if self.active_recovery_generation is not None:
            if type(self.active_recovery_generation) is not int or self.active_recovery_generation<=0:
                raise ValueError('INVALID_WORKFLOW_ACTIVE_RECOVERY_GENERATION')
            if self.phase!='RECOVERING' or self.recovery_generation!=self.active_recovery_generation:
                raise ValueError('WORKFLOW_ACTIVE_RECOVERY_GENERATION_MISMATCH')
        if self.last_processed_tick is not None:
            # Durable accepted-time authority is independent from the semantic
            # phase/watchdog origin.  A safe resume may start a new phase clock
            # above the persisted watermark before another signal is accepted.
            if type(self.last_processed_tick) is not int or self.last_processed_tick<0:
                raise ValueError('INVALID_WORKFLOW_LAST_PROCESSED_TICK')


RecoveryOutcomeDisposition = _Literal['CURRENT','IDEMPOTENT','REJECTED']

@dataclass(frozen=True, slots=True)
class WorkflowRecoveryCorrelation:
    disposition: RecoveryOutcomeDisposition
    reason: str

    def __post_init__(self):
        if self.disposition not in ('CURRENT','IDEMPOTENT','REJECTED') or type(self.reason) is not str or not self.reason:
            raise ValueError('INVALID_WORKFLOW_RECOVERY_CORRELATION')


def next_workflow_recovery_generation(snapshot: WorkflowSnapshot) -> int:
    """Return the next monotonic recovery namespace without mutating state."""
    if not isinstance(snapshot,WorkflowSnapshot):
        raise ValueError('WORKFLOW_SNAPSHOT_REQUIRED')
    if snapshot.recovery_generation is None:
        raise ValueError('WORKFLOW_RECOVERY_GENERATION_UNPROVEN')
    return snapshot.recovery_generation+1


def correlate_recovery_outcome(snapshot: WorkflowSnapshot, signal: WorkflowSignal) -> WorkflowRecoveryCorrelation:
    """Correlate a recovery result without granting phase-transition authority.

    Phase A deliberately exposes the shared fail-closed identity semantics while
    leaving actual state-machine settlement to the Workflow owner in Phase B.
    """
    if not isinstance(snapshot,WorkflowSnapshot) or not isinstance(signal,WorkflowSignal):
        raise ValueError('WORKFLOW_RECOVERY_CORRELATION_CONTRACT_REQUIRED')
    if signal.kind not in ('RECOVERY_SUCCEEDED','RECOVERY_FAILED'):
        raise ValueError('WORKFLOW_RECOVERY_OUTCOME_REQUIRED')
    generation=signal.recovery_generation
    if generation is None:
        return WorkflowRecoveryCorrelation('REJECTED','RECOVERY_IDENTITY_MISSING')
    if snapshot.recovery_generation is None:
        return WorkflowRecoveryCorrelation('REJECTED','RECOVERY_SNAPSHOT_GENERATION_UNPROVEN')
    if generation>snapshot.recovery_generation:
        return WorkflowRecoveryCorrelation('REJECTED','RECOVERY_OUTCOME_FUTURE_GENERATION')
    if snapshot.phase=='RECOVERING':
        active=snapshot.active_recovery_generation
        if active is None:
            return WorkflowRecoveryCorrelation('REJECTED','RECOVERY_ACTIVE_GENERATION_UNPROVEN')
        if generation==active:
            return WorkflowRecoveryCorrelation('CURRENT','RECOVERY_OUTCOME_CURRENT')
        return WorkflowRecoveryCorrelation('REJECTED','RECOVERY_OUTCOME_STALE_GENERATION')
    if generation==snapshot.recovery_generation:
        return WorkflowRecoveryCorrelation('IDEMPOTENT','RECOVERY_OUTCOME_ALREADY_NONCURRENT')
    return WorkflowRecoveryCorrelation('REJECTED','RECOVERY_OUTCOME_STALE_GENERATION')


def with_accepted_workflow_tick(snapshot: WorkflowSnapshot, monotonic_tick: int) -> WorkflowSnapshot:
    """Advance only the durable temporal watermark for an already-accepted signal.

    The semantic phase/watchdog clocks are intentionally untouched.  Callers
    must not invoke this helper for rejected input; Workflow Phase B owns that
    acceptance decision.
    """
    if not isinstance(snapshot,WorkflowSnapshot) or type(monotonic_tick) is not int or monotonic_tick<0:
        raise ValueError('INVALID_WORKFLOW_WATERMARK_UPDATE')
    if snapshot.last_processed_tick is None:
        raise ValueError('WORKFLOW_WATERMARK_UNPROVEN')
    if monotonic_tick<snapshot.last_processed_tick:
        raise ValueError('WORKFLOW_TICK_BELOW_WATERMARK')
    return replace(snapshot,last_processed_tick=monotonic_tick)


@dataclass(frozen=True, slots=True)
class WorkflowApplyResult:
    status: str
    semantic_progress: bool
    reason: str
    snapshot: WorkflowSnapshot
    transition: WorkflowTransition | None = None

    def __post_init__(self):
        if self.status not in ('APPLIED','DUPLICATE','REJECTED') or type(self.semantic_progress) is not bool or not self.reason:
            raise ValueError('INVALID_WORKFLOW_APPLY_RESULT')


@dataclass(frozen=True, slots=True)
class WorkflowActionDispatch:
    status: str
    reason: str
    action_id: str | None = None
    outcome_status: str | None = None
    action_key: str | None = None

    def __post_init__(self):
        if self.status not in ('SUBMITTED','WAIT','NO_ACTION','FAULT') or not self.reason:
            raise ValueError('INVALID_WORKFLOW_ACTION_DISPATCH')
        if self.status=='SUBMITTED' and (self.action_id is None or self.outcome_status is None or self.action_key is None):
            raise ValueError('SUBMITTED_WORKFLOW_ACTION_INCOMPLETE')
