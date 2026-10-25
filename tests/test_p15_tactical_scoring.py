"""P15 priority research: ensure simulated scores cannot become authorizations."""
from __future__ import annotations
import copy
import json
import subprocess
import sys
import unittest
from dataclasses import replace, FrozenInstanceError
from pathlib import Path
from unittest.mock import Mock

from anka_app.decision_offline import reference_kernel
from anka_app.map_research_offline import synthetic_map_scene
from anka_contracts.decision import CastProbe
from anka_contracts.tactical_research import TacticalResearchRequest
from anka_contracts.tactical_scoring import (
    TacticalScoringRequest, SyntheticPositionRisk, SyntheticTargetPriority,
)
from anka_decision.tactical_scoring import inspect_tactical_scoring

ROOT = Path(__file__).resolve().parents[1]


def req(*, policy='CRA_DAMAGE_RESEARCH', seq=(), moves=(215,201,400), targets=(229,220),
        priorities=((229,5,1),(220,1,5)), risks=((215,3),(201,1),(400,0)), scope=None):
    tactical=TacticalResearchRequest(scope or CastProbe('cra-session','cra',1,'test-fight',8,777,32435,3,229),
                                     123,moves,targets,seq)
    return TacticalScoringRequest(tactical,policy,
        tuple(SyntheticTargetPriority(*t) for t in priorities),
        tuple(SyntheticPositionRisk(*p) for p in risks))


