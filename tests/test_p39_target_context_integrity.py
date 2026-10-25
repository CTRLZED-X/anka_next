"""P39: independently authored turn-scoped location and MP movement counterexamples.

Pure synthetic research.  No real server effects, actor window, or input.
"""
from hashlib import sha256
import unittest
from anka_contracts.canonical import EvidenceRef, CanonicalDraft
from anka_contracts.fight_semantic import FightResearchDraft
from anka_contracts.shadow_replay import ShadowScope
from anka_contracts.target_effect_research import TargetEffectWindow
from anka_app.target_effect_research_offline import audit_target_effect_windows


class TargetContextIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.scope = ShadowScope('p39_fixture', 'p39_offline', 1, 123, (111, 222),
            'synthetic.3.7', 'research_adapter', sha256(b'p39').hexdigest(), 1)

    def evidence(self, number):
        return EvidenceRef(self.scope.protocol_build, self.scope.adapter_id,
            'Research_Event', number, self.scope.transport_generation, self.scope.flow_digest)

    def fight(self, kind, index, actor=None, **kwargs):
        return FightResearchDraft(kind, self.evidence(index), self.scope.fight_id,
            actor_id=actor, **kwargs)

    def cell(self, index, actor, cell):
        return self.fight('ACTOR_CELL_OBSERVED', index, actor, cell_id=cell)

    def resource(self, index, actor, metric, value):
        return CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE', actor, self.evidence(index),
            resource=metric, value=value)

    def hp(self, index, actor, value=400):
        return CanonicalDraft('ACTOR_HP_ABSOLUTE', actor, self.evidence(index),
            value=value, maximum=400)

    def cast(self, index, actor=111):
        return self.fight('SPELL_CAST_OBSERVED', index, actor,
            spell_id=12, target_cell=215)

    def turn(self, kind, index, actor, ordinal):
        return self.fight(kind, index, actor, turn_index=ordinal)

    def compare(self, trace, before, cast, after, actor, metric, witness=None):
        return audit_target_effect_windows(tuple(trace), self.scope, (
            TargetEffectWindow(before, cast, after, actor, metric, witness),)).comparisons[0]

    def previous_turn_fixture(self, cell=215):
        return (
            self.fight('FIGHT_START_OBSERVED', 1),  # 0
            self.hp(2, 222),                       # 1: old baseline
            self.cell(3, 222, cell),               # 2: old location witness
            self.turn('TURN_START_OBSERVED', 4, 111, 0), # 3
            self.turn('TURN_END_OBSERVED', 5, 111, 0),   # 4
            self.turn('TURN_START_OBSERVED', 6, 222, 1), # 5
            self.turn('TURN_END_OBSERVED', 7, 222, 1),   # 6
            self.turn('TURN_START_OBSERVED', 8, 111, 2), # 7
            self.cast(9),                         # 8
            self.hp(10, 222, 350),                # 9
            self.turn('TURN_END_OBSERVED', 11, 111, 2),
            self.fight('FIGHT_END_OBSERVED', 12))

    def test_previous_turn_cell_match_is_stale_not_matched(self):
        c = self.compare(self.previous_turn_fixture(), 1, 8, 9, 222, 'HP', 2)
        self.assertEqual(c.location_relation, 'STALE_OBSERVATION')
        self.assertIn('P39_TARGET_CELL_WITNESS_CROSSES_COMPLETED_TURN', c.caveats)
        self.assertEqual(c.relation, 'AMBIGUOUS')

    def test_previous_turn_cell_mismatch_is_stale_not_confirmed_miss(self):
        c = self.compare(self.previous_turn_fixture(cell=214), 1, 8, 9, 222, 'HP', 2)
        self.assertEqual(c.location_relation, 'STALE_OBSERVATION')
        self.assertNotIn('P36_DIRECT_TARGET_CELL_NOT_MATCHED_AOE_UNKNOWN', c.caveats)

    def test_new_turn_witness_pre_turn_start_is_not_stale(self):
        t=(self.fight('FIGHT_START_OBSERVED',1),
           self.turn('TURN_START_OBSERVED',2,222,0),
           self.turn('TURN_END_OBSERVED',3,222,0),
           self.hp(4,222),                     # 3: current baseline
           self.cell(5,222,215),               # 4: after previous turn ended
           self.turn('TURN_START_OBSERVED',6,111,1),
           self.cast(7),                       # 6
           self.hp(8,222,350),                 # 7
           self.turn('TURN_END_OBSERVED',9,111,1),
           self.fight('FIGHT_END_OBSERVED',10))
        c=self.compare(t,3,6,7,222,'HP',4)
        self.assertEqual(c.location_relation,'MATCHED_OBSERVATION')
        self.assertEqual(c.relation,'CHANGED')

    def test_target_mp_movement_before_cast_is_confounder(self):
        t=(self.fight('FIGHT_START_OBSERVED',1),
           self.resource(2,111,'MP',6),         # 1
           self.cell(3,111,213),               # 2
           self.turn('TURN_START_OBSERVED',4,111,0),
           self.cell(5,111,214),               # 4: moved before cast
           self.cast(6),                       # 5
           self.resource(7,111,'MP',5),         # 6
           self.turn('TURN_END_OBSERVED',8,111,0),
           self.fight('FIGHT_END_OBSERVED',9))
        c=self.compare(t,1,5,6,111,'MP',2)
        self.assertEqual(c.relation,'AMBIGUOUS')
        self.assertIn('P39_TARGET_MOVED_BEFORE_CAST',c.caveats)
        self.assertEqual(c.numeric_delta,-1)

    def test_prior_cast_cell_update_same_cell_not_false_confounder(self):
        t=(self.fight('FIGHT_START_OBSERVED',1),
           self.resource(2,111,'MP',6),
           self.cell(3,111,215),
           self.turn('TURN_START_OBSERVED',4,111,0),
           self.cell(5,111,215),
           self.cast(6),
           self.resource(7,111,'MP',5),
           self.turn('TURN_END_OBSERVED',8,111,0),
           self.fight('FIGHT_END_OBSERVED',9))
        c=self.compare(t,1,5,6,111,'MP',2)
        self.assertEqual(c.relation,'CHANGED')
        self.assertNotIn('P39_TARGET_MOVED_BEFORE_CAST',c.caveats)

    def test_foreign_actor_movement_does_not_confound_mp(self):
        t=(self.fight('FIGHT_START_OBSERVED',1),
           self.resource(2,111,'MP',6),
           self.cell(3,111,215),
           self.turn('TURN_START_OBSERVED',4,111,0),
           self.cell(5,222,214),
           self.cast(6),
           self.resource(7,111,'MP',5),
           self.turn('TURN_END_OBSERVED',8,111,0),
           self.fight('FIGHT_END_OBSERVED',9))
        c=self.compare(t,1,5,6,111,'MP',2)
        self.assertEqual(c.relation,'CHANGED')

    def test_after_cast_target_movement_remains_confounder(self):
        t=(self.fight('FIGHT_START_OBSERVED',1),
           self.hp(2,222),
           self.cell(3,222,215),
           self.turn('TURN_START_OBSERVED',4,111,0),
           self.cast(5),
           self.cell(6,222,216),
           self.hp(7,222,350),
           self.turn('TURN_END_OBSERVED',8,111,0),
           self.fight('FIGHT_END_OBSERVED',9))
        c=self.compare(t,1,4,6,222,'HP',2)
        self.assertEqual(c.relation,'AMBIGUOUS')
        self.assertIn('P36_TARGET_MOVED_AFTER_CAST',c.caveats)

    def test_unverified_research_never_becomes_actionable(self):
        t=self.previous_turn_fixture()
        report=audit_target_effect_windows(t,self.scope,(TargetEffectWindow(1,8,9,222,'HP',2),))
        exported=report.to_dict()
        self.assertFalse(exported['actionable'])
        self.assertFalse(exported['server_effect_proven'])
        self.assertFalse(exported['current_build_certified'])
        self.assertNotIn('numeric_delta',str(exported))
        self.assertEqual(exported['committed_events'],0)
        self.assertEqual(exported['physical_input_sent'],False)

if __name__=='__main__':unittest.main()
