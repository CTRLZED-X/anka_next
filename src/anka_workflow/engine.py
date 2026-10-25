"""Definitive M10 mission lifecycle owner with bounded semantic watchdogs."""
from __future__ import annotations
from dataclasses import replace
from hashlib import sha256
import json
from threading import RLock

from anka_contracts.workflow import (
    EffectiveMissionPlan, EncounterCandidate, WorkflowApplyResult, WorkflowSignal,
    WorkflowSnapshot, WorkflowTransition,
)


class WorkflowRejected(ValueError):
    pass


_EXPECTED={
    'CREATED':('START',),'PREFLIGHT':('PREFLIGHT_OK',),'WORLD':('ENCOUNTER_SELECTED',),
    'ENCOUNTER_SELECTED':('FIGHT_ENTRY_PROVEN',),'FIGHT_ENTRY':('PARTY_JOIN_PROVEN',),
    'PARTY_JOIN':('PLACEMENT_PROVEN',),'PLACEMENT':('READY_PROVEN',),'READY':('FIRST_TURN_PROVEN',),
    'FIGHT_ACTIVE':('ACTION_OUTCOME','FIGHT_ENDED'),'FIGHT_END_RECONCILIATION':('FIGHT_OUTCOME',),
    'WORLD_REENTRY':('WORLD_REENTRY_PROVEN',),'RECOVERING':('RECOVERY_SUCCEEDED','RECOVERY_FAILED'),
    'COMPLETED':(),'STOPPED':(),'BLOCKED':(),
}
_TERMINAL={'COMPLETED','STOPPED','BLOCKED'}
_ACTION_PHASES={'WORLD','ENCOUNTER_SELECTED','FIGHT_ENTRY','PARTY_JOIN','PLACEMENT','READY','FIGHT_ACTIVE'}
# Exact signal-id retention is required for restart-safe idempotence, so it must
# never be silently truncated.  Instead, derive a generous but finite ceiling
# from the configured mission budget and reserve one final slot for a fail-closed
# terminal transition if the history is exhausted.
_MIN_SIGNAL_HISTORY=4096
_MAX_SIGNAL_HISTORY=65536
_SIGNALS_PER_ATTEMPT_BUDGET=128


def _signal_history_limit(plan:EffectiveMissionPlan)->int:
    return max(_MIN_SIGNAL_HISTORY,min(_MAX_SIGNAL_HISTORY,
        _MIN_SIGNAL_HISTORY+plan.config.max_attempts*_SIGNALS_PER_ATTEMPT_BUDGET))


def _token(run_id:str, phase:str, fight_epoch:int, counters:tuple[int,...], route_index:int, pending:str|None, counted:tuple[int,...], started:tuple[int,...], generation:int)->str:
    return sha256(json.dumps({'run':run_id,'phase':phase,'fight':fight_epoch,'counters':counters,'route':route_index,'pending':pending,'counted':counted,'started':started,'generation':generation},sort_keys=True,separators=(',',':')).encode()).hexdigest()


