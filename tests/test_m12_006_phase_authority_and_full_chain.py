from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from anka_app.zero_input_integration import ZeroInputQ9Scenario
from anka_contracts.coordination import PartyRosterMember, MemberPartyObservation
from anka_coordination.coordinator import PartyCoordinatorService
from anka_workflow.engine import MissionWorkflow
from tests.test_m9_m10_q6 import mission, sig
from tests.test_m11_execution import (
    command, state, permit, client, StatePort, ClientPort, MechanicsPort, CoordinationPort,
)
from anka_contracts.mechanics import MechanicsResult
from anka_execution.arbiter import HostInputArbiter
from anka_execution.definitive_ledger import DefinitiveExecutionLedger
from anka_execution.drivers.fake_input import FakePhysicalInputDriver
from anka_execution.service import DefinitiveExecutionService


ROSTER=(PartyRosterMember('acct-cra','client-cra',41,'leader'),PartyRosterMember('acct-enu','client-enu',42,'follower'))

class _ExecutionHarness(unittest.TestCase):
    """M12_006 execution fixture without inheriting M11's test methods.

    Reusing the M11Case TestCase directly caused unittest to rediscover every
    inherited M11 test in this module, defeating exact test-inventory checks.
    """
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)

    def make(self,c,*,driver=None,states=None,clients=None,mechanics=None,permits=None,clock=None,arm=True):
        ledger=DefinitiveExecutionLedger(Path(self.temp.name)/f'{c.action_id}.sqlite3')
        arb=HostInputArbiter();drv=driver or FakePhysicalInputDriver('sent')
        svc=DefinitiveExecutionService(
            run_id='run-m11',run_generation=2,ledger=ledger,arbiter=arb,
            state_reader=StatePort(*(states or (state(c),))),
            client=ClientPort(*(clients or (client(c),))),
            mechanics=MechanicsPort(*(mechanics or (MechanicsResult('LEGAL'),))),
            coordination=CoordinationPort(*(permits or (permit(c),))),
            driver=drv,clock_ns=clock or (lambda:50),
        )
        if arm:svc.arm(authority_generation=9)
        return svc,ledger,drv,arb


def phase_obs(n:int,account:str,*,placed=False,ready=False):
    actor=41 if account=='acct-cra' else 42
    return MemberPartyObservation(
        f'coordobs-phase-{n}',account,'client-cra' if account=='acct-cra' else 'client-enu',actor,
        n,n,1,0,'fight-phase',190580738,'PLACEMENT',None,True,placed,ready,'HEALTHY',(f'phase-evidence-{n}',),False,
    )


class TestPhaseAwareCoordination(unittest.TestCase):
    def test_placement_and_ready_do_not_require_first_turn(self):
        c=PartyCoordinatorService('party-main',ROSTER)
        c.observe(phase_obs(1,'acct-cra'));c.observe(phase_obs(2,'acct-enu'))
        self.assertFalse(c.turn_permit('party-main','acct-cra').allowed)
        self.assertEqual(c.turn_permit('party-main','acct-cra').reason,'READY_BARRIER_UNSATISFIED')
        self.assertTrue(c.action_permit('party-main','acct-cra','PLACEMENT').allowed)
        self.assertTrue(c.action_permit('party-main','acct-enu','PLACEMENT').allowed)

        c.observe(phase_obs(3,'acct-cra',placed=True));c.observe(phase_obs(4,'acct-enu',placed=True))
        self.assertTrue(c.snapshot().placement_barrier.satisfied)
        self.assertTrue(c.action_permit('party-main','acct-cra','READY').allowed)
        self.assertTrue(c.action_permit('party-main','acct-enu','READY').allowed)
        self.assertFalse(c.turn_permit('party-main','acct-cra').allowed)

    def test_scope_is_fail_closed_and_world_is_not_misattributed_to_coordination(self):
        c=PartyCoordinatorService('party-main',ROSTER)
        c.observe(phase_obs(1,'acct-cra'));c.observe(phase_obs(2,'acct-enu'))
        self.assertEqual(c.action_permit('party-main','acct-cra','READY').reason,'PLACEMENT_BARRIER_UNSATISFIED')
        self.assertEqual(c.action_permit('party-main','acct-cra','WORLD').reason,'WORLD_AUTHORITY_NOT_OWNED_BY_COORDINATION')
        with self.assertRaisesRegex(Exception,'INVALID_ACTION_PERMIT_SCOPE'):
            c.action_permit('party-main','acct-cra','MAGIC')


