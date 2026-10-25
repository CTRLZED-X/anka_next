"""P38 independently specified false-causality counterexamples across P35/P36.

These traces describe research observations only. Their expected ambiguity is
hand-authored, not generated from the algorithm being tested.
"""
from dataclasses import replace
from hashlib import sha256
import unittest

from anka_app.effect_reconciliation_offline import audit_effect_windows
from anka_app.target_effect_research_offline import audit_target_effect_windows
from anka_contracts.canonical import CanonicalDraft, EvidenceRef
from anka_contracts.effect_reconciliation import ObservationWindow
from anka_contracts.fight_semantic import FightResearchDraft
from anka_contracts.shadow_replay import ShadowScope
from anka_contracts.target_effect_research import TargetEffectWindow


class ResearchWindowConfounderTests(unittest.TestCase):
    def setUp(self):
        self.scope=ShadowScope('private_fixture','private_account',3,123,(111,222),
            'offline.3.7','research_adapter',sha256(b'p38-independent-fixture').hexdigest(),2)

    def ref(self, index):
        return EvidenceRef(self.scope.protocol_build,self.scope.adapter_id,
            'Research_Event',index,self.scope.transport_generation,self.scope.flow_digest)

    def event(self,kind,n,actor=None,**fields):
        return FightResearchDraft(kind,self.ref(n),123,actor_id=actor,**fields)

    def ap(self,n,value=10,actor=111,metric='AP'):
        return CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',actor,self.ref(n),resource=metric,value=value)

    def hp(self,n,value=400,actor=222):
        return CanonicalDraft('ACTOR_HP_ABSOLUTE',actor,self.ref(n),value=value,maximum=400)

    def cds(self,n,spell=12,remaining=2):
        return CanonicalDraft('ACTOR_COOLDOWN_SNAPSHOT',111,self.ref(n),cooldowns=((spell,remaining),))

    def cell(self,n,actor=111,cell=215):
        return self.event('ACTOR_CELL_OBSERVED',n,actor,cell_id=cell)

    def wrap(self,before,cast,after,between=()):
        # All events have distinct source packet positions. A change between
        # initial evidence and cast is explicitly *not* a causal postcondition.
        return (self.event('FIGHT_START_OBSERVED',1),before,
            self.event('TURN_START_OBSERVED',3,111,turn_index=0),
            *between,cast,after,
            self.event('TURN_END_OBSERVED',11,111,turn_index=0),
            self.event('FIGHT_END_OBSERVED',12))

    def test_p35_ap_changed_before_cast_is_ambiguous(self):
        trace=self.wrap(self.ap(2,10),self.event('SPELL_CAST_OBSERVED',6,111,spell_id=12,target_cell=215),
            self.ap(8,8),between=(self.ap(5,8),))
        report=audit_effect_windows(trace,self.scope,(ObservationWindow(1,4,5,'AP'),))
        self.assertEqual(report.comparisons[0].relation,'AMBIGUOUS')
        self.assertEqual(report.comparisons[0].numeric_delta,-2)
        self.assertIn('P38_INTERVENING_ACTOR_METRIC_OBSERVATION',report.comparisons[0].caveats)
        self.assertFalse(report.actionable)

    def test_p35_identical_post_after_intermediate_is_still_ambiguous(self):
        trace=self.wrap(self.ap(2,10),self.event('SPELL_CAST_OBSERVED',6,111,spell_id=12,target_cell=215),
            self.ap(8,10),between=(self.ap(5,8),))
        report=audit_effect_windows(trace,self.scope,(ObservationWindow(1,4,5,'AP'),))
        self.assertEqual(report.comparisons[0].relation,'AMBIGUOUS')
        self.assertEqual(report.comparisons[0].numeric_delta,0)

    def test_p35_intermediate_cooldown_is_ambiguous(self):
        trace=self.wrap(self.cds(2,remaining=3),self.event('SPELL_CAST_OBSERVED',6,111,spell_id=12,target_cell=215),
            self.cds(8,remaining=2),between=(self.cds(5,remaining=2),))
        report=audit_effect_windows(trace,self.scope,(ObservationWindow(1,4,5,'COOLDOWN'),))
        self.assertEqual(report.comparisons[0].relation,'AMBIGUOUS')
        self.assertIsNone(report.comparisons[0].numeric_delta)

    def test_p35_intermediate_hp_is_ambiguous(self):
        before=CanonicalDraft('ACTOR_HP_ABSOLUTE',111,self.ref(2),value=400,maximum=400)
        middle=CanonicalDraft('ACTOR_HP_ABSOLUTE',111,self.ref(5),value=350,maximum=400)
        after=CanonicalDraft('ACTOR_HP_ABSOLUTE',111,self.ref(8),value=350,maximum=400)
        trace=self.wrap(before,self.event('SPELL_CAST_OBSERVED',6,111,spell_id=12,target_cell=215),after,between=(middle,))
        report=audit_effect_windows(trace,self.scope,(ObservationWindow(1,4,5,'HP'),))
        self.assertEqual(report.comparisons[0].relation,'AMBIGUOUS')

    def test_p35_intermediate_cell_is_ambiguous(self):
        trace=self.wrap(self.cell(2),self.event('SPELL_CAST_OBSERVED',6,111,spell_id=12,target_cell=215),
            self.cell(8,cell=214),between=(self.cell(5,cell=214),))
        report=audit_effect_windows(trace,self.scope,(ObservationWindow(1,4,5,'CELL'),))
        self.assertEqual(report.comparisons[0].relation,'AMBIGUOUS')
        self.assertIn('P38_INTERVENING_ACTOR_METRIC_OBSERVATION',report.comparisons[0].caveats)

    def test_p35_mp_window_cell_observation_is_confounding(self):
        trace=self.wrap(self.ap(2,6,metric='MP'),self.event('SPELL_CAST_OBSERVED',6,111,spell_id=12,target_cell=215),
            self.ap(8,5,metric='MP'),between=(self.cell(5,cell=214),))
        report=audit_effect_windows(trace,self.scope,(ObservationWindow(1,4,5,'MP'),))
        self.assertEqual(report.comparisons[0].relation,'AMBIGUOUS')
        self.assertIn('P38_MP_WINDOW_CONTAINS_ACTOR_CELL_OBSERVATION',report.comparisons[0].caveats)

    def test_p35_unrelated_actor_snapshot_not_confounding(self):
        trace=self.wrap(self.ap(2,10),self.event('SPELL_CAST_OBSERVED',6,111,spell_id=12,target_cell=215),
            self.ap(8,8),between=(self.ap(5,4,actor=222),))
        report=audit_effect_windows(trace,self.scope,(ObservationWindow(1,4,5,'AP'),))
        self.assertEqual(report.comparisons[0].relation,'CHANGED')
        self.assertNotIn('P38_INTERVENING_ACTOR_METRIC_OBSERVATION',report.comparisons[0].caveats)

    def test_p35_unrelated_metric_snapshot_not_confounding(self):
        trace=self.wrap(self.ap(2,10),self.event('SPELL_CAST_OBSERVED',6,111,spell_id=12,target_cell=215),
            self.ap(8,8),between=(self.ap(5,4,metric='MP'),))
        report=audit_effect_windows(trace,self.scope,(ObservationWindow(1,4,5,'AP'),))
        self.assertEqual(report.comparisons[0].relation,'CHANGED')

    def previous_turn(self,target=False):
        before=self.hp(2) if target else self.ap(2)
        after=self.hp(10,350) if target else self.ap(10,8)
        return (self.event('FIGHT_START_OBSERVED',1),before,
            self.event('TURN_START_OBSERVED',3,111,turn_index=0),
            self.event('TURN_END_OBSERVED',4,111,turn_index=0),
            self.event('TURN_START_OBSERVED',5,222,turn_index=1),
            self.event('TURN_END_OBSERVED',6,222,turn_index=1),
            self.event('TURN_START_OBSERVED',7,111,turn_index=2),
            self.cell(8,actor=222,cell=215) if target else self.ap(8,8,actor=222),
            self.event('SPELL_CAST_OBSERVED',9,111,spell_id=12,target_cell=215),after,
            self.event('TURN_END_OBSERVED',11,111,turn_index=2),
            self.event('FIGHT_END_OBSERVED',12))

    def test_p35_previous_completed_turn_baseline_is_ambiguous(self):
        trace=self.previous_turn()
        report=audit_effect_windows(trace,self.scope,(ObservationWindow(1,8,9,'AP'),))
        self.assertEqual(report.comparisons[0].relation,'AMBIGUOUS')
        self.assertIn('P38_BASELINE_CROSSES_COMPLETED_TURN',report.comparisons[0].caveats)
        self.assertFalse(report.actionable)

    def test_p36_previous_completed_turn_baseline_is_ambiguous(self):
        trace=self.previous_turn(target=True)
        report=audit_target_effect_windows(trace,self.scope,(TargetEffectWindow(1,8,9,222,'HP',7),))
        self.assertEqual(report.comparisons[0].relation,'AMBIGUOUS')
        self.assertIn('P38_BASELINE_CROSSES_COMPLETED_TURN',report.comparisons[0].caveats)
        self.assertFalse(report.actionable)
        self.assertFalse(report.to_dict()['server_effect_proven'])

    def test_p36_new_turn_start_alone_not_false_blocked(self):
        trace=(self.event('FIGHT_START_OBSERVED',1), self.hp(2),
            self.event('TURN_START_OBSERVED',3,111,turn_index=0),
            self.cell(4,actor=222),
            self.event('SPELL_CAST_OBSERVED',5,111,spell_id=12,target_cell=215),
            self.hp(6,350),
            self.event('TURN_END_OBSERVED',7,111,turn_index=0),
            self.event('FIGHT_END_OBSERVED',8))
        report=audit_target_effect_windows(trace,self.scope,(TargetEffectWindow(1,4,5,222,'HP',3),))
        self.assertEqual(report.comparisons[0].relation,'CHANGED')
        self.assertNotIn('P38_BASELINE_CROSSES_COMPLETED_TURN',report.comparisons[0].caveats)

    def test_p35_explicit_no_causality_even_without_confounders(self):
        trace=self.wrap(self.ap(2,10),self.event('SPELL_CAST_OBSERVED',6,111,spell_id=12,target_cell=215),self.ap(8,8))
        report=audit_effect_windows(trace,self.scope,(ObservationWindow(1,3,4,'AP'),))
        self.assertEqual(report.comparisons[0].relation,'CHANGED')
        self.assertFalse(report.to_dict()['game_server_outcome_certified'])
        self.assertFalse(report.actionable)


if __name__=='__main__':
    unittest.main()
