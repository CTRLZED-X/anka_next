from __future__ import annotations
import ast
from pathlib import Path
import unittest

from anka_contracts.action import ActionOutcome
from anka_contracts.coordination import MemberPartyObservation, PartyRosterMember
from anka_contracts.decision import DecisionFrame
from anka_contracts.mechanics import MechanicsResult
from anka_contracts.workflow import EncounterCandidate, MissionConfigSpec, WorkflowSignal
from anka_coordination.coordinator import PartyCoordinatorService
from anka_decision.planner import DeterministicPlanner
from anka_decision.policies import load_legacy_profiles
from anka_workflow.compiler import compile_mission, MissionCompileError
from anka_workflow.engine import MissionWorkflow
from anka_workflow.integration import WorkflowTurnController

ROOT=Path(__file__).resolve().parents[1]
ROUTES=ROOT/'assets/workflow/routes.json'

ROSTER=(PartyRosterMember('acct-cra','client-cra',41,'leader'),PartyRosterMember('acct-enu','client-enu',42,'follower'))

def obs(n,account,*,cursor=None,revision=None,fight_epoch=1,turn_epoch=1,fight_id='fight-1',map_id=190580738,phase='FIGHT_ACTIVE',owner=41,joined=True,placed=True,ready=True,health='HEALTHY',gap=False,observation_id=None):
    actor=41 if account=='acct-cra' else 42
    return MemberPartyObservation(observation_id or f'coordobs-{n}',account,'client-cra' if account=='acct-cra' else 'client-enu',actor,
        n if cursor is None else cursor,n if revision is None else revision,fight_epoch,turn_epoch,fight_id,map_id,phase,owner,joined,placed,ready,health,(f'evidence-{n}',),gap)

def mission(*,target=2,max_attempts=3,stop_loss=False,stop_unknown=True,watchdog=5,recovery=1):
    cfg=MissionConfigSpec('sufokia_direction_cycle',6,8,target,max_attempts,stop_loss,stop_unknown,'a'*64)
    return compile_mission(cfg,ROUTES,watchdog_budget_ticks=watchdog,recovery_budget=recovery)

def sig(n,kind,tick,*,fight=None,result=None,action=None,status=None,recovery_generation=None):
    return WorkflowSignal(f'wfsig-{n}',kind,tick,(f'ev-{n}',),fight,result,action,status,recovery_generation=recovery_generation)

def advance_to_active(w:MissionWorkflow,fight=1,start=0):
    events=[sig(start+1,'START',0),sig(start+2,'PREFLIGHT_OK',1),sig(start+3,'ENCOUNTER_SELECTED',2),
            sig(start+4,'FIGHT_ENTRY_PROVEN',3,fight=fight),sig(start+5,'PARTY_JOIN_PROVEN',4,fight=fight),
            sig(start+6,'PLACEMENT_PROVEN',5,fight=fight),sig(start+7,'READY_PROVEN',6,fight=fight),
            sig(start+8,'FIRST_TURN_PROVEN',7,fight=fight)]
    for e in events:
        r=w.apply(e); assert r.status=='APPLIED',r.reason
    return start+8

