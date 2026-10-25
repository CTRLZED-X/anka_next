"""P14 adversarial offline tactical research; preserved kernel, zero physical inputs."""
from __future__ import annotations
import copy
import json
import subprocess
import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from anka_app.decision_offline import reference_kernel
from anka_app.map_research_offline import synthetic_map_scene
from anka_contracts.decision import CastProbe
from anka_contracts.tactical_research import TacticalResearchRequest
from anka_decision.tactical_research import inspect_tactical_research
from anka_game_kernel.domain.ids import CellId
from anka_game_kernel.contexts.per_mp_modifiers import PerMPUsedModifierState
from anka_game_kernel.domain.characteristics import CharacteristicKey
from anka_game_kernel.domain.ids import ActorId, SpellId

ROOT=Path(__file__).resolve().parents[1]


def request(*,moves=(215,201,400),targets=(229,220),seq=(),scope=None):
    probe=scope or CastProbe('cra-session','cra',1,'test-fight',8,777,32435,3,229)
    return TacticalResearchRequest(probe,123,moves,targets,seq)


class TestTacticalResearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kernel=reference_kernel(ROOT)

    def assess(self,req=None,*,scene=None,kernel=None):
        s,m,c=scene or synthetic_map_scene()
        return inspect_tactical_research(s,req or request(),map_definition=m,fight_context=c,kernel=kernel or self.kernel)

    def test_real_kernel_stand_move_cast_and_rejection(self):
        r=self.assess()
        self.assertEqual(r.status,'RESEARCH_ONLY')
        self.assertEqual(r.evaluated_count,6)
        self.assertEqual([(x.movement_cell,x.target_cell) for x in r.candidates[:2]],[(215,229),(201,229)])
        self.assertEqual([x.kernel_legality for x in r.candidates[:2]],['LEGAL_STATIC_ONLY']*2)
        self.assertEqual((r.candidates[1].movement_path,r.candidates[1].mp_cost,r.candidates[1].remaining_mp),((215,201),1,4))
        self.assertEqual(r.candidates[0].remaining_ap,8)
        self.assertEqual(r.candidates[-1].kernel_legality,'NOT_EVALUATED')
        self.assertIn('CELL_NOT_REACHABLE_WITH_MP',r.candidates[-1].reasons)

    def test_deterministic_and_no_mutation(self):
        s,m,c=synthetic_map_scene();before=copy.deepcopy(s)
        r1=self.assess(scene=(s,m,c));r2=self.assess(scene=(s,m,c))
        self.assertEqual(r1,r2);self.assertEqual(s,before)

    def test_never_actionable_even_when_static_legal(self):
        r=self.assess();d=r.to_dict()
        self.assertFalse(d['physical_input_permitted']);self.assertFalse(d['actionable'])
        self.assertFalse(d['authoritative']);self.assertTrue(d['preview_only'])
        self.assertNotIn('screen_coordinates',json.dumps(d))
        with self.assertRaises(FrozenInstanceError):r.actionable=True

    def test_move_does_not_claim_confirmed_server_outcome(self):
        r=self.assess(request(moves=(201,),targets=(229,)))
        self.assertIn('MOVEMENT_SERVER_OUTCOME_UNCONFIRMED',r.candidates[0].missing_inputs)
        self.assertFalse(r.actionable)

    def test_per_mp_reactive_effects_force_unknown(self):
        s,m,c=synthetic_map_scene()
        reactive=PerMPUsedModifierState(ActorId(777),SpellId(32435),CharacteristicKey.POWER,1,1,3)
        c=replace(c,per_mp_used_modifiers=(reactive,))
        result=self.assess(request(moves=(201,),targets=(229,)),scene=(s,m,c))
        self.assertEqual(result.candidates[0].kernel_legality,'UNKNOWN')
        self.assertIn('MOVEMENT_DEPENDENT_EFFECTS_UNPROJECTED',result.candidates[0].missing_inputs)

    def test_mp_exact_budget(self):
        r=self.assess(request(moves=(215,201),targets=(229,)))
        self.assertEqual([x.mp_cost for x in r.candidates],[0,1])
        self.assertEqual([x.remaining_mp for x in r.candidates],[5,4])

    def test_unknown_target_not_assumed_legal(self):
        s,m,c=synthetic_map_scene()
        from dataclasses import replace as repl
        c=repl(c,current_turn=None,global_turn_casts=None)
        r=self.assess(scene=(s,m,c),req=request(moves=(215,),targets=(229,)))
        self.assertEqual(r.candidates[0].kernel_legality,'UNKNOWN')
        self.assertIn('casts_this_turn',r.candidates[0].missing_inputs)

    def test_insufficient_ap_no_magic_cost_fallback(self):
        s,m,c=synthetic_map_scene()
        s['actors']['777']['AP']=0
        c=replace(c,actors=(replace(c.actors[0],current_ap=0),c.actors[1]))
        r=self.assess(scene=(s,m,c),req=request(moves=(215,),targets=(229,)))
        self.assertEqual(r.candidates[0].kernel_legality,'ILLEGAL')
        self.assertIsNone(r.candidates[0].remaining_ap)
        self.assertEqual(r.candidates[0].sequence_budget,'OVER_AP_BUDGET')

    def test_two_cast_ap_total_is_not_legal_sequence(self):
        r=self.assess(request(moves=(215,),targets=(229,),seq=((32435,3),(32435,3))))
        self.assertEqual(r.candidates[0].sequence_ap_cost,6)
        self.assertEqual(r.candidates[0].sequence_budget,'WITHIN_AP_BUDGET_COST_ONLY')
        self.assertIn('MULTI_CAST_EFFECTS_AND_CAST_HISTORY_NOT_SIMULATED',r.candidates[0].missing_inputs)

    def test_four_cast_ap_budget_exceeded(self):
        r=self.assess(request(moves=(215,),targets=(229,),seq=((32435,3),)*4))
        self.assertEqual(r.candidates[0].sequence_ap_cost,12)
        self.assertEqual(r.candidates[0].sequence_budget,'OVER_AP_BUDGET')

    def test_unknown_second_spell_blocks_all(self):
        r=self.assess(request(moves=(215,),targets=(229,),seq=((32435,3),(999999999,3))))
        self.assertEqual(r.status,'BLOCKED_STATIC_DATA')
        self.assertEqual(r.candidates,())

    def test_wrong_map_and_wrong_fight_block(self):
        s,m,c=synthetic_map_scene()
        r=self.assess(scene=(s,m,c),req=replace(request(),geometry_map_id=777))
        self.assertIn('MAP_ID_MISMATCH',r.reasons)
        s['fight_id']='different'
        r=self.assess(scene=(s,m,c))
        self.assertEqual(r.status,'BLOCKED_EVIDENCE')

    def test_stale_revision_and_account_generation_block(self):
        s,m,c=synthetic_map_scene();s['revision']=3;s['last_sequence']=3
        r=self.assess(scene=(s,m,c))
        self.assertEqual(r.status,'BLOCKED_EVIDENCE')
        bad=replace(request(),scope=replace(request().scope,account_generation=7))
        self.assertEqual(self.assess(bad).status,'BLOCKED_EVIDENCE')

    def test_snapshot_missing_cast_evidence_is_never_legal(self):
        s,m,c=synthetic_map_scene();c=replace(c,current_turn=None)
        r=self.assess(request(moves=(201,),targets=(229,)),scene=(s,m,c))
        self.assertNotEqual(r.candidates[0].kernel_legality,'LEGAL_STATIC_ONLY')

    def test_tampered_geometry_blocks_candidates(self):
        s,m,c=synthetic_map_scene();c=replace(c,geometry_live_walkable_cells=frozenset({CellId(201)}))
        r=self.assess(scene=(s,m,c))
        self.assertEqual(r.status,'BLOCKED_EVIDENCE')
        self.assertIn('LIVE_GEOMETRY_OVERRIDES_NOT_RECONCILED',r.reasons)

    def test_occupied_cell_not_considered_movement(self):
        r=self.assess(request(moves=(229,),targets=(229,)))
        self.assertEqual(r.candidates[0].kernel_legality,'NOT_EVALUATED')
        self.assertEqual(r.candidates[0].movement_path,())

    def test_all_candidates_in_bounded_cartesian_product(self):
        r=self.assess(request(moves=(215,201,400),targets=(229,220)))
        self.assertEqual(len(r.candidates),6)
        self.assertEqual({(x.movement_cell,x.target_cell) for x in r.candidates},
                         {(m,t) for m in (215,201,400) for t in (229,220)})

    def test_request_rejects_invalid_cells_and_sequences(self):
        p=request()
        for kwargs in [{'moves':()}, {'moves':(215,215)}, {'moves':(-1,)},
                       {'moves':tuple(range(13))},{'targets':(220,)},
                       {'targets':(229,229)}, {'targets':(229,560)},
                       {'seq':((32435,3),)*5}, {'seq':((32435,3),(32435,3.2))},
                       {'seq':((32436,3),)}]:
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):request(**kwargs)
        with self.assertRaises(TypeError):TacticalResearchRequest(None,123,(215,),(229,))
        with self.assertRaises(TypeError):self.assess(req=object())

    def test_kernel_cast_exception_recorded_and_not_mislabeled_legal(self):
        from unittest.mock import Mock
        s,m,c=synthetic_map_scene()
        kernel=Mock(wraps=self.kernel)
        kernel.spells=self.kernel.spells
        kernel.spell_mechanics_overlay=self.kernel.spell_mechanics_overlay
        kernel.casting=self.kernel.casting
        kernel.fight_queries=self.kernel.fight_queries
        kernel.spell_decisions=self.kernel.spell_decisions
        # fail one projected call AFTER base P13 validation
        original=self.kernel.spell_decisions.evaluate_cast_cell
        count={'n':0}
        def fault(**kw):
            count['n']+=1
            if count['n']>1:raise RuntimeError('unexpected')
            return original(**kw)
        kernel.spell_decisions=Mock(wraps=self.kernel.spell_decisions)
        kernel.spell_decisions.evaluate_cast_cell.side_effect=fault
        r=self.assess(request(moves=(215,),targets=(229,)),scene=(s,m,c),kernel=kernel)
        self.assertEqual(r.candidates[0].kernel_legality,'NOT_EVALUATED')
        self.assertIn('KERNEL_CAST_QUERY_FAILED',r.candidates[0].reasons)

    def test_cli_demo_never_live(self):
        cmd=[sys.executable,'-m','anka_app.cli','tactical-demo']
        proc=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(proc.returncode,0,proc.stderr[-1500:])
        self.assertIn('physical_input_sent',proc.stdout)
        self.assertIn('false',proc.stdout.lower())


if __name__=='__main__':unittest.main()