class MissionWorkflow:
    def __init__(self, run_id: str, plan: EffectiveMissionPlan, observer=None):
        if not run_id.startswith('run-') or not isinstance(plan,EffectiveMissionPlan):
            raise WorkflowRejected('INVALID_WORKFLOW_BOOTSTRAP')
        self.plan=plan
        self._observer=observer
        self._lock=RLock()
        self._seen:set[str]=set()
        self._signal_history_limit=_signal_history_limit(plan)
        self._snapshot=WorkflowSnapshot(run_id,'CREATED',0,0,0,0,0,0,0,None,(),(),(),0,
            _token(run_id,'CREATED',0,(0,0,0,0,0),0,None,(),(),0),0,None,plan.recovery_budget,None,_EXPECTED['CREATED'],
            plan_id=plan.plan_id)

    @classmethod
    def resume(cls, plan:EffectiveMissionPlan, snapshot:WorkflowSnapshot, *, resume_tick:int, observer=None):
        if not isinstance(snapshot,WorkflowSnapshot) or type(resume_tick) is not int or resume_tick<0:
            raise WorkflowRejected('INVALID_WORKFLOW_RESUME')
        if snapshot.plan_id != plan.plan_id:
            raise WorkflowRejected('RESUME_MISSION_PLAN_MISMATCH')
        if snapshot.pending_action_id is not None:
            raise WorkflowRejected('RESUME_PENDING_ACTION_RECONCILIATION_REQUIRED')
        engine=cls(snapshot.run_id,plan,observer=observer)
        if len(snapshot.processed_signal_ids)>=engine._signal_history_limit and snapshot.phase not in _TERMINAL:
            raise WorkflowRejected('RESUME_IDEMPOTENCE_HISTORY_EXHAUSTED')
        engine._seen=set(snapshot.processed_signal_ids)
        if snapshot.phase in _TERMINAL:
            engine._snapshot=snapshot
            return engine
        # Resume must never rewind the temporal acceptance fence.  Otherwise a
        # stale signal with a fresh transport identity can become admissible
        # after restart simply because the caller supplied an older tick.
        if resume_tick < snapshot.phase_started_tick:
            raise WorkflowRejected('RESUME_TICK_REGRESSION')
        gen=snapshot.progress_generation+1
        progress=_token(snapshot.run_id,snapshot.phase,snapshot.fight_epoch,(snapshot.attempts,snapshot.wins,snapshot.losses,snapshot.unknowns,snapshot.aborted),snapshot.route_index,None,snapshot.counted_fight_epochs,snapshot.started_fight_epochs,gen)
        engine._snapshot=replace(snapshot,progress_generation=gen,progress_token=progress,phase_started_tick=resume_tick,watchdog_deadline_tick=resume_tick+plan.watchdog_budget_ticks,resume_phase=None if snapshot.phase!='RECOVERING' else snapshot.resume_phase)
        return engine

    def snapshot(self)->WorkflowSnapshot:
        with self._lock:return self._snapshot

    def select_encounter(self,candidates:tuple[EncounterCandidate,...])->EncounterCandidate|None:
        if type(candidates) is not tuple or len(candidates)>512 or any(not isinstance(x,EncounterCandidate) for x in candidates):
            raise WorkflowRejected('INVALID_ENCOUNTER_SET')
        acceptable=[x for x in candidates if self.plan.config.min_monsters<=x.monster_count<=self.plan.config.max_monsters]
        return min(acceptable,key=lambda x:(x.monster_count,x.encounter_id)) if acceptable else None

    def next_route_step(self)->str:
        with self._lock:
            route=self.plan.route
            if self._snapshot.route_index>=len(route.steps) and not route.loop:
                raise WorkflowRejected('ROUTE_EXHAUSTED')
            return route.steps[self._snapshot.route_index % len(route.steps)]

    def _transition(self,new_phase:str,signal:WorkflowSignal,*,reason:str, pending_action_id=Ellipsis,
                    fight_epoch=Ellipsis, counters:tuple[int,int,int,int,int]|None=None,
                    counted=Ellipsis,started=Ellipsis,route_index=Ellipsis,recovery_remaining=Ellipsis,
                    resume_phase=Ellipsis,terminal_reason=Ellipsis,goal_pending=Ellipsis,
                    selected_encounter_id=Ellipsis,selected_encounter_map_id=Ellipsis)->WorkflowApplyResult:
        old=self._snapshot
        gen=old.progress_generation+1
        fe=old.fight_epoch if fight_epoch is Ellipsis else fight_epoch
        pa=old.pending_action_id if pending_action_id is Ellipsis else pending_action_id
        ri=old.route_index if route_index is Ellipsis else route_index
        co=old.counted_fight_epochs if counted is Ellipsis else counted
        st=old.started_fight_epochs if started is Ellipsis else started
        rr=old.recovery_budget_remaining if recovery_remaining is Ellipsis else recovery_remaining
        rp=old.resume_phase if resume_phase is Ellipsis else resume_phase
        tr=old.terminal_reason if terminal_reason is Ellipsis else terminal_reason
        gp=old.goal_reached_pending_reentry if goal_pending is Ellipsis else goal_pending
        sei=old.selected_encounter_id if selected_encounter_id is Ellipsis else selected_encounter_id
        sem=old.selected_encounter_map_id if selected_encounter_map_id is Ellipsis else selected_encounter_map_id
        if counters is None:counters=(old.attempts,old.wins,old.losses,old.unknowns,old.aborted)
        deadline=None if new_phase in _TERMINAL|{'CREATED'} else signal.monotonic_tick+self.plan.watchdog_budget_ticks
        processed=old.processed_signal_ids+(signal.signal_id,)
        progress=_token(old.run_id,new_phase,fe,counters,ri,pa,co,st,gen)
        snap=WorkflowSnapshot(old.run_id,new_phase,fe,*counters,ri,pa,co,st,processed,gen,progress,
            signal.monotonic_tick,deadline,rr,rp,_EXPECTED[new_phase],tr,gp,plan_id=old.plan_id,
            selected_encounter_id=sei,selected_encounter_map_id=sem)
        trans=WorkflowTransition('transition-'+sha256((old.run_id+signal.signal_id+new_phase).encode()).hexdigest()[:24],old.run_id,old.phase,new_phase,signal.kind,signal.evidence_ids,fe if fe>0 else None,_EXPECTED[new_phase],rr,new_phase in _TERMINAL)
        self._seen.add(signal.signal_id);self._snapshot=snap
        return WorkflowApplyResult('APPLIED',True,reason,snap,trans)

    def _nonprogress(self,signal:WorkflowSignal,reason:str,status='APPLIED')->WorkflowApplyResult:
        self._seen.add(signal.signal_id)
        self._snapshot=replace(self._snapshot,processed_signal_ids=self._snapshot.processed_signal_ids+(signal.signal_id,))
        return WorkflowApplyResult(status,False,reason,self._snapshot,None)

    def _record(self,name:str,signal:WorkflowSignal,result:WorkflowApplyResult,**kwargs)->None:
        if self._observer is None:return
        # The entire diagnostic construction path is best-effort, not just the
        # final sink call. A schema/payload bug must never become Workflow state.
        try:
            snap=result.snapshot
            payload={
                'signal_id':signal.signal_id,'signal_kind':signal.kind,'status':result.status,'reason':result.reason,
                'phase':snap.phase,'progress_generation':snap.progress_generation,'route_index':snap.route_index,
                'pending_action_id':snap.pending_action_id,'expected_signals':list(snap.expected_next_evidence),
            }
            if result.transition is not None:
                payload.update({'transition_id':result.transition.transition_id,'from_phase':result.transition.old_phase,
                                'to_phase':result.transition.new_phase})
            payload.update(kwargs.pop('payload',{}))
            severity=kwargs.pop('severity','INFO')
            failure_code=kwargs.pop('failure_code',None)
            self._observer.record(name,owner_system='anka_workflow',severity=severity,
                boundary=kwargs.pop('boundary','workflow.transition'),failure_code=failure_code,
                fight_epoch=snap.fight_epoch if snap.fight_epoch>0 else None,action_id=signal.action_id,
                evidence_class=kwargs.pop('evidence_class','AUTHORITY_COMMITTED' if result.status=='APPLIED' else 'DERIVED'),
                payload=payload,**kwargs)
        except Exception:
            pass

    def _publish_apply(self,signal:WorkflowSignal,result:WorkflowApplyResult)->None:
        # Publish only after releasing Workflow's authority lock. Observer latency
        # or failure must not influence lifecycle ordering or watchdog semantics.
        if result.status=='REJECTED':
            self._record('workflow.signal_rejected',signal,result,boundary='workflow.signal_validation',
                         severity='WARNING',failure_code=result.reason,evidence_class='DERIVED')
            return
        if result.status=='DUPLICATE':
            return
        if result.transition is not None:
            severity='SAFETY' if result.snapshot.phase=='BLOCKED' else 'INFO'
            failure=result.snapshot.terminal_reason if result.snapshot.phase=='BLOCKED' else None
            self._record('workflow.phase_changed',signal,result,boundary='workflow.transition',severity=severity,
                         failure_code=failure)
            if signal.kind=='ACTION_SUBMITTED':
                self._record('workflow.action_pending',signal,result,boundary='workflow.action_fence')
            elif signal.kind=='ACTION_OUTCOME' and result.snapshot.pending_action_id is None:
                self._record('workflow.action_cleared',signal,result,boundary='workflow.action_fence',
                             payload={'action_status':signal.action_status})
            if result.snapshot.phase=='RECOVERING':
                self._record('workflow.recovery_started',signal,result,boundary='workflow.recovery',severity='WARNING')
            elif result.snapshot.phase=='BLOCKED':
                self._record('workflow.blocked',signal,result,boundary='workflow.blocked',severity='SAFETY',
                             failure_code=result.snapshot.terminal_reason or result.reason)

    def apply(self,signal:WorkflowSignal)->WorkflowApplyResult:
        # Watchdog, coordination and action-outcome producers may race. Workflow
        # owns one lifecycle snapshot, so each signal is validated and applied as
        # one serialized transition rather than relying on shared-set atomicity.
        with self._lock:
            result=self._apply_unlocked(signal)
        self._publish_apply(signal,result)
        return result

    def _apply_unlocked(self,signal:WorkflowSignal)->WorkflowApplyResult:
        if not isinstance(signal,WorkflowSignal):raise WorkflowRejected('WORKFLOW_SIGNAL_REQUIRED')
        s=self._snapshot
        if signal.signal_id in self._seen or signal.signal_id in s.processed_signal_ids:
            return WorkflowApplyResult('DUPLICATE',False,'SIGNAL_IDEMPOTENT',s,None)
        if signal.monotonic_tick < s.phase_started_tick:
            return WorkflowApplyResult('REJECTED',False,'MONOTONIC_TICK_REGRESSION',s,None)
        # Semantic duplicates with a new transport/signal identity are idempotent too.
        if signal.kind=='FIGHT_OUTCOME' and signal.fight_epoch is not None and signal.fight_epoch in s.counted_fight_epochs:
            return self._nonprogress(signal,'FIGHT_OUTCOME_ALREADY_COUNTED','DUPLICATE')
        if signal.kind=='FIGHT_ENDED' and signal.fight_epoch==s.fight_epoch and s.phase in ('FIGHT_END_RECONCILIATION','WORLD_REENTRY'):
            return self._nonprogress(signal,'FIGHT_END_ALREADY_OBSERVED','DUPLICATE')
        if signal.kind=='WORLD_REENTRY_PROVEN' and signal.fight_epoch==s.fight_epoch and s.phase=='WORLD':
            return self._nonprogress(signal,'WORLD_REENTRY_ALREADY_OBSERVED','DUPLICATE')
        if s.phase in _TERMINAL:
            # Terminal snapshots are immutable replay fences.  A repeated stop is
            # already satisfied and must not append a fresh transport identity;
            # otherwise unique STOP_REQUESTED traffic can grow history forever
            # after the workflow has supposedly become bounded and immutable.
            if signal.kind=='STOP_REQUESTED':
                return WorkflowApplyResult('DUPLICATE',False,'ALREADY_TERMINAL',s,None)
            return WorkflowApplyResult('REJECTED',False,'WORKFLOW_TERMINAL',s,None)
        # Never forget an already-processed transition just to bound memory: that
        # could make an old command replayable after restart. Reserve the final
        # history slot for an explicit fail-closed terminal transition instead.
        if len(s.processed_signal_ids)>=self._signal_history_limit-1 and signal.kind!='STOP_REQUESTED':
            return self._transition('BLOCKED',signal,reason='IDEMPOTENCE_HISTORY_EXHAUSTED',
                                    terminal_reason='WORKFLOW_IDEMPOTENCE_HISTORY_EXHAUSTED')
        if signal.kind=='STOP_REQUESTED':
            return self._transition('STOPPED',signal,reason='STOP_REQUESTED',terminal_reason='STOP_REQUESTED')
        # Only an explicit watchdog may turn elapsed time into recovery/blocking.
        # An unresolved external action is *not* ordinary phase recovery: retrying
        # around it could duplicate a click that may already have reached the game.
        if signal.kind=='WATCHDOG' and s.pending_action_id is not None:
            if s.watchdog_deadline_tick is None or signal.monotonic_tick<=s.watchdog_deadline_tick:
                return self._nonprogress(signal,'WATCHDOG_WITHIN_BUDGET')
            return self._transition('BLOCKED',signal,reason='PENDING_ACTION_RECONCILIATION_REQUIRED',
                                    terminal_reason='WORKFLOW_PENDING_ACTION_TIMEOUT_REQUIRES_RECONCILIATION')
        if signal.kind=='WATCHDOG':
            if s.watchdog_deadline_tick is None or signal.monotonic_tick<=s.watchdog_deadline_tick:
                return self._nonprogress(signal,'WATCHDOG_WITHIN_BUDGET')
            if s.recovery_budget_remaining>0:
                # A recovery attempt may itself time out.  Preserve the original
                # phase we are trying to recover rather than replacing it with
                # RECOVERING; otherwise RECOVERY_SUCCEEDED can strand the state
                # machine in RECOVERING with no valid resume target.
                resume_target=s.resume_phase if s.phase=='RECOVERING' else s.phase
                return self._transition('RECOVERING',signal,reason='WATCHDOG_RECOVERY_REQUIRED',recovery_remaining=s.recovery_budget_remaining-1,resume_phase=resume_target)
            return self._transition('BLOCKED',signal,reason='WATCHDOG_BUDGET_EXHAUSTED',terminal_reason='WORKFLOW_TIMEOUT_'+s.phase)
        if signal.kind=='HEARTBEAT':
            return self._nonprogress(signal,'HEARTBEAT_NOT_SEMANTIC_PROGRESS')
        # External-action uncertainty is owned consistently in every phase that
        # may issue input, including pre-turn placement/Ready and world/join.
        if s.phase in _ACTION_PHASES and signal.kind=='ACTION_SUBMITTED':
            if s.fight_epoch>0 and signal.fight_epoch!=s.fight_epoch:return WorkflowApplyResult('REJECTED',False,'FIGHT_EPOCH_MISMATCH',s,None)
            if s.fight_epoch==0 and signal.fight_epoch is not None:return WorkflowApplyResult('REJECTED',False,'FIGHT_EPOCH_MISMATCH',s,None)
            if s.pending_action_id is not None:return WorkflowApplyResult('REJECTED',False,'ACTION_ALREADY_PENDING',s,None)
            return self._transition(s.phase,signal,reason='ACTION_SUBMITTED',pending_action_id=signal.action_id)
        if s.phase in _ACTION_PHASES and signal.kind=='ACTION_OUTCOME':
            if s.fight_epoch>0 and signal.fight_epoch!=s.fight_epoch:return WorkflowApplyResult('REJECTED',False,'FIGHT_EPOCH_MISMATCH',s,None)
            if s.fight_epoch==0 and signal.fight_epoch is not None:return WorkflowApplyResult('REJECTED',False,'FIGHT_EPOCH_MISMATCH',s,None)
            if s.pending_action_id!=signal.action_id:return WorkflowApplyResult('REJECTED',False,'ACTION_OUTCOME_NOT_PENDING',s,None)
            if signal.action_status in ('PENDING','CONFIRMED_UNSETTLED'):
                return self._nonprogress(signal,'ACTION_STILL_UNSETTLED')
            if signal.action_status in ('UNCERTAIN','TERMINAL_UNRESOLVED'):
                return self._transition('BLOCKED',signal,reason='ACTION_OUTCOME_UNSAFE',terminal_reason='UNRESOLVED_ACTION_SIDE_EFFECT')
            return self._transition(s.phase,signal,reason='ACTION_SETTLED_OR_NOT_SENT',pending_action_id=None)
        # A phase transition while input is unresolved would lose the retry fence.
        # Fight-end proof is the sole safe superseding event because the fight epoch
        # itself has ended and the action can no longer be blindly replayed there.
        if s.pending_action_id is not None and signal.kind!='FIGHT_ENDED':
            return WorkflowApplyResult('REJECTED',False,'PENDING_ACTION_RECONCILIATION_REQUIRED',s,None)
        if s.phase=='RECOVERING':
            # A watchdog may race the authoritative proof it was waiting for.
            # Preserve that proof instead of requiring an unrelated recovery
            # acknowledgement and risking a permanent lifecycle stall.
            if s.resume_phase=='PREFLIGHT' and signal.kind=='PREFLIGHT_OK':
                return self._transition('WORLD',signal,reason='PREFLIGHT_OK_SUPERSEDES_RECOVERY',resume_phase=None)
            if s.resume_phase=='WORLD' and signal.kind=='ROUTE_STEP_PROVEN':
                return self._transition('WORLD',signal,reason='ROUTE_STEP_PROVEN_SUPERSEDES_RECOVERY',
                                        route_index=s.route_index+1,resume_phase=None)
            if s.resume_phase=='WORLD' and signal.kind=='ENCOUNTER_SELECTED':
                if len(s.started_fight_epochs)>=self.plan.config.max_attempts:
                    return self._transition('STOPPED',signal,reason='MAX_ATTEMPTS_REACHED',
                                            terminal_reason='MAX_ATTEMPTS_REACHED',resume_phase=None)
                return self._transition('ENCOUNTER_SELECTED',signal,reason='ENCOUNTER_SELECTED_SUPERSEDES_RECOVERY',
                                        selected_encounter_id=signal.encounter_id,
                                        selected_encounter_map_id=signal.encounter_map_id,resume_phase=None)
            if s.resume_phase=='ENCOUNTER_SELECTED' and signal.kind=='FIGHT_ENTRY_PROVEN':
                if signal.fight_epoch is None or signal.fight_epoch<=s.fight_epoch or signal.fight_epoch in s.started_fight_epochs:
                    return WorkflowApplyResult('REJECTED',False,'NEW_FIGHT_EPOCH_REQUIRED',s,None)
                return self._transition('FIGHT_ENTRY',signal,reason='FIGHT_ENTRY_PROVEN_SUPERSEDES_RECOVERY',
                                        fight_epoch=signal.fight_epoch,
                                        started=s.started_fight_epochs+(signal.fight_epoch,),resume_phase=None)
            recovery_progress={
                'FIGHT_ENTRY':('PARTY_JOIN_PROVEN','PARTY_JOIN'),
                'PARTY_JOIN':('PLACEMENT_PROVEN','PLACEMENT'),
                'PLACEMENT':('READY_PROVEN','READY'),
                'READY':('FIRST_TURN_PROVEN','FIGHT_ACTIVE'),
            }
            expected=recovery_progress.get(s.resume_phase)
            if expected is not None and signal.kind==expected[0]:
                if signal.fight_epoch!=s.fight_epoch:return WorkflowApplyResult('REJECTED',False,'FIGHT_EPOCH_MISMATCH',s,None)
                return self._transition(expected[1],signal,reason=signal.kind+'_SUPERSEDES_RECOVERY',resume_phase=None)
            if s.resume_phase=='FIGHT_END_RECONCILIATION' and signal.kind=='FIGHT_OUTCOME':
                if signal.fight_epoch!=s.fight_epoch:return WorkflowApplyResult('REJECTED',False,'FIGHT_EPOCH_MISMATCH',s,None)
                attempts,wins,losses,unknowns,aborted=s.attempts+1,s.wins,s.losses,s.unknowns,s.aborted
                if signal.fight_result=='VICTORY':wins+=1
                elif signal.fight_result=='DEFEAT':losses+=1
                elif signal.fight_result=='UNKNOWN':unknowns+=1
                else:aborted+=1
                stop_reason=None
                if wins>=self.plan.config.target_wins:stop_reason='TARGET_WINS_REACHED'
                elif signal.fight_result=='DEFEAT' and self.plan.config.stop_on_loss:stop_reason='LOSS_CONFIRMED'
                elif signal.fight_result=='UNKNOWN' and self.plan.config.stop_on_unknown:stop_reason='OUTCOME_UNKNOWN'
                elif attempts>=self.plan.config.max_attempts:stop_reason='MAX_ATTEMPTS_REACHED'
                return self._transition('WORLD_REENTRY',signal,reason='FIGHT_OUTCOME_SUPERSEDES_RECOVERY',
                                        counters=(attempts,wins,losses,unknowns,aborted),
                                        counted=s.counted_fight_epochs+(s.fight_epoch,),
                                        goal_pending=stop_reason is not None,terminal_reason=stop_reason,
                                        resume_phase=None)
            if s.resume_phase=='WORLD_REENTRY' and signal.kind=='WORLD_REENTRY_PROVEN':
                if signal.fight_epoch!=s.fight_epoch:return WorkflowApplyResult('REJECTED',False,'FIGHT_EPOCH_MISMATCH',s,None)
                if s.goal_reached_pending_reentry:
                    terminal='COMPLETED' if s.terminal_reason=='TARGET_WINS_REACHED' else 'STOPPED'
                    return self._transition(terminal,signal,reason='WORLD_REENTRY_SUPERSEDES_RECOVERY',
                                            terminal_reason=s.terminal_reason,goal_pending=False,
                                            selected_encounter_id=None,selected_encounter_map_id=None,
                                            resume_phase=None)
                return self._transition('WORLD',signal,reason='WORLD_REENTRY_SUPERSEDES_RECOVERY',
                                        goal_pending=False,terminal_reason=None,
                                        selected_encounter_id=None,selected_encounter_map_id=None,
                                        resume_phase=None)
            if signal.kind=='RECOVERY_FAILED':
                return self._transition('BLOCKED',signal,reason='RECOVERY_FAILED',terminal_reason='RECOVERY_FAILED')
            if signal.kind=='RECOVERY_SUCCEEDED' and s.resume_phase:
                return self._transition(s.resume_phase,signal,reason='RECOVERY_SUCCEEDED',resume_phase=None)
            # Fight-end evidence can legitimately overtake watchdog recovery from
            # every phase in which the same authoritative FIGHT_ENDED proof is
            # accepted outside recovery.  Restricting this to READY/FIGHT_ACTIVE
            # strands an early-ended fight merely because its watchdog fired first.
            if signal.kind=='FIGHT_ENDED' and s.resume_phase in (
                'FIGHT_ENTRY','PARTY_JOIN','PLACEMENT','READY','FIGHT_ACTIVE'
            ):
                if signal.fight_epoch!=s.fight_epoch:return WorkflowApplyResult('REJECTED',False,'FIGHT_EPOCH_MISMATCH',s,None)
                return self._transition('FIGHT_END_RECONCILIATION',signal,reason='FIGHT_END_SUPERSEDES_RECOVERY',pending_action_id=None,resume_phase=None)
            return WorkflowApplyResult('REJECTED',False,'RECOVERY_SIGNAL_REQUIRED',s,None)
        if signal.kind=='START' and s.phase=='CREATED':
            return self._transition('PREFLIGHT',signal,reason='WORKFLOW_STARTED')
        if signal.kind=='PREFLIGHT_OK' and s.phase=='PREFLIGHT':
            return self._transition('WORLD',signal,reason='PREFLIGHT_PROVEN')
        if signal.kind=='WORLD_OBSERVED' and s.phase=='WORLD':
            # Fresh observation does not itself advance mission phase.
            return self._nonprogress(signal,'WORLD_OBSERVATION_REFRESH')
        if signal.kind=='ROUTE_STEP_PROVEN' and s.phase=='WORLD':
            return self._transition('WORLD',signal,reason='ROUTE_STEP_PROVEN',route_index=s.route_index+1)
        if signal.kind=='ENCOUNTER_SELECTED' and s.phase=='WORLD':
            if len(s.started_fight_epochs)>=self.plan.config.max_attempts:
                return self._transition('STOPPED',signal,reason='MAX_ATTEMPTS_REACHED',terminal_reason='MAX_ATTEMPTS_REACHED')
            return self._transition('ENCOUNTER_SELECTED',signal,reason='ENCOUNTER_SELECTED',
                                    selected_encounter_id=signal.encounter_id,selected_encounter_map_id=signal.encounter_map_id)
        if signal.kind=='FIGHT_ENTRY_PROVEN' and s.phase=='ENCOUNTER_SELECTED':
            if signal.fight_epoch is None or signal.fight_epoch<=s.fight_epoch or signal.fight_epoch in s.started_fight_epochs:
                return WorkflowApplyResult('REJECTED',False,'NEW_FIGHT_EPOCH_REQUIRED',s,None)
            return self._transition('FIGHT_ENTRY',signal,reason='FIGHT_ENTRY_PROVEN',fight_epoch=signal.fight_epoch,started=s.started_fight_epochs+(signal.fight_epoch,))
        if signal.kind=='FIGHT_ENDED' and s.phase in ('FIGHT_ENTRY','PARTY_JOIN','PLACEMENT','READY'):
            if signal.fight_epoch!=s.fight_epoch:return WorkflowApplyResult('REJECTED',False,'FIGHT_EPOCH_MISMATCH',s,None)
            return self._transition('FIGHT_END_RECONCILIATION',signal,reason='FIGHT_END_BEFORE_ACTIVE',pending_action_id=None)
        phase_signal={'FIGHT_ENTRY':'PARTY_JOIN_PROVEN','PARTY_JOIN':'PLACEMENT_PROVEN','PLACEMENT':'READY_PROVEN','READY':'FIRST_TURN_PROVEN'}
        phase_next={'FIGHT_ENTRY':'PARTY_JOIN','PARTY_JOIN':'PLACEMENT','PLACEMENT':'READY','READY':'FIGHT_ACTIVE'}
        if s.phase in phase_signal and signal.kind==phase_signal[s.phase]:
            if signal.fight_epoch!=s.fight_epoch:return WorkflowApplyResult('REJECTED',False,'FIGHT_EPOCH_MISMATCH',s,None)
            return self._transition(phase_next[s.phase],signal,reason=signal.kind)
        if s.phase=='FIGHT_ACTIVE':
            if signal.kind=='FIGHT_ENDED':
                if signal.fight_epoch!=s.fight_epoch:return WorkflowApplyResult('REJECTED',False,'FIGHT_EPOCH_MISMATCH',s,None)
                return self._transition('FIGHT_END_RECONCILIATION',signal,reason='FIGHT_END_PROVEN',pending_action_id=None)
        if s.phase=='FIGHT_END_RECONCILIATION' and signal.kind=='FIGHT_OUTCOME':
            if signal.fight_epoch!=s.fight_epoch:return WorkflowApplyResult('REJECTED',False,'FIGHT_EPOCH_MISMATCH',s,None)
            if s.fight_epoch in s.counted_fight_epochs:
                return self._nonprogress(signal,'FIGHT_OUTCOME_ALREADY_COUNTED','DUPLICATE')
            attempts,wins,losses,unknowns,aborted=s.attempts+1,s.wins,s.losses,s.unknowns,s.aborted
            if signal.fight_result=='VICTORY':wins+=1
            elif signal.fight_result=='DEFEAT':losses+=1
            elif signal.fight_result=='UNKNOWN':unknowns+=1
            else:aborted+=1
            stop_reason=None
            if wins>=self.plan.config.target_wins:stop_reason='TARGET_WINS_REACHED'
            elif signal.fight_result=='DEFEAT' and self.plan.config.stop_on_loss:stop_reason='LOSS_CONFIRMED'
            elif signal.fight_result=='UNKNOWN' and self.plan.config.stop_on_unknown:stop_reason='OUTCOME_UNKNOWN'
            elif attempts>=self.plan.config.max_attempts:stop_reason='MAX_ATTEMPTS_REACHED'
            return self._transition('WORLD_REENTRY',signal,reason='FIGHT_OUTCOME_COUNTED',counters=(attempts,wins,losses,unknowns,aborted),counted=s.counted_fight_epochs+(s.fight_epoch,),goal_pending=stop_reason is not None,terminal_reason=stop_reason)
        if s.phase=='WORLD_REENTRY' and signal.kind=='WORLD_REENTRY_PROVEN':
            if signal.fight_epoch!=s.fight_epoch:return WorkflowApplyResult('REJECTED',False,'FIGHT_EPOCH_MISMATCH',s,None)
            if s.goal_reached_pending_reentry:
                terminal='COMPLETED' if s.terminal_reason=='TARGET_WINS_REACHED' else 'STOPPED'
                return self._transition(terminal,signal,reason='WORLD_REENTRY_TERMINAL',terminal_reason=s.terminal_reason,goal_pending=False,
                                        selected_encounter_id=None,selected_encounter_map_id=None)
            return self._transition('WORLD',signal,reason='WORLD_REENTRY_PROVEN',goal_pending=False,terminal_reason=None,
                                    selected_encounter_id=None,selected_encounter_map_id=None)
        return WorkflowApplyResult('REJECTED',False,f'UNEXPECTED_SIGNAL:{s.phase}:{signal.kind}',s,None)