class TestM9Coordination(unittest.TestCase):
    def test_same_fight_barriers_and_turn_permit(self):
        c=PartyCoordinatorService('party-main',ROSTER)
        self.assertFalse(c.turn_permit('party-main','acct-cra').allowed)
        c.observe(obs(1,'acct-cra',joined=True,placed=False,ready=False))
        self.assertFalse(c.snapshot().same_fight_proven)
        c.observe(obs(2,'acct-enu',joined=True,placed=False,ready=False))
        s=c.snapshot();self.assertTrue(s.same_fight_proven);self.assertTrue(s.join_barrier.satisfied);self.assertFalse(s.placement_barrier.satisfied)
        c.observe(obs(3,'acct-cra',placed=True,ready=True,cursor=3,revision=3))
        c.observe(obs(4,'acct-enu',placed=True,ready=False,cursor=4,revision=4))
        self.assertFalse(c.snapshot().ready_barrier.satisfied)
        c.observe(obs(5,'acct-enu',placed=True,ready=True,cursor=5,revision=5))
        s=c.snapshot();self.assertEqual((s.phase,s.turn_owner_account_id),('TURN_ACTIVE','acct-cra'))
        self.assertTrue(c.turn_permit('party-main','acct-cra').allowed)
        self.assertEqual(c.turn_permit('party-main','acct-enu').reason,'NOT_CURRENT_TURN_OWNER')

    def test_turn_permit_requires_positive_epoch_from_every_required_member(self):
        c=PartyCoordinatorService('party-main',ROSTER)
        c.observe(obs(1,'acct-cra',turn_epoch=1,owner=41))
        c.observe(obs(2,'acct-enu',turn_epoch=0,owner=41))
        snap=c.snapshot()
        self.assertEqual(snap.phase,'WAIT_TURN_OWNER')
        self.assertIsNone(snap.turn_owner_account_id)
        self.assertIn('TURN_OWNER_NOT_COHERENT',snap.missing_evidence)
        permit=c.turn_permit('party-main','acct-cra')
        self.assertFalse(permit.allowed)
        self.assertEqual(permit.reason,'TURN_OWNER_UNPROVEN')

    def test_handoff_requires_both_accounts_to_observe_new_owner_epoch(self):
        c=PartyCoordinatorService('party-main',ROSTER)
        c.observe(obs(1,'acct-cra'));c.observe(obs(2,'acct-enu'))
        old=c.turn_permit('party-main','acct-cra');self.assertTrue(old.allowed)
        c.observe(obs(3,'acct-cra',turn_epoch=2,owner=42,cursor=3,revision=3))
        mid=c.snapshot();self.assertIsNone(mid.turn_owner_account_id);self.assertIn('TURN_OWNER_SKEW',mid.conflicting_evidence)
        self.assertFalse(c.turn_permit('party-main','acct-enu').allowed)
        c.observe(obs(4,'acct-enu',turn_epoch=2,owner=42,cursor=4,revision=4))
        new=c.turn_permit('party-main','acct-enu');self.assertTrue(new.allowed);self.assertGreater(new.permit_generation,old.permit_generation)
        self.assertFalse(c.turn_permit('party-main','acct-cra').allowed)

    def test_duplicate_and_cursor_only_refresh_do_not_fake_semantic_progress(self):
        c=PartyCoordinatorService('party-main',ROSTER)
        a=c.observe(obs(1,'acct-cra'));self.assertTrue(a.semantic_progress)
        d=c.observe(obs(1,'acct-cra'));self.assertEqual((d.status,d.semantic_progress),('DUPLICATE',False))
        before=c.snapshot().permit_generation
        refresh=obs(2,'acct-cra',cursor=2,revision=2)
        u=c.observe(refresh);self.assertFalse(u.semantic_progress);self.assertEqual(u.snapshot.permit_generation,before)

    def test_conflicting_fight_map_capture_gap_and_reconnect_fail_closed(self):
        c=PartyCoordinatorService('party-main',ROSTER)
        c.observe(obs(1,'acct-cra'));c.observe(obs(2,'acct-enu',map_id=190581250))
        s=c.snapshot();self.assertEqual(s.phase,'BLOCKED');self.assertIn('FIGHT_MAP_CONFLICT',s.conflicting_evidence)
        self.assertFalse(c.turn_permit('party-main','acct-cra').allowed)
        c2=PartyCoordinatorService('party-main',ROSTER)
        c2.observe(obs(3,'acct-cra'));c2.observe(obs(4,'acct-enu',gap=True))
        self.assertFalse(c2.snapshot().same_fight_proven);self.assertEqual(c2.turn_permit('party-main','acct-cra').reason,'SAME_FIGHT_UNPROVEN')
        bad=MemberPartyObservation('coordobs-x','acct-enu','client-restarted',42,5,5,1,1,'fight-1',190580738,'FIGHT_ACTIVE',41,True,True,True,'HEALTHY',('evidence-x',),False)
        self.assertEqual(c2.observe(bad).reason,'MEMBER_IDENTITY_MISMATCH')

    def test_regressions_and_same_revision_conflict_are_rejected(self):
        c=PartyCoordinatorService('party-main',ROSTER);c.observe(obs(5,'acct-cra',cursor=10,revision=10))
        self.assertEqual(c.observe(obs(6,'acct-cra',cursor=9,revision=11)).reason,'MEMBER_CURSOR_REGRESSION')
        conflict=obs(7,'acct-cra',cursor=10,revision=10,ready=False)
        self.assertEqual(c.observe(conflict).reason,'SAME_REVISION_CONFLICT')

    def test_same_revision_duplicate_with_new_transport_identity_is_idempotent(self):
        c=PartyCoordinatorService('party-main',ROSTER);base=obs(1,'acct-cra',cursor=10,revision=10);c.observe(base)
        duplicate=obs(2,'acct-cra',cursor=10,revision=10)
        r=c.observe(duplicate);self.assertEqual((r.status,r.reason,r.semantic_progress),('DUPLICATE','SAME_REVISION_IDEMPOTENT',False))

    def test_observation_id_cache_is_bounded_without_replaying_stale_state(self):
        c=PartyCoordinatorService('party-main',ROSTER)
        c._max_seen_observations=3
        first=obs(100,'acct-cra',cursor=100,revision=100,observation_id='coordobs-old')
        self.assertEqual(c.observe(first).status,'APPLIED')
        for i in range(101,105):
            self.assertEqual(c.observe(obs(i,'acct-cra',cursor=i,revision=i,observation_id=f'coordobs-{i}')).status,'APPLIED')
        self.assertLessEqual(len(c._seen),3)
        # The old exact id may have left the diagnostic conflict cache, but its
        # stale cursor can never regain coordination authority.
        replay=c.observe(first)
        self.assertEqual(replay.status,'REJECTED')
        self.assertEqual(replay.reason,'MEMBER_CURSOR_REGRESSION')

    def test_restart_generation_invalidates_prior_permit_namespace(self):
        c=PartyCoordinatorService('party-main',ROSTER,party_generation=7)
        c.observe(obs(1,'acct-cra'));c.observe(obs(2,'acct-enu'))
        old=c.turn_permit('party-main','acct-cra')
        self.assertTrue(old.allowed);self.assertEqual(old.party_generation,7)
        c.invalidate_ephemeral_permits()
        fresh=c.turn_permit('party-main','acct-cra')
        self.assertTrue(fresh.allowed)
        self.assertNotEqual((old.party_generation,old.permit_generation),(fresh.party_generation,fresh.permit_generation))
        restarted=PartyCoordinatorService('party-main',ROSTER,party_generation=8)
        restarted.observe(obs(11,'acct-cra'));restarted.observe(obs(12,'acct-enu'))
        replacement=restarted.turn_permit('party-main','acct-cra')
        self.assertEqual(replacement.party_generation,8)
        self.assertNotEqual(old.party_generation,replacement.party_generation)

    def test_generic_three_member_roster(self):
        roster=ROSTER+(PartyRosterMember('acct-feca','client-feca',43,'follower'),)
        c=PartyCoordinatorService('party-three',roster)
        c.observe(obs(1,'acct-cra'))
        c.observe(obs(2,'acct-enu'))
        f=MemberPartyObservation('coordobs-3','acct-feca','client-feca',43,3,3,1,1,'fight-1',190580738,'FIGHT_ACTIVE',41,True,True,True,'HEALTHY',('evidence-3',),False)
        c.observe(f);self.assertTrue(c.snapshot().ready_barrier.satisfied);self.assertTrue(c.turn_permit('party-three','acct-cra').allowed)

