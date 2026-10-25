from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import ast,json,unittest

from anka_contracts.decision import DecisionFrame
from anka_contracts.mechanics import MechanicsResult
from anka_decision.planner import DeterministicPlanner,frame_to_dict,frame_from_dict,plan_to_dict,plan_from_dict
from anka_decision.policies import load_legacy_profiles

ROOT=Path(__file__).resolve().parents[1]

class FakeKernel:
    def __init__(self,statuses=None):self.statuses=list(statuses or ['LEGAL']);self.calls=[]
    def validate_plan(self,frame,plan):
        self.calls.append(plan)
        status=self.statuses[min(len(self.calls)-1,len(self.statuses)-1)]
        return MechanicsResult(status,'' if status=='LEGAL' else ('STATIC_ILLEGAL' if status=='ILLEGAL' else 'LIVE_CAST_CONTEXT_REQUIRED'))


def frame(**kw):
    base=dict(frame_id='frame-m8',run_id='run-m8',account_id='acct-cra',fight_epoch=1,turn_epoch=2,
      snapshot_id='snap-'+'1'*32,canonical_cursor=50,workflow_goal='FIGHT_TURN',client_instance_id='client-cra',
      snapshot_semantic_sha256='a'*64,state_reducer_revision='m7-r1',kernel_ruleset_id='kernel-r5',game_data_revision='legacy-r5198',
      policy_profile='cra',class_id=9,actor_id=41,turn_owner_id=41,actor_cell=200,map_id=190580738,ap=11,mp=6,
      proof_statuses=(('fight_phase','KNOWN'),('turn_owner','KNOWN'),('actor_cell','KNOWN'),('ap','KNOWN'),('mp','KNOWN'),('loadout','KNOWN'),('targets','KNOWN')),
      available_spells=((32435,3),(32426,3)),target_cells=(229,220),candidate_move_cells=(201,215),deterministic_seed=0,budget_steps=128)
    base.update(kw);return DecisionFrame(**base)

