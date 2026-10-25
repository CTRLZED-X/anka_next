"""P34: no spell/effect reconstruction by omission; no authority bypass."""
import inspect
import unittest
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from anka_contracts.canonical import EvidenceRef,CanonicalDraft
from anka_contracts.fight_semantic import FightResearchDraft
from anka_contracts.reconstruction_gaps import ReconstructionCoverageReport,CoverageEntry
from anka_contracts.shadow_replay import ShadowScope
from anka_app.reconstruction_gaps_offline import audit_reconstruction_coverage
from anka_app.shadow_replay_offline import run_shadow_replay

class ReconstructionGapTests(unittest.TestCase):
    def setUp(self):
        self.scope=ShadowScope('sensitive_session','sensitive_cra',1,42,(111,222),
              'Dofus 3.7.10.10','test_adapter','a'*64,1)

    def ref(self,n,index=0,**changes):
        return replace(EvidenceRef(self.scope.protocol_build,self.scope.adapter_id,
                        'Test_Wire',n,self.scope.transport_generation,self.scope.flow_digest,
                        message_index=index),**changes)

    def f(self,kind,n,**kwargs):
        return FightResearchDraft(kind,self.ref(n),self.scope.fight_id,**kwargs)

    def r(self,n,name='AP',value=11,actor=111,index=0):
        return CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',actor,self.ref(n,index),resource=name,value=value)

    def cast_flow(self):
        return (self.f('FIGHT_START_OBSERVED',1),
                self.f('ACTOR_CELL_OBSERVED',2,actor_id=111,cell_id=215),
                self.r(3),
                self.f('TURN_START_OBSERVED',4,actor_id=111,turn_index=0),
                self.f('SPELL_CAST_OBSERVED',5,actor_id=111,spell_id=12,target_cell=215),
                self.f('TURN_END_OBSERVED',6,actor_id=111,turn_index=0),
                self.f('FIGHT_END_OBSERVED',7))

    def test_cast_not_silently_removed_and_no_authority(self):
        items=self.cast_flow()
        old=run_shadow_replay(items,self.scope)
        self.assertEqual(old.reason_codes[0],'P33_SPELL_CAST_REDUCER_UNSUPPORTED')
        report=audit_reconstruction_coverage(items,self.scope)
        self.assertEqual(report.status,'GAPS_FOUND_RESEARCH_ONLY')
        self.assertEqual(report.spell_cast_observations,1)
        self.assertEqual(report.cell_observations,1)
        self.assertEqual(report.observations,7)
        self.assertEqual(report.projected_events,8)  # synthetic two actor registrations
        self.assertEqual(report.final_phase,'ENDED')
        for k in ('CAST_EFFECTS_UNVERIFIED','CAST_AP_SETTLEMENT_UNVERIFIED',
                  'CAST_LIMITS_AND_COOLDOWNS_UNVERIFIED','SERVER_CAST_ACCEPTANCE_UNVERIFIED',
                  'FIGHT_OUTCOME_NOT_VERIFIED','MOVEMENT_PATH_AND_MP_COST_UNVERIFIED',
                  'P34_ACTOR_FIELDS_MISSING'):
            self.assertIn(k,report.reason_codes)
        self.assertEqual(report.committed_events,0)
        self.assertFalse(report.actionable or report.physical_input_sent or report.live_state_mutated)

    def test_full_resources_are_not_gameplay_proof(self):
        items=[self.f('FIGHT_START_OBSERVED',1)]
        n=2
        for actor in self.scope.roster_fixture:
            items.append(self.f('ACTOR_CELL_OBSERVED',n,actor_id=actor,cell_id=n));n+=1
            items.append(CanonicalDraft('ACTOR_HP_ABSOLUTE',actor,self.ref(n),value=200,maximum=300));n+=1
            for resource in ('AP','MP'):
                items.append(self.r(n,resource,7,actor));n+=1
            items.append(CanonicalDraft('ACTOR_COOLDOWN_SNAPSHOT',actor,self.ref(n),cooldowns=((12,2),)));n+=1
        items.append(self.f('FIGHT_END_OBSERVED',n))
        report=audit_reconstruction_coverage(tuple(items),self.scope)
        self.assertEqual(report.complete_actor_fields,report.expected_actor_fields)
        self.assertEqual(report.expected_actor_fields,12)
        self.assertTrue(report.to_dict()['roster_is_synthetic_fixture'])
        self.assertIn('FIGHT_OUTCOME_NOT_VERIFIED',report.reason_codes)
        self.assertFalse(report.to_dict()['current_build_certified'])

    def test_missing_fields_count_uses_no_synthetic_defaults(self):
        items=(self.f('FIGHT_START_OBSERVED',1),self.r(2),self.f('FIGHT_END_OBSERVED',3))
        report=audit_reconstruction_coverage(items,self.scope)
        self.assertEqual(report.complete_actor_fields,1)
        self.assertEqual(report.expected_actor_fields,12)
        self.assertIn('P34_ACTOR_FIELDS_MISSING',report.reason_codes)

    def test_no_observations(self):
        r=audit_reconstruction_coverage((),self.scope)
        self.assertEqual(r.status,'BLOCKED_RESEARCH_ONLY')
        self.assertEqual(r.reason_codes,('P34_EMPTY_OR_EXCESSIVE_OBSERVATIONS',))

    def test_excessive_observations(self):
        r=audit_reconstruction_coverage([self.f('FIGHT_START_OBSERVED',1)]*4097,self.scope)
        self.assertEqual(r.status,'BLOCKED_RESEARCH_ONLY')

    def test_cast_without_turn_blocks(self):
        seq=(self.cast_flow()[0],self.cast_flow()[4])
        self.assertEqual(audit_reconstruction_coverage(seq,self.scope).reason_codes,
                         ('P34_CAST_OUTSIDE_PROVEN_TURN',))

    def test_cast_wrong_owner_blocks(self):
        seq=list(self.cast_flow());seq[4]=replace(seq[4],actor_id=222)
        r=audit_reconstruction_coverage(seq,self.scope)
        self.assertEqual(r.reason_codes,('P34_CAST_OUTSIDE_PROVEN_TURN',))
        self.assertEqual(r.first_blocked_index,4)

    def test_cast_after_turn_end_blocks(self):
        seq=list(self.cast_flow());seq[4],seq[5]=seq[5],seq[4]
        seq[4]=replace(seq[4],evidence=self.ref(5))
        seq[5]=replace(seq[5],evidence=self.ref(6))
        r=audit_reconstruction_coverage(seq,self.scope)
        self.assertEqual(r.reason_codes,('P34_CAST_OUTSIDE_PROVEN_TURN',))

    def test_cast_after_fight_end_blocks(self):
        seq=self.cast_flow()
        cast=replace(seq[4],evidence=self.ref(8))
        r=audit_reconstruction_coverage(seq+(cast,),self.scope)
        self.assertEqual(r.reason_codes,('P34_EVENT_AFTER_FIGHT_END',))

    def test_cast_wrong_fight_blocks(self):
        seq=list(self.cast_flow());seq[4]=replace(seq[4],fight_id=43)
        self.assertEqual(audit_reconstruction_coverage(seq,self.scope).reason_codes[0],'P34_FIGHT_ID_MISMATCH')

    def test_cast_wrong_generation_blocks(self):
        seq=list(self.cast_flow());seq[4]=replace(seq[4],evidence=self.ref(5,transport_generation=7))
        self.assertEqual(audit_reconstruction_coverage(seq,self.scope).reason_codes[0],'P34_SOURCE_SCOPE_CHANGED')

    def test_cast_wrong_build_blocks(self):
        seq=list(self.cast_flow());seq[4]=replace(seq[4],evidence=self.ref(5,protocol_build='other'))
        self.assertEqual(audit_reconstruction_coverage(seq,self.scope).reason_codes[0],'P34_SOURCE_SCOPE_CHANGED')

    def test_cast_wrong_flow_blocks(self):
        seq=list(self.cast_flow());seq[4]=replace(seq[4],evidence=self.ref(5,flow_digest='b'*64))
        self.assertEqual(audit_reconstruction_coverage(seq,self.scope).reason_codes[0],'P34_SOURCE_SCOPE_CHANGED')

    def test_cast_unknown_actor_blocks(self):
        seq=list(self.cast_flow());seq[4]=replace(seq[4],actor_id=333)
        self.assertEqual(audit_reconstruction_coverage(seq,self.scope).reason_codes[0],'P34_ACTOR_OUTSIDE_SYNTHETIC_ROSTER')

    def test_duplicate_cast_source_blocks(self):
        seq=list(self.cast_flow());seq.insert(5,seq[4]);
        self.assertEqual(audit_reconstruction_coverage(seq,self.scope).reason_codes[0],
                         'P34_DUPLICATE_OR_CONFLICTING_SOURCE_CLAIM')

    def test_distinct_cast_occurrences_not_deduplicated(self):
        seq=list(self.cast_flow());seq.insert(5,replace(seq[4],evidence=self.ref(5,index=1)))
        report=audit_reconstruction_coverage(tuple(seq),self.scope)
        self.assertEqual(report.spell_cast_observations,2)
        self.assertEqual(report.status,'GAPS_FOUND_RESEARCH_ONLY')

    def test_cast_packet_reordered_blocks(self):
        seq=list(self.cast_flow());seq[4]=replace(seq[4],evidence=self.ref(3,index=1))
        self.assertEqual(audit_reconstruction_coverage(seq,self.scope).reason_codes[0],'P34_SOURCE_REORDERED')

    def test_turn_overlap_rejected(self):
        seq=(self.cast_flow()[0],self.cast_flow()[3],self.f('TURN_START_OBSERVED',5,actor_id=222,turn_index=1))
        self.assertEqual(audit_reconstruction_coverage(seq,self.scope).reason_codes[0],'P34_TURN_OVERLAP_OR_REWIND')

    def test_wrong_turn_end_owner_rejected(self):
        seq=(self.cast_flow()[0],self.cast_flow()[3],self.f('TURN_END_OBSERVED',6,actor_id=222,turn_index=0))
        self.assertEqual(audit_reconstruction_coverage(seq,self.scope).reason_codes[0],'P34_TURN_END_OWNER_OR_EPOCH_MISMATCH')

    def test_wrong_turn_end_epoch_rejected(self):
        seq=(self.cast_flow()[0],self.cast_flow()[3],self.f('TURN_END_OBSERVED',6,actor_id=111,turn_index=1))
        self.assertEqual(audit_reconstruction_coverage(seq,self.scope).reason_codes[0],'P34_TURN_END_OWNER_OR_EPOCH_MISMATCH')

    def test_ending_while_turn_active_rejected(self):
        seq=(self.cast_flow()[0],self.cast_flow()[3],self.f('FIGHT_END_OBSERVED',6))
        self.assertEqual(audit_reconstruction_coverage(seq,self.scope).reason_codes[0],'P34_FIGHT_END_WITH_ACTIVE_TURN')

    def test_missing_fight_start_rejected(self):
        self.assertEqual(audit_reconstruction_coverage(self.cast_flow()[1:],self.scope).reason_codes[0],
                         'P34_FIGHT_START_REQUIRED')

    def test_second_fight_start_rejected(self):
        seq=(self.cast_flow()[0],self.f('FIGHT_START_OBSERVED',2))
        self.assertEqual(audit_reconstruction_coverage(seq,self.scope).reason_codes[0],'P34_DUPLICATE_FIGHT_START')

    def test_duplicate_resource_fact_rejected_by_p33(self):
        seq=(self.cast_flow()[0],self.r(2),self.r(2))
        self.assertEqual(audit_reconstruction_coverage(seq,self.scope).status,'BLOCKED_RESEARCH_ONLY')

    def test_multiple_resources_one_packet_supported(self):
        seq=(self.cast_flow()[0],self.r(2,'AP',11),self.r(2,'MP',5),self.f('FIGHT_END_OBSERVED',3))
        r=audit_reconstruction_coverage(seq,self.scope)
        self.assertEqual(r.status,'GAPS_FOUND_RESEARCH_ONLY')
        self.assertEqual(r.complete_actor_fields,2)

    def test_no_effect_assumptions_for_two_casts(self):
        seq=list(self.cast_flow());seq.insert(5,replace(seq[4],evidence=self.ref(5,index=1)))
        report=audit_reconstruction_coverage(tuple(seq),self.scope)
        self.assertEqual(report.spell_cast_observations,2)
        self.assertIn('CAST_AP_SETTLEMENT_UNVERIFIED',report.reason_codes)
        self.assertIn('CAST_LIMITS_AND_COOLDOWNS_UNVERIFIED',report.reason_codes)

    def test_read_only_report_does_not_export_identity_or_game_values(self):
        report=audit_reconstruction_coverage(self.cast_flow(),self.scope)
        text=str(report.to_dict())
        for secret in ('sensitive_session','sensitive_cra','Test_Wire','a'*64,'215','111','222'):
            self.assertNotIn(secret,text)

    def test_immutable_no_forged_authority_fields(self):
        report=audit_reconstruction_coverage(self.cast_flow(),self.scope)
        with self.assertRaises((ValueError,TypeError)):
            replace(report,actionable=True)
        with self.assertRaises((ValueError,TypeError)):
            replace(report,committed_events=1)
        with self.assertRaises((ValueError,TypeError)):
            replace(report,physical_input_sent=True)

    def test_reject_invalid_report_construction(self):
        r=audit_reconstruction_coverage(self.cast_flow(),self.scope)
        with self.assertRaises(ValueError):replace(r,status='READY_FOR_LIVE')
        with self.assertRaises(ValueError):replace(r,complete_actor_fields=9999)
        with self.assertRaises(ValueError):CoverageEntry('NOT_REAL',1,True,())

    def test_reject_untyped_drafts(self):
        seq=(self.cast_flow()[0],object())
        self.assertEqual(audit_reconstruction_coverage(seq,self.scope).reason_codes[0],'P34_RESEARCH_DRAFT_REQUIRED')

    def test_no_database_or_hardware_or_input(self):
        from anka_app import reconstruction_gaps_offline
        self.assertNotIn('anka_execution',inspect.getsource(reconstruction_gaps_offline))
        self.assertNotIn('sqlite3',inspect.getsource(reconstruction_gaps_offline))
        with patch('sqlite3.connect',side_effect=AssertionError('DB opened')):
            r=audit_reconstruction_coverage(self.cast_flow(),self.scope)
            self.assertEqual(r.committed_events,0)

    def test_automatic_setup_coverage_smoke(self):
        from anka_app.reconstruction_gaps_offline import reconstruction_coverage_smoke
        result=reconstruction_coverage_smoke()
        self.assertTrue(result['effect_gap_detected'])
        self.assertEqual(result['negative'],'P34_CAST_OUTSIDE_PROVEN_TURN')
        self.assertFalse(result['physical_input_sent'])

    def test_only_setup_start_operator_commands(self):
        self.assertEqual({p.name for p in Path(__file__).resolve().parents[1].glob('*.bat')},
                         {'setup.bat','start.bat'})

if __name__=='__main__':unittest.main()