class TestPreTurnWorkflowFence(unittest.TestCase):
    def _party_join_phase(self):
        w=MissionWorkflow('run-phase',mission())
        for e in (sig(1,'START',0),sig(2,'PREFLIGHT_OK',1),sig(3,'ENCOUNTER_SELECTED',2),sig(4,'FIGHT_ENTRY_PROVEN',3,fight=1),sig(5,'PARTY_JOIN_PROVEN',4,fight=1)):
            self.assertEqual(w.apply(e).status,'APPLIED')
        self.assertEqual(w.snapshot().phase,'PARTY_JOIN')
        return w

    def test_phase_transition_cannot_erase_pending_placement_action(self):
        w=self._party_join_phase();aid='action-'+'a'*24
        self.assertEqual(w.apply(sig(6,'ACTION_SUBMITTED',5,fight=1,action=aid)).status,'APPLIED')
        blocked=w.apply(sig(7,'PLACEMENT_PROVEN',6,fight=1))
        self.assertEqual((blocked.status,blocked.reason),('REJECTED','PENDING_ACTION_RECONCILIATION_REQUIRED'))
        settled=w.apply(sig(8,'ACTION_OUTCOME',7,fight=1,action=aid,status='SETTLED_SUCCESS'))
        self.assertIsNone(settled.snapshot.pending_action_id)
        self.assertEqual(w.apply(sig(9,'PLACEMENT_PROVEN',8,fight=1)).snapshot.phase,'PLACEMENT')

    def test_pending_preturn_action_timeout_blocks_instead_of_retrying_recovery(self):
        w=self._party_join_phase();aid='action-'+'b'*24
        w.apply(sig(6,'ACTION_SUBMITTED',5,fight=1,action=aid))
        deadline=w.snapshot().watchdog_deadline_tick
        out=w.apply(sig(7,'WATCHDOG',deadline+1))
        self.assertEqual(out.snapshot.phase,'BLOCKED')
        self.assertEqual(out.snapshot.terminal_reason,'WORKFLOW_PENDING_ACTION_TIMEOUT_REQUIRES_RECONCILIATION')


class TestExecutionAuthorityScope(_ExecutionHarness):
    def test_execution_rejects_scope_mismatch_before_driver(self):
        c=replace(command(990,kind='MOVE'),authority_scope='PLACEMENT')
        wrong=permit(c,scope='TURN')
        svc,_,driver,_=self.make(c,states=(state(c,turn_owner_actor_id=None),),permits=(wrong,))
        out=svc.submit(c)
        self.assertEqual(out.reason,'COORDINATION_AUTHORITY_SCOPE_MISMATCH')
        self.assertEqual(driver.call_count,0)


class TestQ9PreTurnRealChain(unittest.TestCase):
    def test_prepare_first_turn_executes_and_settles_placement_and_ready(self):
        with TemporaryDirectory() as td:
            s=ZeroInputQ9Scenario(Path(td))
            try:
                snap=s.prepare_first_turn()
                self.assertEqual(snap.phase,'FIGHT_ACTIVE')
                rows=s.ledger.audit()
                self.assertEqual(len(rows),8)
                commands=[s.ledger.get_command(x.action_id) for x in rows]
                self.assertEqual(
                    [c.authority_scope for c in commands],
                    ['WORLD','WORLD','FIGHT_ENTRY','JOIN','PLACEMENT','PLACEMENT','READY','READY'],
                )
                self.assertTrue(all(x.status=='SETTLED_SUCCESS' for x in rows))
                self.assertEqual(s.driver.call_count,8)
                self.assertEqual(s.execution.physical_input_count,0)
            finally:s.close()


if __name__=='__main__':unittest.main()