class TestM10Workflow(unittest.TestCase):
    def test_signal_idempotence_history_fails_closed_before_unbounded_growth(self):
        w=MissionWorkflow('run-history-bound',mission(max_attempts=3))
        # Shrink only the test instance's production-derived ceiling so the
        # boundary can be exercised without thousands of synthetic transitions.
        w._signal_history_limit=3
        self.assertEqual(w.apply(sig(9001,'START',0)).snapshot.phase,'PREFLIGHT')
        self.assertEqual(w.apply(sig(9002,'PREFLIGHT_OK',1)).snapshot.phase,'WORLD')
        blocked=w.apply(sig(9003,'HEARTBEAT',2))
        self.assertEqual(blocked.snapshot.phase,'BLOCKED')
        self.assertEqual(blocked.snapshot.terminal_reason,'WORKFLOW_IDEMPOTENCE_HISTORY_EXHAUSTED')
        self.assertEqual(len(blocked.snapshot.processed_signal_ids),3)
        # Once terminal, later traffic cannot grow the exact replay fence.
        again=w.apply(sig(9004,'HEARTBEAT',3))
        self.assertEqual(again.status,'REJECTED')
        self.assertEqual(len(again.snapshot.processed_signal_ids),3)

    def test_compile_route_and_encounter_selection(self):
        p=mission();self.assertEqual(p.route.steps,('R','D','L','U'));self.assertEqual(p.route.start_x,7);self.assertEqual(p.route.start_y,-12)
        w=MissionWorkflow('run-q6',p)
        pick=w.select_encounter((EncounterCandidate('encounter-c',8,1),EncounterCandidate('encounter-a',5,1),EncounterCandidate('encounter-b',6,1)))
        self.assertEqual(pick.encounter_id,'encounter-b')
        bad=MissionConfigSpec('missing_route',1,2,1,1,True,True,'b'*64)
        with self.assertRaises(MissionCompileError):compile_mission(bad,ROUTES)

    def test_world_fight_world_and_exact_counter_idempotence(self):
        w=MissionWorkflow('run-life',mission(target=2,max_attempts=3))
        advance_to_active(w,1)
        self.assertEqual(w.apply(sig(20,'FIGHT_ENDED',8,fight=1)).snapshot.phase,'FIGHT_END_RECONCILIATION')
        r=w.apply(sig(21,'FIGHT_OUTCOME',9,fight=1,result='VICTORY'));self.assertEqual((r.snapshot.attempts,r.snapshot.wins,r.snapshot.phase),(1,1,'WORLD_REENTRY'))
        dup=w.apply(sig(22,'FIGHT_OUTCOME',10,fight=1,result='VICTORY'));self.assertEqual(dup.status,'DUPLICATE');self.assertEqual(dup.snapshot.wins,1)
        self.assertEqual(w.apply(sig(23,'WORLD_REENTRY_PROVEN',11,fight=1)).snapshot.phase,'WORLD')
        self.assertEqual(w.apply(sig(24,'WORLD_REENTRY_PROVEN',12,fight=1)).status,'DUPLICATE')

    def test_route_progress_is_semantic_and_separate_from_fight_reentry(self):
        w=MissionWorkflow('run-route',mission())
        w.apply(sig(1,'START',0));w.apply(sig(2,'PREFLIGHT_OK',1))
        self.assertEqual(w.next_route_step(),'R')
        r=w.apply(sig(3,'ROUTE_STEP_PROVEN',2));self.assertTrue(r.semantic_progress);self.assertEqual(w.next_route_step(),'D')
        w.apply(sig(4,'ROUTE_STEP_PROVEN',3));w.apply(sig(5,'ROUTE_STEP_PROVEN',4));w.apply(sig(6,'ROUTE_STEP_PROVEN',5))
        self.assertEqual(w.next_route_step(),'R')

    def test_resume_preserves_counters_but_restarts_watchdog_and_rejects_pending_action(self):
        w=MissionWorkflow('run-resume',mission());advance_to_active(w,1)
        w.apply(sig(20,'FIGHT_ENDED',8,fight=1));w.apply(sig(21,'FIGHT_OUTCOME',9,fight=1,result='VICTORY'));w.apply(sig(22,'WORLD_REENTRY_PROVEN',10,fight=1))
        before=w.snapshot();resumed=MissionWorkflow.resume(w.plan,before,resume_tick=100)
        self.assertEqual((resumed.snapshot().wins,resumed.snapshot().phase),(1,'WORLD'));self.assertEqual(resumed.snapshot().watchdog_deadline_tick,105);self.assertGreater(resumed.snapshot().progress_generation,before.progress_generation)
        active=MissionWorkflow('run-resume-pending',mission());advance_to_active(active,1);active.apply(sig(30,'ACTION_SUBMITTED',8,fight=1,action='action-pending'))
        from anka_workflow.engine import WorkflowRejected
        with self.assertRaisesRegex(WorkflowRejected,'PENDING_ACTION'):MissionWorkflow.resume(active.plan,active.snapshot(),resume_tick=100)

    def test_resume_rejects_changed_mission_plan(self):
        w=MissionWorkflow('run-plan-bound',mission(watchdog=5,recovery=1))
        w.apply(sig(1,'START',0));w.apply(sig(2,'PREFLIGHT_OK',1))
        snapshot=w.snapshot()
        self.assertEqual(snapshot.plan_id,w.plan.plan_id)
        changed=mission(watchdog=6,recovery=1)
        self.assertNotEqual(changed.plan_id,w.plan.plan_id)
        from anka_workflow.engine import WorkflowRejected
        with self.assertRaisesRegex(WorkflowRejected,'RESUME_MISSION_PLAN_MISMATCH'):
            MissionWorkflow.resume(changed,snapshot,resume_tick=100)

    def test_fight_can_end_before_first_turn_and_still_requires_separate_outcome(self):
        w=MissionWorkflow('run-early-end',mission())
        for e in [sig(1,'START',0),sig(2,'PREFLIGHT_OK',1),sig(3,'ENCOUNTER_SELECTED',2),sig(4,'FIGHT_ENTRY_PROVEN',3,fight=1),sig(5,'PARTY_JOIN_PROVEN',4,fight=1),sig(6,'PLACEMENT_PROVEN',5,fight=1),sig(7,'READY_PROVEN',6,fight=1)]:w.apply(e)
        end=w.apply(sig(8,'FIGHT_ENDED',7,fight=1));self.assertEqual(end.snapshot.phase,'FIGHT_END_RECONCILIATION');self.assertEqual(end.snapshot.attempts,0)
        outcome=w.apply(sig(9,'FIGHT_OUTCOME',8,fight=1,result='UNKNOWN'));self.assertEqual((outcome.snapshot.attempts,outcome.snapshot.unknowns),(1,1))

    def test_target_wins_completes_only_after_world_reentry(self):
        w=MissionWorkflow('run-win',mission(target=1,max_attempts=2));advance_to_active(w,1)
        w.apply(sig(20,'FIGHT_ENDED',8,fight=1));out=w.apply(sig(21,'FIGHT_OUTCOME',9,fight=1,result='VICTORY'))
        self.assertEqual(out.snapshot.phase,'WORLD_REENTRY');self.assertEqual(out.snapshot.terminal_reason,'TARGET_WINS_REACHED')
        end=w.apply(sig(22,'WORLD_REENTRY_PROVEN',10,fight=1));self.assertEqual((end.snapshot.phase,end.snapshot.wins),('COMPLETED',1))

    def test_heartbeat_does_not_reset_ready_watchdog_and_recovery_is_bounded(self):
        w=MissionWorkflow('run-watch',mission(watchdog=5,recovery=1))
        for e in [sig(1,'START',0),sig(2,'PREFLIGHT_OK',1),sig(3,'ENCOUNTER_SELECTED',2),sig(4,'FIGHT_ENTRY_PROVEN',3,fight=1),sig(5,'PARTY_JOIN_PROVEN',4,fight=1),sig(6,'PLACEMENT_PROVEN',5,fight=1),sig(7,'READY_PROVEN',6,fight=1)]:w.apply(e)
        self.assertEqual(w.snapshot().phase,'READY');deadline=w.snapshot().watchdog_deadline_tick
        hb=w.apply(sig(8,'HEARTBEAT',deadline));self.assertFalse(hb.semantic_progress);self.assertEqual(w.snapshot().watchdog_deadline_tick,deadline)
        rec=w.apply(sig(9,'WATCHDOG',deadline+1));self.assertEqual(rec.snapshot.phase,'RECOVERING');self.assertEqual(rec.snapshot.recovery_budget_remaining,0)
        resume=w.apply(sig(10,'RECOVERY_SUCCEEDED',deadline+2,recovery_generation=rec.snapshot.active_recovery_generation));self.assertEqual(resume.snapshot.phase,'READY')
        blocked=w.apply(sig(11,'WATCHDOG',resume.snapshot.watchdog_deadline_tick+1));self.assertEqual(blocked.snapshot.phase,'BLOCKED');self.assertIn('WORKFLOW_TIMEOUT_READY',blocked.snapshot.terminal_reason)

    def test_repeated_recovery_timeout_preserves_original_resume_phase(self):
        w=MissionWorkflow('run-repeat-recovery',mission(watchdog=1,recovery=2))
        for e in [sig(1,'START',0),sig(2,'PREFLIGHT_OK',1),sig(3,'ENCOUNTER_SELECTED',2),sig(4,'FIGHT_ENTRY_PROVEN',3,fight=1),sig(5,'PARTY_JOIN_PROVEN',4,fight=1),sig(6,'PLACEMENT_PROVEN',5,fight=1),sig(7,'READY_PROVEN',6,fight=1)]:w.apply(e)
        self.assertEqual(w.snapshot().phase,'READY')
        first=w.apply(sig(8,'WATCHDOG',w.snapshot().watchdog_deadline_tick+1))
        self.assertEqual((first.snapshot.phase,first.snapshot.resume_phase,first.snapshot.recovery_budget_remaining),('RECOVERING','READY',1))
        second=w.apply(sig(9,'WATCHDOG',first.snapshot.watchdog_deadline_tick+1))
        self.assertEqual((second.snapshot.phase,second.snapshot.resume_phase,second.snapshot.recovery_budget_remaining),('RECOVERING','READY',0))
        resumed=w.apply(sig(10,'RECOVERY_SUCCEEDED',second.snapshot.phase_started_tick+1,recovery_generation=second.snapshot.active_recovery_generation))
        self.assertEqual(resumed.snapshot.phase,'READY')
        self.assertIsNone(resumed.snapshot.resume_phase)

    def test_late_fight_end_can_supersede_watchdog_recovery(self):
        w=MissionWorkflow('run-late',mission(watchdog=1,recovery=1));advance_to_active(w,1)
        rec=w.apply(sig(20,'WATCHDOG',w.snapshot().watchdog_deadline_tick+1));self.assertEqual(rec.snapshot.phase,'RECOVERING')
        ended=w.apply(sig(21,'FIGHT_ENDED',rec.snapshot.phase_started_tick+1,fight=1));self.assertEqual(ended.snapshot.phase,'FIGHT_END_RECONCILIATION')

    def test_pending_action_does_not_count_as_progress_and_uncertain_blocks(self):
        w=MissionWorkflow('run-action',mission());advance_to_active(w,1)
        sub=w.apply(sig(20,'ACTION_SUBMITTED',8,fight=1,action='action-1'));deadline=sub.snapshot.watchdog_deadline_tick
        p=w.apply(sig(21,'ACTION_OUTCOME',9,fight=1,action='action-1',status='PENDING'));self.assertFalse(p.semantic_progress);self.assertEqual(p.snapshot.watchdog_deadline_tick,deadline)
        settled=w.apply(sig(22,'ACTION_OUTCOME',10,fight=1,action='action-1',status='SETTLED_SUCCESS'));self.assertTrue(settled.semantic_progress);self.assertIsNone(settled.snapshot.pending_action_id)
        w.apply(sig(23,'ACTION_SUBMITTED',11,fight=1,action='action-2'))
        bad=w.apply(sig(24,'ACTION_OUTCOME',12,fight=1,action='action-2',status='UNCERTAIN'));self.assertEqual(bad.snapshot.phase,'BLOCKED');self.assertEqual(bad.snapshot.terminal_reason,'UNRESOLVED_ACTION_SIDE_EFFECT')

    def test_stop_policies_and_max_attempts(self):
        # Explicit loss policy
        w=MissionWorkflow('run-loss',mission(target=2,max_attempts=2,stop_loss=True));advance_to_active(w,1)
        w.apply(sig(20,'FIGHT_ENDED',8,fight=1));w.apply(sig(21,'FIGHT_OUTCOME',9,fight=1,result='DEFEAT'))
        self.assertEqual(w.apply(sig(22,'WORLD_REENTRY_PROVEN',10,fight=1)).snapshot.phase,'STOPPED')
        # Attempt budget with loss allowed
        w=MissionWorkflow('run-budget',mission(target=2,max_attempts=2,stop_loss=False,stop_unknown=False));advance_to_active(w,1)
        w.apply(sig(20,'FIGHT_ENDED',8,fight=1));w.apply(sig(21,'FIGHT_OUTCOME',9,fight=1,result='DEFEAT'));w.apply(sig(22,'WORLD_REENTRY_PROVEN',10,fight=1))
        for e in [sig(30,'ENCOUNTER_SELECTED',11),sig(31,'FIGHT_ENTRY_PROVEN',12,fight=2),sig(32,'PARTY_JOIN_PROVEN',13,fight=2),sig(33,'PLACEMENT_PROVEN',14,fight=2),sig(34,'READY_PROVEN',15,fight=2),sig(35,'FIRST_TURN_PROVEN',16,fight=2),sig(36,'FIGHT_ENDED',17,fight=2),sig(37,'FIGHT_OUTCOME',18,fight=2,result='DEFEAT')]:w.apply(e)
        self.assertEqual(w.apply(sig(38,'WORLD_REENTRY_PROVEN',19,fight=2)).snapshot.terminal_reason,'MAX_ATTEMPTS_REACHED')

    def test_stop_request_is_safe_from_active_phase(self):
        w=MissionWorkflow('run-stop',mission());advance_to_active(w,1)
        s=w.apply(sig(20,'STOP_REQUESTED',8));self.assertEqual((s.snapshot.phase,s.snapshot.terminal_reason),('STOPPED','STOP_REQUESTED'))
        self.assertEqual(w.apply(sig(21,'HEARTBEAT',9)).status,'REJECTED')