class TestP15TacticalScoring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kernel=reference_kernel(ROOT)

    def inspect(self, request=None, scene=None, kernel=None):
        snap,geometry,context=scene or synthetic_map_scene()
        return inspect_tactical_scoring(snap,request or req(),map_definition=geometry,
                                        fight_context=context,kernel=kernel or self.kernel)

    def test_deterministic_ranking_uses_kernel_legality(self):
        r=self.inspect()
        self.assertEqual(r.status,'RESEARCH_ONLY')
        self.assertEqual(r.evaluated_count,6)
        self.assertEqual([x.assessment for x in r.ranked[:2]],['SCORED_STATIC_PREVIEW']*2)
        self.assertEqual((r.ranked[0].candidate.movement_cell,r.ranked[0].score),(201,18))
        self.assertEqual((r.ranked[1].candidate.movement_cell,r.ranked[1].score),(215,15))
        self.assertEqual(len([x for x in r.ranked if x.score is not None]),2)
        self.assertEqual({x.score for x in r.ranked if x.assessment=='REJECTED_KERNEL'},{None})

    def test_profiles_are_explicit_not_inferred_from_character_name(self):
        cra=self.inspect(req()).ranked[0].score
        enu=self.inspect(req(policy='ENU_CONTROL_RESEARCH')).ranked[0].score
        self.assertNotEqual(cra,enu)
        self.assertEqual(enu,6)
        self.assertEqual(self.inspect(req(policy='BALANCED_RESEARCH')).ranked[0].score, 9)

    def test_contributions_sum_to_score_and_are_explained(self):
        for x in self.inspect().ranked:
            if x.score is None:
                self.assertFalse(x.contributions)
            else:
                self.assertEqual(sum(value for _,value in x.contributions),x.score)
                self.assertIn('P15_SYNTHETIC_PRIORITIES_NOT_GAME_EFFECTS',x.reasons)
                self.assertTrue(set(dict(x.contributions))=={
                    'synthetic_damage_priority','synthetic_control_priority',
                    'synthetic_exposure_cost','kernel_mp_spend_cost'})

    def test_any_multicast_is_not_scored_as_a_valid_sequence(self):
        r=self.inspect(req(seq=((32435,3),(32435,3))))
        self.assertTrue(all(x.score is None for x in r.ranked))
        self.assertTrue(any(x.assessment=='UNSCORED_MULTI_CAST_UNCERTIFIED' for x in r.ranked))

    def test_multicast_over_ap_is_rejected(self):
        r=self.inspect(req(seq=((32435,3),)*4))
        self.assertTrue(any(x.assessment=='REJECTED_AP_BUDGET' for x in r.ranked))
        self.assertTrue(all(x.score is None for x in r.ranked))

    def test_kernel_rejected_cells_never_rank_above_statically_legal(self):
        r=self.inspect()
        illegal=[x for x in r.ranked if x.candidate.target_cell==220]
        self.assertTrue(all(x.assessment=='REJECTED_KERNEL' for x in illegal if
                            x.candidate.movement_cell in (215,201)))

    def test_stale_scope_quarantines_every_candidate(self):
        bad=replace(req(),research=replace(req().research,
                    scope=replace(req().research.scope,account_generation=99)))
        report=self.inspect(bad)
        self.assertEqual(report.status,'BLOCKED_EVIDENCE')
        self.assertEqual(report.ranked,())

    def test_live_geometry_disagreement_quarantines_all(self):
        from anka_game_kernel.domain.ids import CellId
        snap,geometry,ctx=synthetic_map_scene()
        ctx=replace(ctx,geometry_live_walkable_cells=frozenset({CellId(201)}))
        report=self.inspect(scene=(snap,geometry,ctx))
        self.assertEqual(report.status,'BLOCKED_EVIDENCE')
        self.assertIn('LIVE_GEOMETRY_OVERRIDES_NOT_RECONCILED',report.reasons)

    def test_unknown_cast_history_not_scored(self):
        snap,geometry,ctx=synthetic_map_scene()
        ctx=replace(ctx,current_turn=None,global_turn_casts=None)
        report=self.inspect(scene=(snap,geometry,ctx))
        self.assertTrue(all(x.score is None for x in report.ranked))

    def test_reactive_effects_not_ranked_as_statically_legal(self):
        from anka_game_kernel.contexts.per_mp_modifiers import PerMPUsedModifierState
        from anka_game_kernel.domain.ids import ActorId,SpellId
        from anka_game_kernel.domain.characteristics import CharacteristicKey
        snap,geo,ctx=synthetic_map_scene()
        reactive=PerMPUsedModifierState(ActorId(777),SpellId(32435),CharacteristicKey.POWER,1,1,3)
        ctx=replace(ctx,per_mp_used_modifiers=(reactive,))
        report=self.inspect(scene=(snap,geo,ctx))
        moved=[x for x in report.ranked if x.candidate.movement_cell==201]
        self.assertTrue(all(x.score is None for x in moved))

    def test_no_input_authority_even_when_scored(self):
        r=self.inspect()
        data=r.to_dict()
        self.assertFalse(data['authoritative']);self.assertFalse(data['actionable'])
        self.assertFalse(data['physical_input_permitted']);self.assertIsNone(data['selected_action'])
        self.assertIsNone(data['damage_or_mp_removal_prediction'])
        self.assertTrue(data['fixture_priorities_only'])
        self.assertNotIn('screen_coordinates',json.dumps(data))
        with self.assertRaises(FrozenInstanceError):r.actionable=True
        with self.assertRaises(FrozenInstanceError):r.ranked[0].score=999

    def test_reconstructed_reports_cannot_forge_actuation_authority(self):
        from anka_decision.tactical_research import inspect_tactical_research
        s,m,c=synthetic_map_scene()
        base=inspect_tactical_research(s,req().research,
                                       map_definition=m,fight_context=c,kernel=self.kernel)
        report=self.inspect()
        for key in ['actionable', 'authoritative']:
            with self.subTest(key=key),self.assertRaises(ValueError):
                replace(report,**{key:True})
            with self.subTest(key=key),self.assertRaises(ValueError):
                replace(base,**{key:True})
        with self.assertRaises(ValueError):replace(report,preview_only=False)
        with self.assertRaises(ValueError):replace(base,preview_only=False)

    def test_no_runtime_capture_or_execution_dependencies(self):
        import ast
        for name in ('anka_decision/tactical_scoring.py',
                     'anka_contracts/tactical_scoring.py'):
            code=(ROOT/'src'/name).read_text(encoding='utf-8')
            tree=ast.parse(code)
            imports=[node.module for node in ast.walk(tree)
                     if isinstance(node,ast.ImportFrom)]
            self.assertFalse(any((module or '').startswith(('anka_execution',
                  'anka_capture','anka_protocol','anka_client','anka_live_state')) for module in imports))
            self.assertNotIn('pyautogui',code)

    def test_deterministic_and_input_immutable(self):
        scene=synthetic_map_scene()
        snap_before=copy.deepcopy(scene[0]);request=req()
        result1=self.inspect(request,scene);result2=self.inspect(request,scene)
        self.assertEqual(result1,result2);self.assertEqual(scene[0],snap_before)

    def test_missing_fixture_values_are_not_filled_by_default(self):
        with self.assertRaisesRegex(ValueError,'INCOMPLETE_OR_DUPLICATE_TARGETS'):
            req(priorities=((229,5,1),))
        with self.assertRaisesRegex(ValueError,'INCOMPLETE_OR_DUPLICATE_POSITIONS'):
            req(risks=((215,1),(201,2)))
        with self.assertRaises(ValueError):req(priorities=((229,5,1),(229,1,5)))
        with self.assertRaises(ValueError):req(risks=((215,1),(201,2),(201,3)))

    def test_invalid_synthetic_inputs_rejected(self):
        for values in [((229,-1,1),(220,2,3)),((229,6,1),(220,2,3)),
                       ((229,True,1),(220,2,3)),((229,1.3,1),(220,2,3))]:
            with self.subTest(values=values),self.assertRaises(ValueError):
                req(priorities=values)
        for values in [((215,-1),(201,2),(400,0)),((215,True),(201,2),(400,0)),
                       ((215,10),(201,2),(400,0))]:
            with self.subTest(values=values),self.assertRaises(ValueError):req(risks=values)
        for policy in ['CRA','ENU','',None,12]:
            with self.subTest(policy=policy),self.assertRaises(ValueError):req(policy=policy)
        with self.assertRaises(TypeError):inspect_tactical_scoring({},object(),
                                map_definition=None,fight_context=None,kernel=None)

    def test_no_silent_policy_class_detection(self):
        # Policy is supplied explicitly; actor/name are not consulted to select it.
        self.assertEqual(self.inspect(req(policy='ENU_CONTROL_RESEARCH')).policy,
                         'ENU_CONTROL_RESEARCH')

    def test_priority_reversal_changes_synthetic_ranking_not_legality(self):
        baseline=self.inspect().ranked
        inverted=self.inspect(req(priorities=((229,0,5),(220,5,0)))).ranked
        # Different fixture values can affect scores, never Kernel legality.
        self.assertNotEqual(baseline[0].score,inverted[0].score)
        self.assertEqual([x.candidate.kernel_legality for x in baseline if x.score is not None],
                         ['LEGAL_STATIC_ONLY']*2)

    def test_kernel_fault_never_fabricates_score(self):
        k=Mock(wraps=self.kernel)
        k.spell_mechanics_overlay=self.kernel.spell_mechanics_overlay
        k.spells=self.kernel.spells
        k.casting=self.kernel.casting
        k.fight_queries=self.kernel.fight_queries
        k.spell_decisions=self.kernel.spell_decisions
        original=self.kernel.spell_decisions.evaluate_cast_cell
        calls={'i':0}
        def fault(**kwargs):
            calls['i']+=1
            if calls['i']>=2:raise RuntimeError('injected')
            return original(**kwargs)
        k.spell_decisions=Mock(wraps=self.kernel.spell_decisions)
        k.spell_decisions.evaluate_cast_cell.side_effect=fault
        r=self.inspect(kernel=k)
        self.assertFalse(any(x.score is not None for x in r.ranked))

    def test_cli_demos_never_perform_game_input(self):
        for policy in ['CRA_DAMAGE_RESEARCH','ENU_CONTROL_RESEARCH']:
            p=subprocess.run([sys.executable,'-m','anka_app.cli','scoring-demo',policy],
                             cwd=ROOT,text=True,capture_output=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stderr[-1000:])
            self.assertIn('"physical_input_sent": false',p.stdout)
        p=subprocess.run([sys.executable,'-m','anka_app.cli','scoring-demo','UNKNOWN'],
                         cwd=ROOT,text=True,capture_output=True,timeout=30)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('P15_POLICY_UNSUPPORTED',p.stdout)


if __name__=='__main__':unittest.main()
