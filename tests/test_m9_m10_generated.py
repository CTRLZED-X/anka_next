"""Independent small-state oracles for Q6.

Expected answers are encoded here rather than obtained from production helper methods.
"""
from __future__ import annotations
from itertools import product
from pathlib import Path
import unittest

from anka_contracts.coordination import MemberPartyObservation,PartyRosterMember
from anka_contracts.workflow import MissionConfigSpec,WorkflowSignal
from anka_coordination.coordinator import PartyCoordinatorService
from anka_workflow.compiler import compile_mission
from anka_workflow.engine import MissionWorkflow

ROOT=Path(__file__).resolve().parents[1]
ROSTER=(PartyRosterMember('acct-cra','client-cra',41,'leader'),PartyRosterMember('acct-enu','client-enu',42,'follower'))

def O(i,acct,*,joined,placed,ready,owner,health='HEALTHY',gap=False,map_id=190580738):
    actor=41 if acct=='acct-cra' else 42
    return MemberPartyObservation(f'coordobs-g{i}',acct,'client-cra' if acct=='acct-cra' else 'client-enu',actor,i,i,1,1,'fight-g',map_id,'FIGHT_ACTIVE',owner,joined,placed,ready,health,(f'e{i}',),gap)

def S(i,kind,tick,fight=None,result=None):return WorkflowSignal(f'wfsig-g{i}',kind,tick,(f'e{i}',),fight,result,None,None)

def plan(stop_loss=False,stop_unknown=False,target=2,max_attempts=3):
    return compile_mission(MissionConfigSpec('sufokia_direction_cycle',1,8,target,max_attempts,stop_loss,stop_unknown,'f'*64),ROOT/'assets/workflow/routes.json',watchdog_budget_ticks=2,recovery_budget=1)

def to_active(w,fight,base):
    seq=[('START',None),('PREFLIGHT_OK',None),('ENCOUNTER_SELECTED',None),('FIGHT_ENTRY_PROVEN',fight),('PARTY_JOIN_PROVEN',fight),('PLACEMENT_PROVEN',fight),('READY_PROVEN',fight),('FIRST_TURN_PROVEN',fight)]
    for j,(kind,epoch) in enumerate(seq):w.apply(S(base+j,kind,j,epoch))

class TestCoordinationSmallModel(unittest.TestCase):
    def test_exhaustive_barriers_and_owner_modes(self):
        case=0
        for flags in product((False,True),repeat=6):
            cj,cp,cr,ej,ep,er=flags
            for owners in ((41,41),(42,42),(41,42),(None,None)):
                case+=1
                c=PartyCoordinatorService('party-model',ROSTER)
                c.observe(O(case*2-1,'acct-cra',joined=cj,placed=cp,ready=cr,owner=owners[0]))
                c.observe(O(case*2,'acct-enu',joined=ej,placed=ep,ready=er,owner=owners[1]))
                snap=c.snapshot()
                expect_join=cj and ej
                expect_place=expect_join and cp and ep
                expect_ready=expect_place and cr and er
                expect_cra=expect_ready and owners==(41,41)
                expect_enu=expect_ready and owners==(42,42)
                with self.subTest(flags=flags,owners=owners):
                    self.assertEqual(snap.join_barrier.satisfied,expect_join)
                    self.assertEqual(snap.placement_barrier.satisfied,expect_place)
                    self.assertEqual(snap.ready_barrier.satisfied,expect_ready)
                    self.assertEqual(c.turn_permit('party-model','acct-cra').allowed,expect_cra)
                    self.assertEqual(c.turn_permit('party-model','acct-enu').allowed,expect_enu)

    def test_each_health_or_gap_fault_removes_all_turn_permits(self):
        case=0
        for account in ('acct-cra','acct-enu'):
            for health,gap in (('DEGRADED',False),('BLOCKED',False),('UNKNOWN',False),('HEALTHY',True)):
                case+=1;c=PartyCoordinatorService('party-health',ROSTER)
                kwargs1={'joined':True,'placed':True,'ready':True,'owner':41};kwargs2=dict(kwargs1)
                if account=='acct-cra':kwargs1.update(health=health,gap=gap)
                else:kwargs2.update(health=health,gap=gap)
                c.observe(O(case*2-1,'acct-cra',**kwargs1));c.observe(O(case*2,'acct-enu',**kwargs2))
                with self.subTest(account=account,health=health,gap=gap):
                    self.assertFalse(c.turn_permit('party-health','acct-cra').allowed)
                    self.assertFalse(c.turn_permit('party-health','acct-enu').allowed)

class TestWorkflowSmallModel(unittest.TestCase):
    def test_outcome_policy_matrix(self):
        case=0
        for result,stop_loss,stop_unknown in product(('VICTORY','DEFEAT','UNKNOWN'),(False,True),(False,True)):
            case+=1;w=MissionWorkflow(f'run-model-{case}',plan(stop_loss,stop_unknown,target=2,max_attempts=3));to_active(w,1,case*100)
            w.apply(S(case*100+20,'FIGHT_ENDED',8,1));r=w.apply(S(case*100+21,'FIGHT_OUTCOME',9,1,result))
            self.assertEqual(r.snapshot.attempts,1)
            self.assertEqual(r.snapshot.wins,int(result=='VICTORY'));self.assertEqual(r.snapshot.losses,int(result=='DEFEAT'));self.assertEqual(r.snapshot.unknowns,int(result=='UNKNOWN'))
            end=w.apply(S(case*100+22,'WORLD_REENTRY_PROVEN',10,1))
            expected_stop=(result=='DEFEAT' and stop_loss) or (result=='UNKNOWN' and stop_unknown)
            with self.subTest(result=result,stop_loss=stop_loss,stop_unknown=stop_unknown):
                self.assertEqual(end.snapshot.phase,'STOPPED' if expected_stop else 'WORLD')

    def test_watchdog_always_terminates_with_finite_recovery_budget(self):
        for phase_target in ('PREFLIGHT','WORLD','ENCOUNTER_SELECTED','FIGHT_ENTRY','PARTY_JOIN','PLACEMENT','READY','FIGHT_ACTIVE'):
            w=MissionWorkflow('run-watch-'+phase_target.lower(),plan())
            steps=[S(1,'START',0),S(2,'PREFLIGHT_OK',1),S(3,'ENCOUNTER_SELECTED',2),S(4,'FIGHT_ENTRY_PROVEN',3,1),S(5,'PARTY_JOIN_PROVEN',4,1),S(6,'PLACEMENT_PROVEN',5,1),S(7,'READY_PROVEN',6,1),S(8,'FIRST_TURN_PROVEN',7,1)]
            targets=['PREFLIGHT','WORLD','ENCOUNTER_SELECTED','FIGHT_ENTRY','PARTY_JOIN','PLACEMENT','READY','FIGHT_ACTIVE']
            for ev,target in zip(steps,targets):
                w.apply(ev)
                if target==phase_target:break
            first=w.apply(WorkflowSignal('wfsig-watch-1','WATCHDOG',w.snapshot().watchdog_deadline_tick+1))
            self.assertEqual(first.snapshot.phase,'RECOVERING')
            w.apply(WorkflowSignal('wfsig-watch-2','RECOVERY_SUCCEEDED',first.snapshot.phase_started_tick+1))
            blocked=w.apply(WorkflowSignal('wfsig-watch-3','WATCHDOG',w.snapshot().watchdog_deadline_tick+1))
            with self.subTest(phase=phase_target):self.assertEqual(blocked.snapshot.phase,'BLOCKED')

if __name__=='__main__':unittest.main()