class LegalKernel:
    def __init__(self):self.calls=[]
    def validate_plan(self,frame,plan):self.calls.append((frame,plan));return MechanicsResult('LEGAL')
class ZeroInputExecutor:
    def __init__(self):self.commands=[];self.physical_input_count=0
    def submit(self,command):
        self.commands.append(command)
        return ActionOutcome(command.action_id,None,'REJECTED_NOT_SENT',(),True)

class TestQ6Integration(unittest.TestCase):
    def frame(self,account='acct-cra',actor=41,owner=41,turn=1):
        return DecisionFrame('frame-q6','run-q6',account,1,turn,'snap-'+'1'*32,50,'FIGHT_TURN',
            'client-cra' if account=='acct-cra' else 'client-enu','a'*64,'m7-r1','kernel-r5','legacy-r5198','cra' if account=='acct-cra' else 'enu',
            9 if account=='acct-cra' else 3,actor,owner,200,190580738,11,6,
            (('fight_phase','KNOWN'),('turn_owner','KNOWN'),('actor_cell','KNOWN'),('ap','KNOWN'),('mp','KNOWN'),('loadout','KNOWN'),('targets','KNOWN')),
            ((32435,3),) if account=='acct-cra' else ((32382,3),),(229,),(201,),(),0,128)

    def test_decision_coordination_workflow_execution_zero_input(self):
        coord=PartyCoordinatorService('party-main',ROSTER);coord.observe(obs(1,'acct-cra'));coord.observe(obs(2,'acct-enu'))
        kernel=LegalKernel();planner=DeterministicPlanner(kernel,load_legacy_profiles(ROOT/'assets/decision/legacy_r5198_spell_priorities.json'))
        executor=ZeroInputExecutor();ctl=WorkflowTurnController(planner,executor,coord)
        dispatch=ctl.request('party-main',self.frame())
        self.assertEqual((dispatch.status,dispatch.outcome_status),('SUBMITTED','REJECTED_NOT_SENT'));self.assertEqual(len(executor.commands),1);self.assertEqual(executor.physical_input_count,0)
        # ENU may not act until BOTH observations prove the handoff.
        coord.observe(obs(3,'acct-cra',turn_epoch=2,owner=42,cursor=3,revision=3))
        wait=ctl.request('party-main',self.frame('acct-enu',42,42,2));self.assertEqual(wait.status,'WAIT');self.assertEqual(len(executor.commands),1)
        coord.observe(obs(4,'acct-enu',turn_epoch=2,owner=42,cursor=4,revision=4))
        enu=ctl.request('party-main',self.frame('acct-enu',42,42,2));self.assertEqual(enu.status,'SUBMITTED');self.assertEqual(len(executor.commands),2);self.assertEqual(executor.physical_input_count,0)

    def test_architecture_boundaries(self):
        forbidden_coord=('anka_workflow','anka_decision','anka_execution','anka_client','anka_protocol','anka_capture','anka_live_state','anka_canonical')
        forbidden_flow=('anka_coordination','anka_decision','anka_execution','anka_client','anka_protocol','anka_capture','anka_live_state','anka_canonical')
        for package,forbidden in [('anka_coordination',forbidden_coord),('anka_workflow',forbidden_flow)]:
            for path in (ROOT/'src'/package).rglob('*.py'):
                tree=ast.parse(path.read_text());names=[]
                for n in ast.walk(tree):
                    if isinstance(n,ast.Import):names += [x.name for x in n.names]
                    elif isinstance(n,ast.ImportFrom):names.append(n.module or '')
                bad=[x for x in names if any(x==f or x.startswith(f+'.') for f in forbidden)]
                self.assertFalse(bad,(path,bad))

if __name__=='__main__':unittest.main()
