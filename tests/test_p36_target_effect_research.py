"""P36: target observation research must resist false causal attribution."""
import unittest
from dataclasses import replace
from hashlib import sha256

from anka_app.target_effect_research_offline import (
    audit_target_effect_windows, target_effect_research_smoke)
from anka_contracts.target_effect_research import (
    TargetEffectWindow, TargetEffectResearchReport, TargetEffectComparison)
from anka_contracts.canonical import CanonicalDraft, EvidenceRef
from anka_contracts.fight_semantic import FightResearchDraft
from anka_contracts.shadow_replay import ShadowScope


class TestP36TargetEffects(unittest.TestCase):
    def setUp(self):
        self.scope=ShadowScope('private_session','private_actor',2,42,(111,222),
            'Dofus 3.7.10.10','research_adapter',sha256(b'source').hexdigest(),5)

    def ref(self,n):
        return EvidenceRef(self.scope.protocol_build,self.scope.adapter_id,'Server_Research',
             n,self.scope.transport_generation,self.scope.flow_digest)

    def f(self,kind,n,actor=None,**kw):
        return FightResearchDraft(kind,self.ref(n),42,actor_id=actor,**kw)

    def hp(self,n,v=400,actor=222,maxval=400):
        return CanonicalDraft('ACTOR_HP_ABSOLUTE',actor,self.ref(n),value=v,maximum=maxval)

    def res(self,n,kind='AP',value=10,actor=222):
        return CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',actor,self.ref(n),resource=kind,value=value)

    def fixtures(self,metric='HP',extra=(),before=None,after=None,cell=215):
        if metric=='HP':
            before=before or self.hp(2);after=after or self.hp(8,360)
        else:
            before=before or self.res(2,metric,10);after=after or self.res(8,metric,8)
        source=(self.f('FIGHT_START_OBSERVED',1),before,
          self.f('ACTOR_CELL_OBSERVED',3,222,cell_id=cell),
          self.f('TURN_START_OBSERVED',4,111,turn_index=0),
          self.f('SPELL_CAST_OBSERVED',5,111,spell_id=12,target_cell=215),
          *extra,after,
          self.f('TURN_END_OBSERVED',10,111,turn_index=0),
          self.f('FIGHT_END_OBSERVED',11))
        return source

    def audit(self,items=None,windows=None):
        a=items if items is not None else self.fixtures()
        ws=windows if windows is not None else (TargetEffectWindow(1,4,len(a)-3,222,'HP',2),)
        return audit_target_effect_windows(a,self.scope,ws)

    def test_hp_change_is_not_damage_proof(self):
        r=self.audit()
        self.assertEqual(r.comparisons[0].numeric_delta,-40)
        self.assertEqual(r.comparisons[0].relation,'CHANGED')
        self.assertIn('P36_CAUSAL_TARGET_EFFECT_UNPROVEN',r.comparisons[0].caveats)
        self.assertFalse(r.actionable or r.physical_input_sent or r.committed_events)
        self.assertFalse(r.to_dict()['server_effect_proven'])

    def test_matching_target_cell_is_only_spatial_observation(self):
        c=self.audit().comparisons[0]
        self.assertEqual(c.location_relation,'MATCHED_OBSERVATION')
        self.assertIn('P36_CELL_MATCH_NOT_HIT_OR_SERVER_CAUSAL_PROOF',c.caveats)

    def test_target_cell_mismatch_does_not_infer_spell_missed(self):
        r=self.audit(self.fixtures(cell=214))
        self.assertEqual(r.comparisons[0].location_relation,'MISMATCHED_OBSERVATION')
        self.assertIn('P36_DIRECT_TARGET_CELL_NOT_MATCHED_AOE_UNKNOWN',r.comparisons[0].caveats)
        self.assertFalse(r.actionable)

    def test_missing_cell_proof_is_explicit(self):
        r=self.audit(windows=(TargetEffectWindow(1,4,5,222),))
        self.assertEqual(r.comparisons[0].location_relation,'UNKNOWN')
        self.assertIn('P36_TARGET_CELL_EVIDENCE_MISSING',r.comparisons[0].caveats)

    def test_change_equal_not_rejected_cast(self):
        r=self.audit(self.fixtures(after=self.hp(8,400)))
        self.assertEqual(r.comparisons[0].relation,'UNCHANGED')
        self.assertFalse(r.to_dict()['server_effect_proven'])

    def test_resource_mp_drain_not_proven(self):
        r=self.audit(self.fixtures('MP'), (TargetEffectWindow(1,4,5,222,'MP',2),))
        self.assertEqual(r.comparisons[0].numeric_delta,-2)
        self.assertFalse(r.actionable)

    def test_resource_ap_drain_not_proven(self):
        r=self.audit(self.fixtures('AP'), (TargetEffectWindow(1,4,5,222,'AP',2),))
        self.assertEqual(r.comparisons[0].relation,'CHANGED')
        self.assertFalse(r.physical_input_sent)

    def test_intervening_other_cast_marks_ambiguous(self):
        # An extra cast from the current turn owner may explain the same HP loss.
        a=self.fixtures(extra=(self.f('SPELL_CAST_OBSERVED',6,111,spell_id=13,target_cell=215),))
        a=list(a);a[6]=replace(a[6],evidence=self.ref(8)); a=tuple(a)
        r=self.audit(a,(TargetEffectWindow(1,4,6,222,'HP',2),))
        self.assertEqual(r.comparisons[0].relation,'AMBIGUOUS')
        self.assertIn('P36_COMPETING_CAST_OBSERVED',r.comparisons[0].caveats)

    def test_intervening_hp_before_cast_is_confounder(self):
        # Source-order gives no right to attribute an earlier HP drop to later cast.
        a=(self.f('FIGHT_START_OBSERVED',1),self.hp(2),self.hp(3,350),
          self.f('ACTOR_CELL_OBSERVED',4,222,cell_id=215),
          self.f('TURN_START_OBSERVED',5,111,turn_index=0),
          self.f('SPELL_CAST_OBSERVED',6,111,spell_id=12,target_cell=215),
          self.hp(8,350),self.f('TURN_END_OBSERVED',9,111,turn_index=0),
          self.f('FIGHT_END_OBSERVED',10))
        r=self.audit(a,(TargetEffectWindow(1,5,6,222,'HP',3),))
        self.assertEqual(r.comparisons[0].relation,'AMBIGUOUS')
        self.assertIn('P36_INTERVENING_TARGET_ABSOLUTE_VALUE',r.comparisons[0].caveats)

    def test_target_move_after_cast_is_confounder(self):
        a=self.fixtures(extra=(self.f('ACTOR_CELL_OBSERVED',6,222,cell_id=216),))
        a=list(a);a[6]=replace(a[6],evidence=self.ref(8));a=tuple(a)
        r=self.audit(a,(TargetEffectWindow(1,4,6,222,'HP',2),))
        self.assertEqual(r.comparisons[0].relation,'AMBIGUOUS')
        self.assertIn('P36_TARGET_MOVED_AFTER_CAST',r.comparisons[0].caveats)

    def test_cell_witness_overridden_before_cast(self):
        a=(self.f('FIGHT_START_OBSERVED',1),self.hp(2),
          self.f('ACTOR_CELL_OBSERVED',3,222,cell_id=215),
          self.f('ACTOR_CELL_OBSERVED',4,222,cell_id=216),
          self.f('TURN_START_OBSERVED',5,111,turn_index=0),
          self.f('SPELL_CAST_OBSERVED',6,111,spell_id=12,target_cell=215),
          self.hp(7,360),self.f('TURN_END_OBSERVED',8,111,turn_index=0),
          self.f('FIGHT_END_OBSERVED',9))
        r=self.audit(a,(TargetEffectWindow(1,5,6,222,'HP',2),))
        self.assertEqual(r.comparisons[0].location_relation,'STALE_OBSERVATION')

    def test_wrong_target_actor_blocks(self):
        r=self.audit(windows=(TargetEffectWindow(1,4,5,333,'HP',2),))
        self.assertEqual(r.reason_codes,('P36_TARGET_OUTSIDE_VERIFIED_RESEARCH_ROSTER',))

    def test_hp_actor_mismatch_blocks(self):
        r=self.audit(self.fixtures(after=self.hp(8,390,actor=111)))
        self.assertEqual(r.reason_codes,('P36_TARGET_OBSERVATION_ACTOR_INVALID',))

    def test_wrong_metric_blocks(self):
        r=self.audit(windows=(TargetEffectWindow(1,4,5,222,'AP',2),))
        self.assertEqual(r.reason_codes,('P36_TARGET_METRIC_KIND_MISMATCH',))

    def test_not_cast_blocks(self):
        r=self.audit(windows=(TargetEffectWindow(1,3,5,222,'HP',2),))
        self.assertEqual(r.reason_codes,('P36_CAST_OBSERVATION_REQUIRED',))

    def test_not_cell_witness_blocks(self):
        r=self.audit(windows=(TargetEffectWindow(1,4,5,222,'HP',1),))
        self.assertEqual(r.reason_codes,('P36_TARGET_CELL_WITNESS_INVALID',))

    def test_duplicate_rejected(self):
        w=TargetEffectWindow(1,4,5,222,'HP',2)
        r=self.audit(windows=(w,w))
        self.assertEqual(r.first_blocked_window,1)
        self.assertEqual(r.reason_codes,('P36_DUPLICATE_TARGET_METRIC_WINDOW',))

    def test_window_bounds_rejected(self):
        r=self.audit(windows=(TargetEffectWindow(1,4,500,222,'HP',2),))
        self.assertEqual(r.reason_codes,('P36_WINDOW_INDEX_OUTSIDE_TRACE',))

    def test_no_windows_incomplete(self):
        r=self.audit(windows=())
        self.assertEqual(r.status,'INCOMPLETE_RESEARCH_ONLY')

    def test_invalid_trace_without_windows_still_blocks(self):
        r=self.audit(items=(),windows=())
        self.assertEqual(r.status,'BLOCKED_RESEARCH_ONLY')
        self.assertEqual(r.reason_codes,('P34_EMPTY_OR_EXCESSIVE_OBSERVATIONS',))
        self.assertIsNone(r.first_blocked_window)

    def test_wrong_scope_blocks_before_reading_hp(self):
        a=list(self.fixtures());a[5]=replace(a[5],evidence=replace(a[5].evidence,transport_generation=99))
        r=self.audit(tuple(a))
        self.assertEqual(r.reason_codes,('P34_SOURCE_SCOPE_CHANGED',))

    def test_reused_target_post_across_casts(self):
        a=self.fixtures(extra=(self.f('SPELL_CAST_OBSERVED',6,111,spell_id=13,target_cell=215),))
        a=list(a);a[6]=replace(a[6],evidence=self.ref(8));a=tuple(a)
        r=self.audit(a,(TargetEffectWindow(1,4,6,222,'HP',2), TargetEffectWindow(1,5,6,222,'HP',2)))
        self.assertEqual(r.reason_codes,('P36_REUSED_POST_SNAPSHOT_FOR_DIFFERENT_CAST',))

    def test_report_does_not_export_pii_or_deltas(self):
        r=self.audit();d=r.to_dict()
        self.assertNotIn('numeric_delta',repr(d))
        self.assertNotIn('private_session',repr(d))
        self.assertNotIn('private_actor',repr(d))
        self.assertNotIn('400',repr(d))
        self.assertEqual(d['authority'],'RESEARCH_ONLY_NOT_CANONICAL')

    def test_contract_rejects_bool_and_order(self):
        for kw in ({'before_index':True},{'after_index':2},{'target_actor_id':0},
                   {'target_cell_index':4},{'metric':'DAMAGE'}):
            defaults=dict(before_index=1,cast_index=4,after_index=5,target_actor_id=222)
            defaults.update(kw)
            with self.assertRaisesRegex(ValueError,'P36_TARGET_WINDOW_INVALID'):
                TargetEffectWindow(**defaults)

    def test_report_forged_authority_rejected(self):
        with self.assertRaises(TypeError):
            TargetEffectResearchReport('GAPS_FOUND_RESEARCH_ONLY',(),5,1,(),actionable=True)
        with self.assertRaises(ValueError):
            TargetEffectComparison(0,'HP','CONFIRMED','UNKNOWN',('x',),-20)

    def test_smoke(self):
        r=target_effect_research_smoke()
        self.assertEqual(r['status'],'PASS_RESEARCH_ONLY')
        self.assertFalse(r['current_build_certified'] or r['physical_input_sent'])

if __name__=='__main__':unittest.main()
