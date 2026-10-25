"""P41 adversarial, hand-authored research traces: cell refresh != movement.

These traces contain synthetic observations only; no server-effect proof or input.
"""
import unittest
from hashlib import sha256

from anka_app.effect_reconciliation_offline import audit_effect_windows
from anka_app.target_effect_research_offline import audit_target_effect_windows
from anka_contracts.canonical import CanonicalDraft, EvidenceRef
from anka_contracts.effect_reconciliation import ObservationWindow
from anka_contracts.fight_semantic import FightResearchDraft
from anka_contracts.shadow_replay import ShadowScope
from anka_contracts.target_effect_research import TargetEffectWindow


class CellTransitionTests(unittest.TestCase):
    def setUp(self):
        self.scope = ShadowScope('p41_synthetic', 'fixture', 1, 123, (111, 222),
                                 'offline_3.7', 'research_adapter', sha256(b'p41').hexdigest(), 1)

    def ref(self, ordinal):
        s = self.scope
        return EvidenceRef(s.protocol_build, s.adapter_id, 'Research_Event', ordinal,
                           s.transport_generation, s.flow_digest)

    def event(self, kind, ordinal, actor=None, **kwargs):
        return FightResearchDraft(kind, self.ref(ordinal), self.scope.fight_id,
                                  actor_id=actor, **kwargs)

    def cell(self, ordinal, actor, cell):
        return self.event('ACTOR_CELL_OBSERVED', ordinal, actor, cell_id=cell)

    def mp(self, ordinal, actor, value):
        return CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE', actor, self.ref(ordinal),
                              resource='MP', value=value)

    def hp(self, ordinal, actor, value):
        return CanonicalDraft('ACTOR_HP_ABSOLUTE', actor, self.ref(ordinal),
                              value=value, maximum=400)

    def cast(self, ordinal):
        return self.event('SPELL_CAST_OBSERVED', ordinal, 111, spell_id=12, target_cell=215)

    def make_trace(self, *, target=False, initial_cell=215, refreshed_cell=215,
            include_anchor=True, include_refresh=True, roundtrip=False):
        actor = 222 if target else 111
        arr = [self.event('FIGHT_START_OBSERVED', 1)]
        arr.append(self.hp(2, actor, 400) if target else self.mp(2, actor, 6))
        if include_anchor:
            arr.append(self.cell(3, actor, initial_cell))
        arr.append(self.event('TURN_START_OBSERVED', 4, 111, turn_index=0))
        cast_idx = len(arr)
        arr.append(self.cast(5))
        if roundtrip:
            arr.append(self.cell(6, actor, 216))
        if include_refresh:
            arr.append(self.cell(7, actor, refreshed_cell))
        after_idx = len(arr)
        arr.append(self.hp(8, actor, 360) if target else self.mp(8, actor, 5))
        arr.extend((self.event('TURN_END_OBSERVED', 9, 111, turn_index=0),
                    self.event('FIGHT_END_OBSERVED', 10)))
        return tuple(arr), cast_idx, after_idx

    def inspect(self, *, target=False, **kwargs):
        trace, cast_idx, after_idx = self.make_trace(target=target, **kwargs)
        if target:
            window = TargetEffectWindow(1, cast_idx, after_idx, 222, 'HP',
                                        2 if kwargs.get('include_anchor', True) else None)
            report = audit_target_effect_windows(trace, self.scope, (window,))
        else:
            report = audit_effect_windows(trace, self.scope,
                                          (ObservationWindow(1, cast_idx, after_idx, 'MP'),))
        self.assertEqual(report.status, 'GAPS_FOUND_RESEARCH_ONLY', report.reason_codes)
        self.assertFalse(report.actionable)
        self.assertFalse(report.physical_input_sent)
        self.assertEqual(report.committed_events, 0)
        return report.comparisons[0]

    def test_p35_same_cell_refresh_is_not_movement(self):
        c = self.inspect()
        self.assertEqual(c.relation, 'CHANGED')
        self.assertNotIn('P38_MP_WINDOW_CONTAINS_ACTOR_CELL_OBSERVATION', c.caveats)

    def test_p36_same_cell_refresh_is_not_movement(self):
        c = self.inspect(target=True)
        self.assertEqual(c.relation, 'CHANGED')
        self.assertNotIn('P36_TARGET_MOVED_AFTER_CAST', c.caveats)
        self.assertFalse(c.to_dict()['server_effect_proven'])

    def test_p35_genuine_displacement_remains_ambiguous(self):
        c = self.inspect(refreshed_cell=216)
        self.assertEqual(c.relation, 'AMBIGUOUS')
        self.assertIn('P38_MP_WINDOW_CONTAINS_ACTOR_CELL_OBSERVATION', c.caveats)

    def test_p36_genuine_displacement_remains_ambiguous(self):
        c = self.inspect(target=True, refreshed_cell=216)
        self.assertEqual(c.relation, 'AMBIGUOUS')
        self.assertIn('P36_TARGET_MOVED_AFTER_CAST', c.caveats)

    def test_p35_departure_and_return_still_confounds(self):
        c = self.inspect(roundtrip=True)
        self.assertEqual(c.relation, 'AMBIGUOUS')
        self.assertIn('P38_MP_WINDOW_CONTAINS_ACTOR_CELL_OBSERVATION', c.caveats)

    def test_p36_departure_and_return_still_confounds(self):
        c = self.inspect(target=True, roundtrip=True)
        self.assertEqual(c.relation, 'AMBIGUOUS')
        self.assertIn('P36_TARGET_MOVED_AFTER_CAST', c.caveats)

    def test_p35_unanchored_post_cell_is_not_clean(self):
        c = self.inspect(include_anchor=False)
        self.assertEqual(c.relation, 'AMBIGUOUS')
        self.assertIn('P41_CELL_TRANSITION_BASELINE_MISSING', c.caveats)

    def test_p36_unanchored_post_cell_is_not_clean(self):
        c = self.inspect(target=True, include_anchor=False)
        self.assertEqual(c.relation, 'AMBIGUOUS')
        self.assertIn('P41_CELL_TRANSITION_BASELINE_MISSING', c.caveats)

    def test_p35_unanchored_pre_cast_cell_stays_ambiguous(self):
        c = self.inspect(include_refresh=False)
        self.assertEqual(c.relation, 'AMBIGUOUS')
        self.assertIn('P38_MP_WINDOW_CONTAINS_ACTOR_CELL_OBSERVATION', c.caveats)

    def test_p36_no_post_cell_no_new_confounder(self):
        c = self.inspect(target=True, include_refresh=False)
        self.assertEqual(c.relation, 'CHANGED')

    def test_unrelated_actor_cell_does_not_confound(self):
        trace, cast, after = self.make_trace()
        source = list(trace)
        source.insert(after, self.cell(7, 222, 216))
        report = audit_effect_windows(tuple(source), self.scope,
                                      (ObservationWindow(1, cast, after+1, 'MP'),))
        self.assertEqual(report.comparisons[0].relation, 'CHANGED')


if __name__ == '__main__':
    unittest.main()