class TestExactJoinTargetAuthority(unittest.TestCase):
    def test_join_permit_is_bound_to_exact_fight_id_epoch_and_map(self):
        from dataclasses import replace
        from anka_app.zero_input_integration import CRA,ENU,PARTY,WORLD_MAP
        with TemporaryDirectory() as td:
            s=ZeroInputQ9Scenario(Path(td))
            try:
                s._signal('START');s._signal('PREFLIGHT_OK')
                for acct in (CRA,ENU):s._bootstrap_world_account(acct)
                for acct in (CRA,ENU):s._run_world_move(acct,WORLD_MAP+1)
                s._signal('ROUTE_STEP_PROVEN')
                encounter_id='encounter-q9-join-bind';encounter_map_id=WORLD_MAP+1
                s._signal('ENCOUNTER_SELECTED',encounter_id=encounter_id,encounter_map_id=encounter_map_id)
                s._run_fight_entry(CRA,encounter_id,encounter_map_id)
                s._signal('FIGHT_ENTRY_PROVEN',fight_epoch=1)
                s._coord_obs(CRA,'JOIN');s._coord_join_target(ENU)

                frame=s._join_frame(ENU);planned=s.planner.plan(frame)
                self.assertEqual(planned.disposition,'PLAN');plan=planned.plan
                good=s.authority.permit_for_plan(PARTY,frame,plan,'JOIN')
                self.assertTrue(good.allowed)

                wrong_id=replace(plan,semantic_target=tuple((k,'fight-wrong') if k=='target_fight_id' else (k,v) for k,v in plan.semantic_target))
                denied=s.authority.permit_for_plan(PARTY,frame,wrong_id,'JOIN')
                self.assertFalse(denied.allowed);self.assertEqual(denied.reason,'JOIN_TARGET_FIGHT_ID_MISMATCH')

                wrong_epoch=replace(plan,semantic_target=tuple((k,'2') if k=='target_fight_epoch' else (k,v) for k,v in plan.semantic_target))
                denied=s.authority.permit_for_plan(PARTY,frame,wrong_epoch,'JOIN')
                self.assertFalse(denied.allowed);self.assertEqual(denied.reason,'JOIN_TARGET_FIGHT_EPOCH_MISMATCH')

                wrong_map=replace(plan,semantic_target=plan.semantic_target+(('map_id','999999'),))
                denied=s.authority.permit_for_plan(PARTY,frame,wrong_map,'JOIN')
                self.assertFalse(denied.allowed);self.assertEqual(denied.reason,'JOIN_TARGET_MAP_MISMATCH')
            finally:s.close()

class TestWorkflowObserverIsolation(unittest.TestCase):
    def test_broken_observer_cannot_change_committed_workflow_transition(self):
        class BrokenObserver:
            def record(self,*a,**k):raise RuntimeError('observer exploded')
        w=MissionWorkflow('run-observer-safe',mission(),observer=BrokenObserver())
        out=w.apply(sig(1,'START',0))
        self.assertEqual(out.status,'APPLIED')
        self.assertEqual(w.snapshot().phase,'PREFLIGHT')

class TestAuthorizationBlockDiagnostics(unittest.TestCase):
    def test_ready_before_placement_records_exact_authority_block_reason(self):
        from anka_app.zero_input_integration import CRA,ENU,WORLD_MAP
        with TemporaryDirectory() as td:
            s=ZeroInputQ9Scenario(Path(td))
            try:
                s._signal('START');s._signal('PREFLIGHT_OK')
                for acct in (CRA,ENU):s._bootstrap_world_account(acct)
                for acct in (CRA,ENU):s._run_world_move(acct,WORLD_MAP+1)
                s._signal('ROUTE_STEP_PROVEN')
                encounter_id='encounter-q9-auth-block';encounter_map_id=WORLD_MAP+1
                s._signal('ENCOUNTER_SELECTED',encounter_id=encounter_id,encounter_map_id=encounter_map_id)
                s._run_fight_entry(CRA,encounter_id,encounter_map_id);s._signal('FIGHT_ENTRY_PROVEN',fight_epoch=1)
                s._coord_obs(CRA,'JOIN');s._coord_join_target(ENU);s._run_join(ENU);s._signal('PARTY_JOIN_PROVEN',fight_epoch=1)
                frame=s._phase_frame(CRA,'READY')
                out=s.controller.request('party-q9',frame)
                self.assertEqual(out.status,'WAIT')
                self.assertEqual(out.reason,'COORDINATION_PLACEMENT_BARRIER_UNSATISFIED')
                event=next(e for e in reversed(s.observer.recent) if e['event_name']=='workflow.action_authorization_blocked')
                self.assertEqual(event['failure_code'],'COORDINATION_PLACEMENT_BARRIER_UNSATISFIED')
                self.assertEqual(event['payload']['scope'],'READY')
                self.assertEqual(event['account_id'],CRA[0])
            finally:s.close()

class _CaptureObserver:
    def __init__(self):self.events=[]
    def record(self,name,**kwargs):
        self.events.append((name,kwargs));return 'RECORDED'

