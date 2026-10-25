"""P35 adversarial source-linked resource and position observation windows."""
import unittest
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from anka_contracts.canonical import CanonicalDraft, EvidenceRef
from anka_contracts.fight_semantic import FightResearchDraft
from anka_contracts.effect_reconciliation import (
    ObservationWindow, ObservationComparison, EffectReconciliationReport)
from anka_contracts.shadow_replay import ShadowScope
from anka_app.effect_reconciliation_offline import (
    audit_effect_windows, effect_reconciliation_smoke)


class EffectReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.scope=ShadowScope('sensitive_session','private_name',2,42,(111,222),
            'Dofus 3.7.10.10','research_adapter','a'*64,5)

    def ref(self,number,message_index=0,**kwargs):
        return replace(EvidenceRef(self.scope.protocol_build,self.scope.adapter_id,
            'Research_Wire',number,self.scope.transport_generation,self.scope.flow_digest,
            message_index=message_index),**kwargs)

    def fight(self,kind,n,actor=None,**kw):
        return FightResearchDraft(kind,self.ref(n),self.scope.fight_id,actor_id=actor,**kw)

    def resource(self,n,metric='AP',value=11,actor=111):
        return CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',actor,self.ref(n),resource=metric,value=value)

    def hp(self,n,value=300,maximum=400,actor=111):
        return CanonicalDraft('ACTOR_HP_ABSOLUTE',actor,self.ref(n),value=value,maximum=maximum)

    def cds(self,n,items=((12,2),),actor=111):
        return CanonicalDraft('ACTOR_COOLDOWN_SNAPSHOT',actor,self.ref(n),cooldowns=items)

    def cell(self,n,cell=215,actor=111):
        return self.fight('ACTOR_CELL_OBSERVED',n,actor=actor,cell_id=cell)

    def flow(self,before=None,after=None,intermediate=()):
        before=before or self.resource(2)
        after=after or self.resource(5,value=8)
        return (self.fight('FIGHT_START_OBSERVED',1),before,
                self.fight('TURN_START_OBSERVED',3,111,turn_index=0),
                self.fight('SPELL_CAST_OBSERVED',4,111,spell_id=12,target_cell=215),
                *intermediate,after,
                self.fight('TURN_END_OBSERVED',8,111,turn_index=0),
                self.fight('FIGHT_END_OBSERVED',9))

    def audit(self,items=None,windows=None,scope=None):
        return audit_effect_windows(items if items is not None else self.flow(),
            scope or self.scope,windows if windows is not None else (ObservationWindow(1,3,4,'AP'),))

    def test_observed_ap_delta_never_proves_cast(self):
        result=self.audit()
        self.assertEqual(result.status,'GAPS_FOUND_RESEARCH_ONLY')
        self.assertEqual(result.comparisons[0].numeric_delta,-3)
        self.assertEqual(result.comparisons[0].relation,'CHANGED')
        self.assertIn('P35_NO_SERVER_CAUSAL_SETTLEMENT',result.reason_codes)
        self.assertFalse(result.actionable or result.live_state_mutated or result.physical_input_sent)

    def test_no_change_does_not_mean_rejected_cast(self):
        result=self.audit(self.flow(after=self.resource(5,value=11)))
        self.assertEqual(result.comparisons[0].relation,'UNCHANGED')
        self.assertIn('P35_NO_INDEPENDENT_SERVER_CAUSAL_PROOF',result.comparisons[0].caveats)

    def test_ap_increase_not_assumed_bug(self):
        result=self.audit(self.flow(after=self.resource(5,value=14)))
        self.assertEqual(result.comparisons[0].numeric_delta,3)
        self.assertEqual(result.status,'GAPS_FOUND_RESEARCH_ONLY')

    def test_hp_changes_no_damage_causation(self):
        result=self.audit(self.flow(before=self.hp(2),after=self.hp(5,250)),
              (ObservationWindow(1,3,4,'HP'),))
        self.assertEqual(result.comparisons[0].numeric_delta,-50)
        self.assertIn('P35_HP_CHANGE_SOURCE_UNKNOWN',result.comparisons[0].caveats)

    def test_hp_max_change_not_silently_ignored(self):
        result=self.audit(self.flow(before=self.hp(2,300,400),after=self.hp(5,300,450)),
              (ObservationWindow(1,3,4,'HP'),))
        self.assertEqual(result.comparisons[0].relation,'CHANGED')
        self.assertEqual(result.comparisons[0].numeric_delta,0)

    def test_cooldown_research_only(self):
        result=self.audit(self.flow(before=self.cds(2),after=self.cds(5,((12,1),))),
              (ObservationWindow(1,3,4,'COOLDOWN'),))
        self.assertEqual(result.comparisons[0].relation,'CHANGED')
        self.assertIsNone(result.comparisons[0].numeric_delta)
        self.assertIn('P35_COOLDOWN_CHRONOLOGY_UNVERIFIED',result.comparisons[0].caveats)

    def test_cell_change_no_mp_cost_claim(self):
        result=self.audit(self.flow(before=self.cell(2),after=self.cell(5,214)),
              (ObservationWindow(1,3,4,'CELL'),))
        self.assertEqual(result.comparisons[0].relation,'CHANGED')
        self.assertIn('P35_PATH_AND_MP_COST_UNKNOWN',result.comparisons[0].caveats)

    def test_mp_delta(self):
        result=self.audit(self.flow(before=self.resource(2,'MP',5),after=self.resource(5,'MP',4)),
              (ObservationWindow(1,3,4,'MP'),))
        self.assertEqual(result.comparisons[0].numeric_delta,-1)

    def test_range_delta(self):
        result=self.audit(self.flow(before=self.resource(2,'RANGE',5),after=self.resource(5,'RANGE',4)),
              (ObservationWindow(1,3,4,'RANGE'),))
        self.assertEqual(result.comparisons[0].numeric_delta,-1)

    def test_actor_mismatch_before(self):
        r=self.audit(self.flow(before=self.resource(2,actor=222)))
        self.assertEqual(r.reason_codes,('P35_BEFORE_AFTER_ACTOR_MISMATCH',))

    def test_actor_mismatch_after(self):
        r=self.audit(self.flow(after=self.resource(5,actor=222)))
        self.assertEqual(r.reason_codes,('P35_BEFORE_AFTER_ACTOR_MISMATCH',))

    def test_metric_kind_mismatch(self):
        r=self.audit(self.flow(before=self.hp(2)))
        self.assertEqual(r.reason_codes,('P35_RESOURCE_KIND_MISMATCH',))

    def test_target_action_not_cast(self):
        r=self.audit(self.flow(),(ObservationWindow(1,2,4,'AP'),))
        self.assertEqual(r.reason_codes,('P35_ACTION_MUST_BE_SPELL_OBSERVATION',))

    def test_wrong_ordering_spec_rejected(self):
        with self.assertRaisesRegex(ValueError,'P35_WINDOW_CONTRACT_INVALID'):
            ObservationWindow(3,1,4,'AP')

    def test_bool_index_rejected(self):
        with self.assertRaisesRegex(ValueError,'P35_WINDOW_CONTRACT_INVALID'):
            ObservationWindow(True,3,4,'AP')

    def test_unknown_metric_rejected(self):
        with self.assertRaisesRegex(ValueError,'P35_WINDOW_CONTRACT_INVALID'):
            ObservationWindow(1,3,4,'DAMAGE')

    def test_outside_trace_rejected(self):
        r=self.audit(self.flow(),(ObservationWindow(1,3,50,'AP'),))
        self.assertEqual(r.reason_codes,('P35_WINDOW_INDEX_OUTSIDE_TRACE',))

    def test_duplicate_link_rejected(self):
        w=ObservationWindow(1,3,4,'AP')
        r=self.audit(self.flow(),(w,w))
        self.assertEqual(r.reason_codes,('P35_DUPLICATE_ACTION_METRIC_LINK',))
        self.assertEqual(r.first_blocked_window,1)

    def test_different_source_same_position_rejected(self):
        flow=list(self.flow());flow[4]=replace(flow[4],evidence=self.ref(4))
        r=self.audit(tuple(flow))
        self.assertEqual(r.reason_codes,('P35_DISTINCT_ORDERED_SOURCE_COORDINATES_REQUIRED',))

    def test_source_scope_changed(self):
        flow=list(self.flow());flow[4]=replace(flow[4],evidence=self.ref(5,transport_generation=99))
        r=self.audit(tuple(flow))
        self.assertEqual(r.reason_codes,('P34_SOURCE_SCOPE_CHANGED',))

    def test_source_reordering(self):
        flow=list(self.flow());flow[4]=replace(flow[4],evidence=self.ref(1))
        r=self.audit(tuple(flow))
        self.assertEqual(r.reason_codes,('P34_SOURCE_REORDERED',))

    def test_cast_wrong_turn_rejected_by_existing_audit(self):
        flow=list(self.flow());flow[3]=replace(flow[3],actor_id=222)
        r=self.audit(tuple(flow))
        self.assertEqual(r.reason_codes,('P34_CAST_OUTSIDE_PROVEN_TURN',))

    def test_wrong_fight_blocked(self):
        flow=list(self.flow());flow[3]=replace(flow[3],fight_id=99)
        r=self.audit(tuple(flow))
        self.assertEqual(r.reason_codes,('P34_FIGHT_ID_MISMATCH',))

    def test_after_turn_boundary_rejected(self):
        flow=list(self.flow());flow[4],flow[5]=(flow[5],replace(flow[4],evidence=self.ref(10)))
        # make source chronology nondecreasing so the boundary check, not sorting, is decisive
        flow[5]=replace(flow[5],evidence=self.ref(8))
        flow[6]=replace(flow[6],evidence=self.ref(11))
        r=self.audit(tuple(flow),(ObservationWindow(1,3,5,'AP'),))
        self.assertEqual(r.reason_codes,('P35_POST_SNAPSHOT_OUTSIDE_ACTION_TURN',))

    def test_intervening_cast_is_ambiguous(self):
        flow=list(self.flow(intermediate=(self.fight('SPELL_CAST_OBSERVED',5,111,spell_id=13,target_cell=215),)))
        flow[5]=replace(flow[5],evidence=self.ref(6))
        r=self.audit(tuple(flow),(ObservationWindow(1,3,5,'AP'),))
        self.assertEqual(r.comparisons[0].relation,'AMBIGUOUS')
        self.assertIn('P35_INTERVENING_CAST_MAKES_DELTA_AMBIGUOUS',r.reason_codes)

    def test_reused_post_snapshot_across_different_casts_rejected(self):
        flow=list(self.flow(intermediate=(self.fight('SPELL_CAST_OBSERVED',5,111,spell_id=13,target_cell=215),)))
        flow[5]=replace(flow[5],evidence=self.ref(6))
        r=self.audit(tuple(flow),(ObservationWindow(1,3,5,'AP'),ObservationWindow(1,4,5,'AP')))
        self.assertEqual(r.reason_codes,('P35_REUSED_POST_SNAPSHOT_FOR_DIFFERENT_ACTION',))

    def test_no_windows_explicitly_incomplete(self):
        r=self.audit(self.flow(),())
        self.assertEqual(r.status,'INCOMPLETE_RESEARCH_ONLY')
        self.assertIn('P35_EXPLICIT_WINDOWS_MISSING',r.reason_codes)

    def test_empty_trace_blocked(self):
        r=self.audit((),())
        self.assertEqual(r.status,'BLOCKED_RESEARCH_ONLY')
        self.assertEqual(r.reason_codes,('P34_EMPTY_OR_EXCESSIVE_OBSERVATIONS',))

    def test_many_windows_rejected(self):
        with self.assertRaisesRegex(ValueError,'P35_TOO_MANY_WINDOWS'):
            self.audit(self.flow(),(ObservationWindow(1,3,4,'AP'),)*129)

    def test_report_cannot_claim_action_authority(self):
        r=self.audit()
        with self.assertRaises(TypeError):
            replace(r,actionable=True)
        with self.assertRaises(TypeError):
            replace(r,committed_events=1)

    def test_diagnostic_export_privacy(self):
        r=self.audit(self.flow(before=self.hp(2),after=self.hp(5,250)),(ObservationWindow(1,3,4,'HP'),))
        output=str(r.to_dict())
        for secret in ('private_name','sensitive_session','Dofus 3.7','research_adapter','a'*64,'-50',"'300'", "'250'"):
            self.assertNotIn(secret,output)
        self.assertFalse(r.to_dict()['current_build_certified'])
        self.assertFalse(r.to_dict()['game_server_outcome_certified'])

    def test_declared_causation_is_never_output(self):
        result=self.audit()
        self.assertNotIn('confirmed',result.status.lower())
        self.assertFalse(result.to_dict()['actionable'])
        self.assertFalse(result.to_dict()['physical_input_sent'])

    def test_smoke(self):
        self.assertEqual(effect_reconciliation_smoke()['status'],'PASS_RESEARCH_ONLY')

    def test_architecture_packages_not_tied_to_driver(self):
        import anka_contracts.effect_reconciliation as contract
        import anka_app.effect_reconciliation_offline as implementation
        for module in (contract,implementation):
            source=Path(module.__file__).read_text()
            for forbidden in ('from anka_execution', 'import anka_execution',
                              'from anka_capture', 'import anka_capture'):
                self.assertNotIn(forbidden,source)

if __name__=='__main__': unittest.main()
