"""P33 independent research-to-state shadow replay boundary (no game input)."""
import unittest
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from anka_contracts.canonical import EvidenceRef,CanonicalDraft
from anka_contracts.fight_semantic import FightResearchDraft
from anka_contracts.shadow_replay import ShadowScope,ShadowReplayReport
from anka_canonical.shadow_bridge import build_shadow_specs
from anka_app.shadow_replay_offline import run_shadow_replay


class ShadowProjectionTests(unittest.TestCase):
    def setUp(self):
        self.scope=ShadowScope('fixture_session','fixture_cra',1,42,(111,222),
                               'Dofus 3.7.10.10','historical_adapter','a'*64,1)

    def ref(self,n,ordinal=0,**kwargs):
        return EvidenceRef(protocol_build=self.scope.protocol_build,adapter_id=self.scope.adapter_id,
                           wire_name='Test_Wire',packet_number=n,transport_generation=self.scope.transport_generation,
                           flow_digest=self.scope.flow_digest,message_index=ordinal,**kwargs)

    def fight(self,kind,n,**kwargs):
        return FightResearchDraft(kind,self.ref(n),self.scope.fight_id,**kwargs)

    def resource(self,n,resource='AP',value=11,actor=111,ordinal=0):
        return CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',actor,self.ref(n,ordinal),resource=resource,value=value)

    def full(self):
        return (self.fight('FIGHT_START_OBSERVED',1),
                self.fight('ACTOR_CELL_OBSERVED',2,actor_id=111,cell_id=215),
                self.resource(3),
                self.fight('TURN_START_OBSERVED',4,actor_id=111,turn_index=0),
                self.fight('TURN_END_OBSERVED',5,actor_id=111,turn_index=0),
                self.fight('TURN_START_OBSERVED',6,actor_id=222,turn_index=1),
                self.fight('TURN_END_OBSERVED',7,actor_id=222,turn_index=1),
                self.fight('FIGHT_END_OBSERVED',8))

    def test_shadow_complete_replay_research_only(self):
        r=run_shadow_replay(self.full(),self.scope)
        self.assertEqual(r.status,'SHADOW_CONSISTENT_RESEARCH_ONLY')
        self.assertEqual(r.final_phase,'ENDED')
        self.assertEqual(r.fixture_events,2)
        self.assertEqual(r.projected_events,10)
        self.assertEqual(r.committed_events,0)
        self.assertFalse(r.actionable)
        self.assertFalse(r.live_state_mutated)
        self.assertFalse(r.physical_input_sent)
        self.assertFalse(r.to_dict()['current_build_certified'])

    def test_partial_turn_replay_is_incomplete(self):
        r=run_shadow_replay(self.full()[:4],self.scope)
        self.assertEqual(r.status,'SHADOW_INCOMPLETE_RESEARCH')
        self.assertEqual(r.final_phase,'IN_FIGHT')
        self.assertIn('P33_FIGHT_END_NOT_OBSERVED',r.reason_codes)

    def test_scalar_hp_mp_cooldown_are_reducer_compatible(self):
        begin=self.full()[0]
        hp=CanonicalDraft('ACTOR_HP_ABSOLUTE',111,self.ref(3),value=1800,maximum=2000)
        cd=CanonicalDraft('ACTOR_COOLDOWN_SNAPSHOT',111,self.ref(4),cooldowns=((12,2),))
        events=(begin,self.resource(2),hp,cd,self.fight('FIGHT_END_OBSERVED',5))
        r=run_shadow_replay(events,self.scope)
        self.assertEqual(r.status,'SHADOW_CONSISTENT_RESEARCH_ONLY')
        self.assertEqual(r.projected_events,7)

    def test_multiple_fields_same_wire_occurrence_are_not_lost(self):
        events=(self.full()[0], self.resource(2,'AP',11,ordinal=0),
                self.resource(2,'MP',5,ordinal=0),self.fight('FIGHT_END_OBSERVED',3))
        r=run_shadow_replay(events,self.scope)
        self.assertEqual(r.status,'SHADOW_CONSISTENT_RESEARCH_ONLY')

    def test_duplicate_same_field_at_same_message_rejected(self):
        events=(self.full()[0],self.resource(2),self.resource(2, value=9),self.fight('FIGHT_END_OBSERVED',3))
        self.assertEqual(run_shadow_replay(events,self.scope).reason_codes[0],
                         'P33_DUPLICATE_OR_CONFLICTING_SOURCE_CLAIM')

    def test_duplicate_identical_field_rejected(self):
        events=(self.full()[0],self.resource(2),self.resource(2))
        self.assertEqual(run_shadow_replay(events,self.scope).status,'SHADOW_BLOCKED')

    def test_out_of_order_packet_rejected(self):
        events=(self.full()[0],self.resource(4),self.resource(3,'MP',5))
        self.assertEqual(run_shadow_replay(events,self.scope).reason_codes[0],'P33_SOURCE_REORDERED')

    def test_later_message_ordinal_in_same_packet_allowed(self):
        events=(self.full()[0],self.resource(2,ordinal=0),self.resource(2,'MP',5,ordinal=1),self.fight('FIGHT_END_OBSERVED',3))
        self.assertEqual(run_shadow_replay(events,self.scope).status,'SHADOW_CONSISTENT_RESEARCH_ONLY')

    def test_wrong_build_blocks(self):
        e=replace(self.full()[1],evidence=replace(self.ref(2),protocol_build='Dofus 9.9'))
        self.assertEqual(run_shadow_replay((self.full()[0],e),self.scope).reason_codes[0],'P33_SOURCE_SCOPE_CHANGED')

    def test_wrong_adapter_blocks(self):
        e=replace(self.full()[1],evidence=replace(self.ref(2),adapter_id='someone_else'))
        self.assertEqual(run_shadow_replay((self.full()[0],e),self.scope).reason_codes[0],'P33_SOURCE_SCOPE_CHANGED')

    def test_wrong_flow_digest_blocks(self):
        e=replace(self.full()[1],evidence=replace(self.ref(2),flow_digest='b'*64))
        self.assertEqual(run_shadow_replay((self.full()[0],e),self.scope).reason_codes[0],'P33_SOURCE_SCOPE_CHANGED')

    def test_wrong_transport_generation_blocks(self):
        e=replace(self.full()[1],evidence=replace(self.ref(2),transport_generation=9))
        self.assertEqual(run_shadow_replay((self.full()[0],e),self.scope).reason_codes[0],'P33_SOURCE_SCOPE_CHANGED')

    def test_wrong_fight_blocks(self):
        e=replace(self.full()[1],fight_id=43)
        self.assertEqual(run_shadow_replay((self.full()[0],e),self.scope).reason_codes[0],'P33_FIGHT_ID_MISMATCH')

    def test_missing_fight_start_blocks(self):
        self.assertEqual(run_shadow_replay(self.full()[1:],self.scope).reason_codes[0],'P33_FIGHT_START_REQUIRED')

    def test_wrong_first_fight_id_blocks(self):
        e=replace(self.full()[0],fight_id=43)
        self.assertEqual(run_shadow_replay((e,),self.scope).reason_codes[0],'P33_FIGHT_ID_MISMATCH')

    def test_roster_not_inferred_from_observations(self):
        e=self.fight('ACTOR_CELL_OBSERVED',2,actor_id=333,cell_id=4)
        self.assertEqual(run_shadow_replay((self.full()[0],e),self.scope).reason_codes[0],
                         'P33_ACTOR_NOT_IN_SYNTHETIC_ROSTER')

    def test_overlapping_turns_rejected(self):
        seq=self.full()
        self.assertEqual(run_shadow_replay((seq[0],seq[3],seq[5]),self.scope).reason_codes[0],
                         'P33_TURN_OVERLAP_OR_REWIND')

    def test_rewinding_turn_epoch_rejected(self):
        seq=self.full()
        bad=self.fight('TURN_START_OBSERVED',8,actor_id=111,turn_index=0)
        self.assertEqual(run_shadow_replay((seq[0],seq[3],seq[4],bad),self.scope).reason_codes[0],
                         'P33_TURN_OVERLAP_OR_REWIND')

    def test_end_turn_owner_mismatch_rejected(self):
        seq=self.full()
        self.assertEqual(run_shadow_replay((seq[0],seq[3],self.fight('TURN_END_OBSERVED',5,actor_id=222,turn_index=0)),self.scope).reason_codes[0],
                         'P33_TURN_END_EPOCH_OR_OWNER_MISMATCH')

    def test_end_fight_while_turn_open_rejected(self):
        seq=self.full()
        self.assertEqual(run_shadow_replay((seq[0],seq[3],self.fight('FIGHT_END_OBSERVED',5)),self.scope).reason_codes[0],
                         'P33_FIGHT_ENDED_WITH_ACTIVE_TURN')

    def test_event_after_fight_end_rejected(self):
        seq=(self.full()[0],self.fight('FIGHT_END_OBSERVED',2),self.resource(3))
        self.assertEqual(run_shadow_replay(seq,self.scope).reason_codes[0],'P33_EVENT_AFTER_FIGHT_END')

    def test_spell_cast_not_silently_ignored(self):
        seq=self.full()
        cast=self.fight('SPELL_CAST_OBSERVED',5,actor_id=111,spell_id=20,target_cell=215)
        self.assertEqual(run_shadow_replay((seq[0],seq[3],cast),self.scope).reason_codes[0],
                         'P33_SPELL_CAST_REDUCER_UNSUPPORTED')

    def test_cross_account_scope_requires_distinct_fixture(self):
        report=run_shadow_replay(self.full(),replace(self.scope,account_id='fixture_enu'))
        # Identity comes from explicit *synthetic* fixture, not packet evidence.
        self.assertEqual(report.status,'SHADOW_CONSISTENT_RESEARCH_ONLY')
        self.assertTrue(report.to_dict()['roster_is_synthetic_fixture'])

    def test_empty_or_excessive_inputs_fail(self):
        self.assertEqual(run_shadow_replay((),self.scope).status,'SHADOW_BLOCKED')
        self.assertEqual(run_shadow_replay(self.full()*513,self.scope).reason_codes[0],
                         'P33_OBSERVATIONS_EMPTY_OR_EXCESSIVE')

    def test_untyped_input_fails_closed(self):
        self.assertEqual(run_shadow_replay((self.full()[0],object()),self.scope).reason_codes[0],
                         'P33_RESEARCH_DRAFT_REQUIRED')

    def test_research_reports_cannot_claim_live_authority(self):
        r=run_shadow_replay(self.full(),self.scope)
        from dataclasses import replace
        with self.assertRaises((ValueError,TypeError)):
            replace(r,actionable=True)
        with self.assertRaises((ValueError,TypeError)):
            replace(r,committed_events=1)

    def test_no_sqlite_or_input_dependency_or_side_effect(self):
        import inspect
        from anka_canonical import shadow_bridge
        from anka_app import shadow_replay_offline
        self.assertNotIn('sqlite3',inspect.getsource(shadow_bridge))
        self.assertNotIn('anka_execution',inspect.getsource(shadow_replay_offline))
        with patch('sqlite3.connect',side_effect=AssertionError('database opened')):
            self.assertEqual(run_shadow_replay(self.full(),self.scope).status,'SHADOW_CONSISTENT_RESEARCH_ONLY')

    def test_no_sensitive_values_in_report(self):
        r=run_shadow_replay((self.full()[0],self.resource(2,value=117),self.fight('FIGHT_END_OBSERVED',3)),self.scope)
        text=str(r.to_dict())
        for value in ('fixture_cra','fixture_session','117','Test_Wire','a'*64):
            self.assertNotIn(value,text)

    def test_scope_validation(self):
        with self.assertRaisesRegex(ValueError,'P33_SHADOW_ROSTER_INVALID'):
            replace(self.scope,roster_fixture=(111,111))
        with self.assertRaisesRegex(ValueError,'P33_SHADOW_FLOW_INVALID'):
            replace(self.scope,flow_digest='bad')

    def test_no_third_bat_launcher(self):
        root=Path(__file__).resolve().parents[1]
        self.assertEqual({p.name for p in root.glob('*.bat')},{'setup.bat','start.bat'})

if __name__=='__main__':unittest.main()