class TestExecutionFailureObservability(_ExecutionHarness):
    def test_final_guard_rejection_is_explicitly_observable(self):
        from tests.test_m11_execution import client
        c=command(1600);first=client(c);second=client(c,attestation_id='clientatt-drift-observed',window_generation=99)
        svc,_,driver,_=self.make(c,clients=(first,second));obs=_CaptureObserver();svc._observer=obs
        out=svc.submit(c)
        self.assertEqual(out.status,'REJECTED_NOT_SENT');self.assertEqual(driver.call_count,0)
        row=next(k for n,k in obs.events if n=='execution.final_guard_rejected')
        self.assertEqual(row['failure_code'],'EXTERNAL_CONTEXT_CHANGED_AFTER_PREPARE')
        self.assertEqual(row['boundary'],'execution.pre_input_revalidation')

    def test_ignored_outcome_records_why_it_was_not_accepted(self):
        from dataclasses import replace
        from tests.test_m11_execution import evidence
        c=command(1601);svc,_,_,_=self.make(c);obs=_CaptureObserver();svc._observer=obs
        self.assertEqual(svc.submit(c).status,'PENDING')
        wrong=replace(evidence(c,1601),account_id='acct-enu')
        out=svc.reconcile(c.action_id,wrong)
        self.assertEqual(out.status,'PENDING')
        row=next(k for n,k in obs.events if n=='execution.outcome_ignored')
        self.assertTrue(row['failure_code'])
        self.assertEqual(row['payload']['evidence_result'],'CONFIRMATION')
        self.assertTrue(row['payload']['evidence_authoritative'])

    def test_arbiter_release_failure_records_run_level_safety_fault(self):
        c=command(1602);svc,_,_,arb=self.make(c);obs=_CaptureObserver();svc._observer=obs
        def broken_release(_lease):raise RuntimeError('release failed')
        arb.release=broken_release
        out=svc.submit(c)
        self.assertEqual(out.status,'PENDING')
        self.assertFalse(svc.armed)
        row=next(k for n,k in obs.events if n=='execution.safety_fault')
        self.assertEqual(row['failure_code'],'INPUT_ARBITER_RELEASE_FAILED:RuntimeError')
        self.assertEqual(row['boundary'],'execution.input_arbitration')


class TestM12006HealthyChainDiagnosticCoverage(unittest.TestCase):
    def test_happy_path_has_zero_diagnostic_loss_and_all_authoritative_owners(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from anka_app.zero_input_integration import ZeroInputQ9Scenario
        with TemporaryDirectory() as td:
            scenario=ZeroInputQ9Scenario(Path(td))
            try:
                result=scenario.happy_path()
                self.assertEqual(scenario.observer.dropped,0)
                events=list(scenario.observer.recent)
                owners={e.get('owner_system') for e in events}
                self.assertTrue({'anka_protocol','anka_canonical','anka_live_state','anka_coordination',
                                 'anka_decision','anka_workflow','anka_execution','anka_app'} <= owners)
                for name in ('workflow.action_requested','execution.admitted','execution.input_sent','execution.outcome_settled'):
                    rows=[e for e in events if e.get('event_name')==name]
                    self.assertTrue(rows,name)
                    self.assertTrue(all(e.get('action_id','').startswith('action-') for e in rows),name)
                # The trace created by Workflow must continue across Execution.
                requested={e['action_id']:e['trace_id'] for e in events if e.get('event_name')=='workflow.action_requested'}
                for e in events:
                    if e.get('owner_system')=='anka_execution' and e.get('action_id') in requested:
                        self.assertEqual(e.get('trace_id'),requested[e['action_id']])
            finally:
                scenario.close()

class TestM12006WorkflowRealDiagnosticTransitions(unittest.TestCase):
    def test_real_workflow_engine_publishes_phase_transition_events(self):
        from pathlib import Path
        import tempfile
        from anka_app.zero_input_integration import ZeroInputQ9Scenario
        with tempfile.TemporaryDirectory() as td:
            scenario=ZeroInputQ9Scenario(Path(td))
            try:
                scenario._signal('START')
                scenario._signal('PREFLIGHT_OK')
                events=[e for e in scenario.observer.recent if e.get('event_name')=='workflow.phase_changed']
                self.assertEqual(len(events),2)
                self.assertEqual(events[0]['payload']['from_phase'],'CREATED')
                self.assertEqual(events[0]['payload']['to_phase'],'PREFLIGHT')
                self.assertEqual(events[1]['payload']['from_phase'],'PREFLIGHT')
                self.assertEqual(events[1]['payload']['to_phase'],'WORLD')
                self.assertEqual(events[0]['owner_system'],'anka_workflow')
            finally:
                scenario.close()
