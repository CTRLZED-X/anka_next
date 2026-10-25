"""P16 genuine kernel preview and adversarial sequence tests; no live authority."""
from __future__ import annotations
import copy
import json
import subprocess
import sys
import unittest
from dataclasses import FrozenInstanceError,replace
from pathlib import Path
from types import SimpleNamespace
from anka_app.decision_offline import reference_kernel
from anka_app.map_research_offline import synthetic_map_scene
from anka_contracts.decision import CastProbe
from anka_contracts.tactical_research import TacticalResearchRequest
from anka_contracts.sequence_research import ResearchCastStep,SequenceResearchRequest,SequenceResearchReport
from anka_decision.sequence_research import inspect_sequence_research
from anka_game_kernel.contexts.projection import FightProjection
from anka_game_kernel.contexts.turn_history import CastRecord
from anka_game_kernel.domain.ids import ActorId,CellId,SpellId
from anka_game_kernel.mechanics.projection.service import FightProjectionService
from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.results.action_projection import CastActionProjectionResult
from anka_game_kernel.contexts.per_mp_modifiers import PerMPUsedModifierState
from anka_game_kernel.domain.characteristics import CharacteristicKey
ROOT=Path(__file__).resolve().parents[1]


def build(*,move=215,sequence=((32435,3,229),(32435,3,229)),tactical_sequence=()):
    scope=CastProbe('cra-session','cra',1,'test-fight',8,777,32435,3,229)
    tactical=TacticalResearchRequest(scope,123,(215,201,400),(229,220),tactical_sequence)
    return SequenceResearchRequest(tactical,move,tuple(ResearchCastStep(*x) for x in sequence))