class TestM8Planner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.policies=load_legacy_profiles(ROOT/'assets/decision/legacy_r5198_spell_priorities.json')
    def planner(self,kernel=None):return DeterministicPlanner(kernel or FakeKernel(),self.policies)

    def test_same_frame_same_plan_and_codec_roundtrip(self):
        f=frame();p=self.planner();a=p.plan(f);b=self.planner().plan(f)
        self.assertEqual(a,b);self.assertEqual(a.disposition,'PLAN');self.assertEqual(a.plan.kind,'CAST')
        # Legacy strategy preference ranks spell 32426 before 32435, but only because both are proven available in the frame.
        self.assertEqual(dict(a.plan.semantic_target)['spell_id'],'32426')
        self.assertEqual(frame_from_dict(frame_to_dict(f)),f);self.assertEqual(plan_from_dict(plan_to_dict(a.plan)),a.plan)
        self.assertNotIn('screen',json.dumps(plan_to_dict(a.plan)).lower());self.assertNotIn('pixel',json.dumps(plan_to_dict(a.plan)).lower())

    def test_missing_or_stale_required_evidence_waits(self):
        for name,status in [('ap','UNKNOWN'),('mp','STALE'),('turn_owner','CONFLICTING'),('loadout','NOT_OBSERVED')]:
            with self.subTest(name=name):
                proofs=tuple((k,status if k==name else v) for k,v in frame().proof_statuses)
                r=self.planner().plan(frame(proof_statuses=proofs));self.assertEqual(r.disposition,'WAIT');self.assertIn(name,r.required_evidence)

    def test_wrong_turn_waits_not_end_turn(self):
        r=self.planner().plan(frame(turn_owner_id=99));self.assertEqual(r.disposition,'WAIT');self.assertEqual(r.reason,'DECISION_NOT_ACTOR_TURN')

    def test_kernel_indeterminate_waits_instead_of_guessing(self):
        r=self.planner(FakeKernel(['INDETERMINATE'])).plan(frame())
        self.assertEqual(r.disposition,'WAIT');self.assertIn('LIVE_CAST_CONTEXT_REQUIRED',r.required_evidence)

    def test_illegal_candidates_fall_through_to_semantic_end_turn(self):
        r=self.planner(FakeKernel(['ILLEGAL'])).plan(frame())
        self.assertEqual((r.disposition,r.plan.kind),('PLAN','END_TURN'))

    def test_quarantined_rejected_action_key_does_not_loop(self):
        first=self.planner().plan(frame()).plan
        second_frame=frame(quarantined_action_keys=(first.action_key,))
        second=self.planner().plan(second_frame)
        self.assertEqual(second.disposition,'PLAN');self.assertEqual(second.plan.kind,'CAST');self.assertNotEqual(second.plan.action_key,first.action_key)
        self.assertEqual(dict(second.plan.semantic_target)['target_cell'],'220')

    def test_all_casts_and_end_turn_quarantined_returns_no_action(self):
        p=self.planner();f=frame(target_cells=(229,),available_spells=((32426,3),))
        cast=p.plan(f).plan
        f2=replace(f,quarantined_action_keys=(cast.action_key,));end=DeterministicPlanner(FakeKernel(['ILLEGAL']),self.policies).plan(f2).plan
        f3=replace(f,quarantined_action_keys=(cast.action_key,end.action_key))
        r=DeterministicPlanner(FakeKernel(['LEGAL']),self.policies).plan(f3)
        self.assertEqual(r.disposition,'NO_ACTION');self.assertEqual(r.reason,'DECISION_ALL_ACTION_KEYS_QUARANTINED')

    def test_budget_is_bounded_and_typed(self):
        r=self.planner(FakeKernel(['ILLEGAL'])).plan(frame(budget_steps=1))
        self.assertEqual(r.disposition,'WAIT');self.assertEqual(r.reason,'DECISION_BUDGET_EXHAUSTED')

    def test_policy_class_mismatch_faults(self):
        r=self.planner().plan(frame(class_id=3,policy_profile='cra'))
        self.assertEqual((r.disposition,r.failure_code),('FAULT','POLICY_CLASS_MISMATCH'))

    def test_historical_policy_does_not_create_unproven_spells(self):
        f=frame(available_spells=((32435,3),))
        r=self.planner().plan(f);self.assertEqual(dict(r.plan.semantic_target)['spell_id'],'32435')
        self.assertNotIn('32426',dict(r.plan.semantic_target).values())

    def test_ready_world_and_placement_are_semantic_only(self):
        ready=self.planner().plan(frame(workflow_goal='READY'))
        self.assertEqual(ready.plan.kind,'READY')
        world=frame(workflow_goal='WORLD_MOVE',proof_statuses=(('world_map','KNOWN'),('actor_cell','KNOWN')),candidate_move_cells=(401,))
        self.assertEqual(self.planner().plan(world).plan.kind,'WORLD_MOVE')
        place=frame(workflow_goal='PLACEMENT',proof_statuses=(('fight_phase','KNOWN'),('actor_cell','KNOWN')),candidate_move_cells=(201,))
        self.assertEqual(self.planner().plan(place).plan.kind,'MOVE')

    def test_no_forbidden_runtime_dependencies(self):
        forbidden=('anka_protocol','anka_capture','anka_client','anka_execution','anka_coordination','anka_workflow','anka_live_state','anka_canonical')
        for path in (ROOT/'src/anka_decision').rglob('*.py'):
            tree=ast.parse(path.read_text())
            names=[]
            for n in ast.walk(tree):
                if isinstance(n,ast.Import):names += [x.name for x in n.names]
                elif isinstance(n,ast.ImportFrom):names.append(n.module or '')
            self.assertFalse([x for x in names if any(x==f or x.startswith(f+'.') for f in forbidden)],path)

if __name__=='__main__':unittest.main()
