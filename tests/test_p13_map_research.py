"""P13: challenge geometry, decision and movement using actual preserved Kernel rules."""
from __future__ import annotations
import ast
import copy
import json
import subprocess
import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import MagicMock

from anka_app.decision_offline import reference_kernel
from anka_app.map_research_offline import synthetic_map_scene, map_demo
from anka_contracts.decision import CastProbe
from anka_contracts.map_research import MapResearchRequest
from anka_decision.map_research import inspect_map_research
from anka_game_kernel.domain.ids import MapId, CellId, ActorId

ROOT=Path(__file__).resolve().parents[1]

def request(target=229, move=201, cells=None):
    return MapResearchRequest(CastProbe('cra-session','cra',1,'test-fight',8,777,32435,3,target),
        123, tuple(cells if cells is not None else (target,)),move)


class TestMapResearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.kernel=reference_kernel(ROOT)

    def evaluate(self, req=None, **kwargs):
        snapshot, map_def, context=synthetic_map_scene(**kwargs)
        return inspect_map_research(snapshot, req or request(),map_definition=map_def,
                                     fight_context=context,kernel=self.kernel)

    def test_real_kernel_positive_static_cast_and_path(self):
        r=self.evaluate()
        self.assertEqual(r.status,'RESEARCH_ONLY')
        self.assertEqual(r.evaluated_cells,((229,'LEGAL_STATIC_ONLY',()),))
        self.assertEqual(r.movement_target_status,'REACHABLE_STATIC_ONLY')
        self.assertEqual(r.movement_target_path,(215,201))
        self.assertEqual(dict(r.reachable_cells)[201],1)
    def test_never_actionable(self):
        r=self.evaluate();data=r.to_dict()
        self.assertFalse(data['actionable']);self.assertFalse(data['authoritative'])
        self.assertFalse(data['physical_input_permitted']);self.assertTrue(data['preview_only'])
        with self.assertRaises(FrozenInstanceError):r.actionable=True
    def test_range_rejection_not_approximated(self):
        r=self.evaluate(request(cells=(229,220,201)))
        kinds={cell:status for cell,status,_ in r.evaluated_cells}
        self.assertEqual(kinds[220],'ILLEGAL')
        self.assertEqual(kinds[201],'ILLEGAL')
    def test_dynamic_occupancy_rejects_move(self):
        r=self.evaluate(request(move=229))
        self.assertEqual(r.movement_target_status,'ILLEGAL_OR_NOT_REACHABLE_WITH_MP')
        self.assertNotIn(229,dict(r.reachable_cells))
    def test_unreachable_by_mp_not_reported_as_obstacle(self):
        r=self.evaluate(request(move=400))
        self.assertIn(r.movement_target_status,('OUTSIDE_MP_BUDGET','ILLEGAL_OR_NOT_REACHABLE_WITH_MP'))
    def test_los_blocker_deterministic(self):
        r=self.evaluate(request(target=258,move=201),opponent_cell=258,blocked_los=(230,))
        self.assertEqual(r.status,'RESEARCH_ONLY')
        self.assertEqual(r.evaluated_cells[0][1],'ILLEGAL')
        self.assertIn('line_of_sight',str(r.evaluated_cells[0][2]))
    def test_map_avoid_cell_makes_unwalkable(self):
        r=self.evaluate(request(move=201),non_walkable=(201,))
        self.assertEqual(r.movement_target_status,'ILLEGAL_OR_NOT_REACHABLE_WITH_MP')
    def test_map_incomplete_refused(self):
        s,m,c=synthetic_map_scene()
        r=inspect_map_research(s,request(),map_definition=replace(m,cells=m.cells[:-1]),fight_context=c,kernel=self.kernel)
        self.assertEqual(r.status,'BLOCKED_EVIDENCE')
        self.assertIn('MAP_COVERAGE_INCOMPLETE',r.reasons)
    def test_map_duplicates_refused_even_if_length_560(self):
        s,m,c=synthetic_map_scene()
        r=inspect_map_research(s,request(),map_definition=replace(m,cells=m.cells[:-1]+(m.cells[0],)),fight_context=c,kernel=self.kernel)
        self.assertIn('MAP_COVERAGE_INCOMPLETE',r.reasons)
    def test_wrong_map_definition(self):
        s,m,c=synthetic_map_scene()
        r=inspect_map_research(s,request(),map_definition=replace(m,map_id=MapId(42)),fight_context=c,kernel=self.kernel)
        self.assertIn('MAP_ID_MISMATCH',r.reasons)
    def test_context_map_conflict(self):
        s,m,c=synthetic_map_scene()
        r=inspect_map_research(s,request(),map_definition=m,fight_context=replace(c,map_id=MapId(42)),kernel=self.kernel)
        self.assertIn('FIGHT_MAP_ID_CONFLICT',r.reasons)
    def test_fight_turn_owner_conflict(self):
        s,m,c=synthetic_map_scene()
        r=inspect_map_research(s,request(),map_definition=m,fight_context=replace(c,active_actor_id=ActorId(888),current_turn=None),kernel=self.kernel)
        self.assertIn('FIGHT_TURN_ACTOR_MISMATCH',r.reasons)
    def test_fight_actor_position_conflict(self):
        s,m,c=synthetic_map_scene()
        actor=replace(c.actors[0],cell_id=CellId(214))
        r=inspect_map_research(s,request(),map_definition=m,fight_context=replace(c,actors=(actor,c.actors[1])),kernel=self.kernel)
        self.assertIn('FIGHT_ACTOR_STATE_CONFLICT',r.reasons)
    def test_fight_actor_ap_conflict(self):
        s,m,c=synthetic_map_scene()
        actor=replace(c.actors[0],current_ap=9)
        r=inspect_map_research(s,request(),map_definition=m,fight_context=replace(c,actors=(actor,c.actors[1])),kernel=self.kernel)
        self.assertIn('FIGHT_ACTOR_STATE_CONFLICT',r.reasons)
    def test_cooldowns_incomplete(self):
        s,m,c=synthetic_map_scene()
        actor=replace(c.actors[0],cooldowns_complete=False)
        r=inspect_map_research(s,request(),map_definition=m,fight_context=replace(c,actors=(actor,c.actors[1])),kernel=self.kernel)
        self.assertIn('FIGHT_COOLDOWN_EVIDENCE_INCOMPLETE',r.reasons)
    def test_cooldowns_conflicting(self):
        s,m,c=synthetic_map_scene()
        actor=replace(c.actors[0],cooldowns=())
        r=inspect_map_research(s,request(),map_definition=m,fight_context=replace(c,actors=(actor,c.actors[1])),kernel=self.kernel)
        self.assertIn('FIGHT_COOLDOWNS_CONFLICT',r.reasons)
    def test_actor_unknown_cell_invalid(self):
        s,m,c=synthetic_map_scene()
        unknown=replace(c.actors[1],cell_id=None)
        r=inspect_map_research(s,request(),map_definition=m,fight_context=replace(c,actors=(c.actors[0],unknown)),kernel=self.kernel)
        self.assertIn('FIGHT_OCCUPANCY_INCOMPLETE',r.reasons)
    def test_stale_state_short_circuits_map(self):
        s,m,c=synthetic_map_scene()
        s['last_sequence']=4
        r=inspect_map_research(s,request(),map_definition=m,fight_context=c,kernel=self.kernel)
        self.assertEqual(r.status,'BLOCKED_EVIDENCE')
        self.assertIn('STATE_SEQUENCE_INCONSISTENT',r.reasons)
    def test_unknown_turn_cast_history_never_proves_legal_cast(self):
        s,m,c=synthetic_map_scene()
        r=inspect_map_research(s,request(),map_definition=m,
                    fight_context=replace(c,current_turn=None,global_turn_casts=None),kernel=self.kernel)
        self.assertEqual(r.evaluated_cells[0][1],'UNKNOWN')
        self.assertIn('casts_this_turn',r.missing_inputs)
    def test_low_ap_is_rejected_at_kernel_stage(self):
        s,m,c=synthetic_map_scene()
        s['actors']['777']['AP']=0
        c=replace(c,actors=(replace(c.actors[0],current_ap=0),c.actors[1]))
        r=inspect_map_research(s,request(),map_definition=m,fight_context=c,kernel=self.kernel)
        self.assertEqual(r.evaluated_cells[0][1],'ILLEGAL')
        self.assertIn('availability',str(r.evaluated_cells[0][2]))
    def test_current_fight_geometry_override_needs_reconciliation(self):
        s,m,c=synthetic_map_scene()
        c=replace(c,geometry_live_walkable_cells=frozenset({CellId(201)}))
        r=inspect_map_research(s,request(),map_definition=m,fight_context=c,kernel=self.kernel)
        self.assertIn('LIVE_GEOMETRY_OVERRIDES_NOT_RECONCILED',r.reasons)
    def test_origin_static_map_conflict_refused(self):
        s,m,c=synthetic_map_scene(non_walkable=(215,))
        r=inspect_map_research(s,request(),map_definition=m,fight_context=c,kernel=self.kernel)
        self.assertIn('ACTOR_ORIGIN_GEOMETRY_CONFLICT',r.reasons)
    def test_cast_candidates_keep_order_and_no_duplicate_target(self):
        s,m,c=synthetic_map_scene()
        r=inspect_map_research(s,request(cells=(201,229,220)),map_definition=m,fight_context=c,kernel=self.kernel)
        self.assertEqual(tuple(row[0] for row in r.evaluated_cells),(201,229,220))
    def test_no_move_request_is_not_silently_invented(self):
        s,m,c=synthetic_map_scene()
        r=inspect_map_research(s,request(move=None),map_definition=m,fight_context=c,kernel=self.kernel)
        self.assertEqual(r.movement_target_status,'NOT_REQUESTED')
        self.assertEqual(r.movement_target_path,())
    def test_no_mutation(self):
        s,m,c=synthetic_map_scene();before=copy.deepcopy(s)
        inspect_map_research(s,request(),map_definition=m,fight_context=c,kernel=self.kernel)
        self.assertEqual(before,s)
    def test_unknown_spell_refused(self):
        s,m,c=synthetic_map_scene();p=request()
        bad=replace(p,scope=replace(p.scope,spell_id=99999999))
        r=inspect_map_research(s,bad,map_definition=m,fight_context=c,kernel=self.kernel)
        self.assertEqual(r.status,'BLOCKED_STATIC_DATA')
    def test_kernel_method_failure_not_silent(self):
        s,m,c=synthetic_map_scene();kernel=MagicMock()
        kernel.spells.require.side_effect=KeyError('spell')
        r=inspect_map_research(s,request(),map_definition=m,fight_context=c,kernel=kernel)
        self.assertEqual(r.status,'BLOCKED_STATIC_DATA')
    def test_contract_invalid(self):
        p=request().scope
        for bad in ((),(229,229),(-1,),(560,),tuple(range(17))):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                MapResearchRequest(p,123,bad)
        with self.assertRaises(ValueError):MapResearchRequest(p,0,(229,))
        with self.assertRaises(ValueError):MapResearchRequest(p,123,(229,),560)
        with self.assertRaises(TypeError):inspect_map_research({},'bad',map_definition=None,fight_context=None,kernel=None)
    def test_module_dependency_boundary(self):
        blocked={'anka_app','anka_capture','anka_protocol','anka_live_state','anka_canonical',
                 'anka_execution','anka_client','anka_coordination','anka_workflow','anka_observability'}
        for path in (ROOT/'src/anka_decision').rglob('*.py'):
            tree=ast.parse(path.read_text())
            imports=[]
            for node in ast.walk(tree):
                if isinstance(node,ast.Import):imports.extend(alias.name for alias in node.names)
                if isinstance(node,ast.ImportFrom):imports.append(node.module or '')
            self.assertFalse(set(n.split('.')[0] for n in imports)&blocked,path)
    def test_demo_and_cli(self):
        r=map_demo(root=ROOT)
        self.assertEqual(r['status'],'RESEARCH_ONLY')
        self.assertFalse(r['physical_input_sent'])
        run=subprocess.run([sys.executable,'-m','anka_app.cli','map-demo'],cwd=ROOT,
                capture_output=True,text=True,timeout=30)
        self.assertEqual(run.returncode,0,run.stdout[-1500:])
        self.assertIn('RESEARCH_ONLY',run.stdout)
    def test_start_still_disabled(self):
        run=subprocess.run([sys.executable,'-m','anka_app.cli','start'],cwd=ROOT,
                capture_output=True,text=True,timeout=30)
        self.assertEqual(run.returncode,40)
        self.assertIn('START_WINDOWS_REQUIRED',run.stdout)

if __name__=='__main__':unittest.main()