class TestP16Sequence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kernel=reference_kernel(ROOT)

    def check(self,request=None,*,scene=None,kernel=None):
        snapshot,geometry,context=scene or synthetic_map_scene()
        return inspect_sequence_research(snapshot,request or build(),map_definition=geometry,
                                          fight_context=context,kernel=kernel or self.kernel)

    def test_actual_kernel_stops_after_first_live_authoritative_cast(self):
        result=self.check()
        self.assertEqual(result.status,'STOPPED_UNCERTAIN')
        self.assertEqual(result.attempted_count,1)
        self.assertEqual(result.requested_count,2)
        step=result.steps[0]
        self.assertEqual(step.status,'STOP_UNRESOLVED_EFFECTS')
        self.assertEqual((step.before_ap,step.after_ap),(11,8))
        self.assertIn('damage_amount',step.live_requirements)
        self.assertEqual(step.projected_cast_count,1)
        self.assertFalse(step.projection_complete)

    def test_legal_first_cast_is_not_assumed_complete_even_when_only_one(self):
        r=self.check(build(sequence=((32435,3,229),)))
        self.assertEqual(r.status,'STOPPED_UNCERTAIN')
        self.assertEqual(r.attempted_count,1)

    def test_actual_kernel_move_then_cast_stops_on_unresolved_effects(self):
        r=self.check(build(move=201))
        self.assertEqual(r.status,'STOPPED_UNCERTAIN')
        self.assertEqual(r.steps[0].after_mp,4)

    def test_rejects_unreachable_movement_before_cast(self):
        r=self.check(build(move=400))
        self.assertEqual(r.status,'BLOCKED_GATE')
        self.assertEqual(r.attempted_count,0)

    def test_reactive_movement_blocks_all(self):
        s,m,c=synthetic_map_scene()
        modifier=PerMPUsedModifierState(ActorId(777),SpellId(32435),CharacteristicKey.POWER,1,1,3)
        c=replace(c,per_mp_used_modifiers=(modifier,))
        self.assertEqual(self.check(build(move=201),scene=(s,m,c)).status,'BLOCKED_GATE')

    def test_stale_account_revision(self):
        s,m,c=synthetic_map_scene();s['revision']=7
        r=self.check(scene=(s,m,c))
        self.assertEqual(r.status,'BLOCKED_GATE')
        self.assertEqual(r.attempted_count,0)

    def test_wrong_fight_identity(self):
        s,m,c=synthetic_map_scene();s['fight_id']='other'
        self.assertEqual(self.check(scene=(s,m,c)).status,'BLOCKED_GATE')

    def test_not_enough_ap_blocks_before_sequence(self):
        s,m,c=synthetic_map_scene();s['actors']['777']['AP']=0
        c=replace(c,actors=(replace(c.actors[0],current_ap=0),c.actors[1]))
        self.assertEqual(self.check(scene=(s,m,c)).status,'BLOCKED_GATE')

    def test_missing_cast_history_does_not_assume_zero(self):
        s,m,c=synthetic_map_scene();c=replace(c,current_turn=None,global_turn_casts=None)
        self.assertEqual(self.check(scene=(s,m,c)).status,'BLOCKED_GATE')

    def test_unknown_second_spell_explicit_halt_not_throw(self):
        r=self.check(build(sequence=((32435,3,229),(99999999,3,220))))
        self.assertEqual(r.status,'STOPPED_UNCERTAIN')
        self.assertEqual(r.attempted_count,1)

    def test_disallow_invalid_first_spell(self):
        with self.assertRaisesRegex(ValueError,'P16_FIRST_STEP'):
            build(sequence=((32435,3,220),))

    def test_request_bounded_casts(self):
        with self.assertRaisesRegex(ValueError,'P16_CAST_SEQUENCE_INVALID'):
            build(sequence=())
        with self.assertRaisesRegex(ValueError,'P16_CAST_SEQUENCE_INVALID'):
            build(sequence=((32435,3,229),)*5)

    def test_movement_must_be_in_tactical_request(self):
        with self.assertRaisesRegex(ValueError,'P16_MOVEMENT_NOT_REQUESTED'):
            build(move=216)

    def test_first_spell_grade_must_match(self):
        with self.assertRaisesRegex(ValueError,'P16_FIRST_STEP'):
            build(sequence=((32435,2,229),))

    def test_explicit_p14_cost_sequence_mismatch(self):
        with self.assertRaisesRegex(ValueError,'P16_TACTICAL_SEQUENCE_MISMATCH'):
            build(tactical_sequence=((32435,3),(32435,3)),sequence=((32435,3,229),))

    def test_bools_invalid_for_ids_and_cells(self):
        for data in [(True,3,229),(32435,True,229),(32435,3,True),(-1,3,229),
                     (32435,11,229),(32435,3,560)]:
            with self.subTest(data=data),self.assertRaises(ValueError): ResearchCastStep(*data)
        with self.assertRaises(ValueError):build(move=True)

    def test_wrong_contract(self):
        with self.assertRaises(TypeError):self.check(request=object())
        with self.assertRaises(TypeError):SequenceResearchRequest(None,215,(ResearchCastStep(32435,3,229),))

    def test_immutable_no_execution_auth_and_json(self):
        r=self.check()
        with self.assertRaises(FrozenInstanceError):r.actionable=True
        exported=r.to_dict()
        self.assertIs(exported['physical_input_permitted'],False)
        self.assertIs(exported['actionable'],False)
        self.assertIs(exported['authoritative'],False)
        self.assertIsNone(exported['selected_action'])
        self.assertNotIn('screen_coordinates',json.dumps(exported))
        with self.assertRaisesRegex(ValueError,'P16_RESEARCH_AUTHORITY_FORGERY'):
            replace(r,actionable=True)
        with self.assertRaisesRegex(ValueError,'P16_RESEARCH_AUTHORITY_FORGERY'):
            replace(r,physical_input_permitted=True)
        with self.assertRaisesRegex(ValueError,'P16_RESEARCH_AUTHORITY_FORGERY'):
            replace(r,authoritative=True)

    def test_deterministic_and_snapshot_immutable(self):
        s,m,c=synthetic_map_scene();baseline=copy.deepcopy(s)
        a=self.check(scene=(s,m,c));b=self.check(scene=(s,m,c))
        self.assertEqual(a,b)
        self.assertEqual(s,baseline)
        self.assertEqual(c.current_turn.cast_count(SpellId(32435)),0)
        self.assertEqual(c.actor(ActorId(777)).current_ap,11)

    def test_projected_missing_live_effects_never_flow_to_second(self):
        fake=self.fake_kernel(callback=lambda **kw: self.kernel.spell_decisions.preview_cast(**kw))
        r=self.check(kernel=fake)
        self.assertEqual(fake.spell_decisions.calls,1)
        self.assertEqual(r.attempted_count,1)

    def fake_kernel(self,callback):
        class Spy:
            calls=0
            def evaluate_cast_cell(self,**kwargs):
                return self.self_original.evaluate_cast_cell(**kwargs)
            def preview_cast(self,**kwargs):
                self.calls+=1
                return callback(**kwargs)
        Spy.self_original=self.kernel.spell_decisions
        spy=Spy()
        return SimpleNamespace(spell_decisions=spy,spell_mechanics_overlay=self.kernel.spell_mechanics_overlay,
                               fight_queries=self.kernel.fight_queries,spells=self.kernel.spells,
                               casting=self.kernel.casting)

    def test_synthetic_complete_projection_can_chain_and_track_history(self):
        """Explicit fixture models fully known effect-free cast to test P16 loop itself."""
        proj=FightProjectionService()
        def synthetic_effect_free(**kw):
            ctx=kw['context']; aid=kw['caster_id']; sid=kw['spell_id']
            legality=self.kernel.spell_decisions.evaluate_cast_cell(**kw)
            initial=FightProjection.from_context(ctx)
            if legality.legal is not True:
                return CastActionProjectionResult(certainty=Certainty.DETERMINISTIC,
                    legal=False,projection_complete=False,projection=initial)
            moved=proj.spend_ap(initial,aid,3)
            target=ctx.actor_at(kw['target_cell'])
            moved=proj.append_cast(moved,CastRecord(aid,sid,kw['grade'],
                target_actor_id=target.actor_id if target else None,
                target_cell=kw['target_cell'],ap_spent=3))
            return CastActionProjectionResult(certainty=Certainty.DETERMINISTIC,
                legal=True,projection_complete=True,projection=moved)
        fake=self.fake_kernel(callback=synthetic_effect_free)
        result=self.check(kernel=fake)
        self.assertEqual(result.status,'RESEARCH_ONLY')
        self.assertEqual(result.attempted_count,2)
        self.assertEqual([s.projected_cast_count for s in result.steps],[1,2])
        self.assertEqual([s.after_ap for s in result.steps],[8,5])
        self.assertFalse(result.actionable)

    def test_second_cast_rejected_after_projected_ap_spend(self):
        proj=FightProjectionService()
        def synthetic_effect_free(**kw):
            ctx=kw['context'];aid=kw['caster_id'];sid=kw['spell_id']
            preview=FightProjection.from_context(ctx)
            if ctx.actor(aid).current_ap < 3:
                return CastActionProjectionResult(certainty=Certainty.DETERMINISTIC,
                    legal=False,projection_complete=False,projection=preview)
            preview=proj.spend_ap(preview,aid,3)
            preview=proj.append_cast(preview,CastRecord(aid,sid,kw['grade'],
                            target_actor_id=ctx.actor_at(kw['target_cell']).actor_id,
                            target_cell=kw['target_cell'],ap_spent=3))
            return CastActionProjectionResult(certainty=Certainty.DETERMINISTIC,
                legal=True,projection_complete=True,projection=preview)
        s,m,c=synthetic_map_scene();s['actors']['777']['AP']=4
        c=replace(c,actors=(replace(c.actors[0],current_ap=4),c.actors[1]))
        r=self.check(scene=(s,m,c),kernel=self.fake_kernel(callback=synthetic_effect_free))
        self.assertEqual(r.status,'STOPPED_ILLEGAL')
        self.assertEqual(r.attempted_count,2)
        self.assertEqual((r.steps[0].after_ap,r.steps[1].before_ap),(1,1))

    def test_kernel_exception_does_not_escape(self):
        def bad(**kwargs):raise RuntimeError('injected')
        r=self.check(kernel=self.fake_kernel(callback=bad))
        self.assertEqual(r.status,'BLOCKED_KERNEL')
        self.assertEqual(r.attempted_count,0)

    def test_forged_complete_projection_without_cast_history_is_rejected(self):
        def forged(**kw):
            return CastActionProjectionResult(certainty=Certainty.DETERMINISTIC,
                legal=True,projection_complete=True,projection=FightProjection.from_context(kw['context']))
        r=self.check(kernel=self.fake_kernel(callback=forged))
        self.assertEqual(r.status,'BLOCKED_KERNEL')
        self.assertIn('P16_PROJECTION_INTEGRITY_CONFLICT',r.reasons)
        self.assertEqual(r.attempted_count,0)

    def test_forged_complete_projection_with_wrong_target_is_rejected(self):
        projection=FightProjectionService()
        def forged(**kw):
            ctx=kw['context'];aid=kw['caster_id'];sid=kw['spell_id']
            changed=projection.spend_ap(FightProjection.from_context(ctx),aid,3)
            changed=projection.append_cast(changed,CastRecord(aid,sid,kw['grade'],
                target_cell=CellId(220),ap_spent=3))
            return CastActionProjectionResult(certainty=Certainty.DETERMINISTIC,
                legal=True,projection_complete=True,projection=changed)
        r=self.check(kernel=self.fake_kernel(callback=forged))
        self.assertEqual(r.status,'BLOCKED_KERNEL')
        self.assertEqual(r.attempted_count,0)

    def test_kernel_return_wrong_type_fails_closed(self):
        r=self.check(kernel=self.fake_kernel(callback=lambda **kw: object()))
        self.assertEqual(r.status,'BLOCKED_KERNEL')
        self.assertIn('P16_INVALID_KERNEL_RESULT',r.reasons)

    def test_kernel_return_projection_wrong_type_fails_closed(self):
        def forged(**kw):
            return CastActionProjectionResult(certainty=Certainty.DETERMINISTIC,
                legal=True,projection_complete=True,projection='invalid')
        r=self.check(kernel=self.fake_kernel(callback=forged))
        self.assertIn('P16_INVALID_KERNEL_PROJECTION',r.reasons)

    def test_movement_sequence_outcome_unconfirmed_when_fixture_complete(self):
        service=FightProjectionService()
        def deterministic(**kw):
            context=kw['context'];aid=kw['caster_id'];sid=kw['spell_id']
            p=service.spend_ap(FightProjection.from_context(context),aid,3)
            actor=context.actor_at(kw['target_cell'])
            p=service.append_cast(p,CastRecord(aid,sid,kw['grade'],
                target_actor_id=actor.actor_id if actor else None,
                target_cell=kw['target_cell'],ap_spent=3))
            return CastActionProjectionResult(certainty=Certainty.DETERMINISTIC,
                legal=True,projection_complete=True,projection=p)
        r=self.check(build(move=201,sequence=((32435,3,229),)),
                     kernel=self.fake_kernel(callback=deterministic))
        self.assertEqual(r.status,'RESEARCH_ONLY')
        self.assertIn('MOVEMENT_OUTCOME_NOT_CONFIRMED',r.reasons)
        self.assertEqual(r.steps[0].after_mp,4)
        self.assertFalse(r.actionable)

    def test_cli_safe_synthetic_demo(self):
        done=subprocess.run([sys.executable,'-m','anka_app.cli','sequence-demo'],cwd=ROOT,
                            capture_output=True,text=True,timeout=30)
        self.assertEqual(done.returncode,0,done.stderr[-1200:])
        self.assertIn('ANKA_STATUS=STOPPED_UNCERTAIN',done.stdout)
        self.assertIn('"physical_input_sent": false',done.stdout)


if __name__=='__main__':unittest.main()
