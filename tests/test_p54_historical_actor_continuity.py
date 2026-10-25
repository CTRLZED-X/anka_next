"""P54 cross-family historical character -> fight actor continuity falsification."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import unittest

from anka_contracts.canonical import EvidenceRef
from anka_contracts.historical_identity import HistoricalIdentityObservation
from anka_contracts.historical_lifecycle import LegacyFightObservation
from anka_contracts.historical_combat import HistoricalCombatObservation
from anka_protocol.adapters.historical_identity import BUILD, ADAPTER_ID as ID_ADAPTER
from anka_protocol.historical_actor_continuity import audit_historical_actor_continuity

FLOW=sha256(b'p54-flow').hexdigest()

def ev(adapter,wire,packet,index=0,flow=FLOW,generation=3,build=BUILD):
    return EvidenceRef(build,adapter,wire,packet,generation,flow,message_index=index)

def identity(actor=41,packet=1,flow=FLOW,generation=3,build=BUILD):
    return HistoricalIdentityObservation(ev(ID_ADAPTER,'jnj',packet,flow=flow,generation=generation,build=build),
                                         'Curseni',actor,301,777)

def life(kind,packet,actor=None,**kw):
    return LegacyFightObservation(kind,ev('dofus_3_7_10_10_p45_fight_lifecycle','jvj' if kind=='TURN_OWNER_OBSERVED' else 'jup',packet),401,actor_id=actor,**kw)

def cast(packet,actor=41,index=0):
    return HistoricalCombatObservation('CAST_WIRE_OBSERVED',ev('dofus_3_7_10_10_p46_combat_history','jsq',packet,index),401,
        wire_action_type=300,actor_id=actor,spell_id=123,spell_level_record_id=456,target_cell_id=250)

def move(packet,actor=41):
    return HistoricalCombatObservation('DISPLACEMENT_OBSERVED',ev('dofus_3_7_10_10_p46_combat_history','jsq',packet),401,
        wire_action_type=5,actor_id=actor,from_cell_id=250,to_cell_id=251,displacement_kind='PUSH')

def result(packet):
    return HistoricalCombatObservation('FIGHT_RESULT_BOUNDARY_OBSERVED',ev('dofus_3_7_10_10_p46_combat_history','jwp',packet),401)

class P54ActorContinuityTests(unittest.TestCase):
    def test_local_owner_cast_end_forms_research_continuity(self):
        seq=(life('TURN_OWNER_OBSERVED',2,41),cast(3,41),life('TURN_END_OBSERVED',4,41),result(5))
        r=audit_historical_actor_continuity(identity(),seq)
        self.assertEqual(r.status,'RESEARCH_ACTOR_CONTINUITY_ONLY')
        self.assertEqual((r.local_actor_references,r.local_turn_owner_records,r.local_cast_records,r.local_turn_end_records),(3,1,1,1))
        self.assertEqual(r.result_boundaries,1)
        self.assertFalse(r.current_client_certified or r.account_binding_verified or r.actionable or r.physical_input_sent)
        self.assertEqual(r.canonical_commits,0)

    def test_foreign_actor_records_are_normal_not_conflict(self):
        seq=(life('TURN_OWNER_OBSERVED',2,99),cast(3,99),life('TURN_END_OBSERVED',4,99),
             life('TURN_OWNER_OBSERVED',5,41),cast(6,41))
        r=audit_historical_actor_continuity(identity(),seq)
        self.assertEqual(r.status,'RESEARCH_ACTOR_CONTINUITY_ONLY')
        self.assertEqual((r.foreign_actor_references,r.local_actor_references),(3,2))

    def test_local_displacement_is_continuity_not_cast_causation(self):
        r=audit_historical_actor_continuity(identity(),(move(2,41),))
        self.assertEqual((r.status,r.local_displacement_records),('RESEARCH_ACTOR_CONTINUITY_ONLY',1))
        self.assertIn('CAST_RECORD_IS_NOT_SERVER_SUCCESS_OR_EFFECT_CAUSATION',r.limitations)

    def test_ready_record_alone_is_valid_but_historical_only(self):
        ready=LegacyFightObservation('FIGHT_READY_OBSERVED',ev('life','jxd',2),401,actor_id=41,ready=True)
        r=audit_historical_actor_continuity(identity(),(ready,))
        self.assertEqual((r.status,r.local_ready_records),('RESEARCH_ACTOR_CONTINUITY_ONLY',1))

    def test_no_local_actor_is_partial(self):
        r=audit_historical_actor_continuity(identity(),(life('TURN_OWNER_OBSERVED',2,99),cast(3,99)))
        self.assertEqual((r.status,r.first_issue),('PARTIAL_EVIDENCE','P54_LOCAL_ACTOR_NOT_SEEN_IN_FIGHT'))

    def test_weak_local_end_only_is_partial(self):
        r=audit_historical_actor_continuity(identity(),(life('TURN_END_OBSERVED',2,41),))
        self.assertEqual((r.status,r.first_issue),('PARTIAL_EVIDENCE','P54_LOCAL_ACTOR_REFERENCE_TOO_WEAK'))

    def test_mixed_flow_blocks(self):
        bad=replace(cast(2),evidence=replace(cast(2).evidence,flow_digest='1'*64))
        r=audit_historical_actor_continuity(identity(),(bad,))
        self.assertEqual((r.status,r.first_issue),('BLOCKED_EVIDENCE','P54_BUILD_FLOW_OR_GENERATION_CONFLICT'))

    def test_mixed_generation_blocks(self):
        bad=replace(cast(2),evidence=replace(cast(2).evidence,transport_generation=4))
        self.assertEqual(audit_historical_actor_continuity(identity(),(bad,)).first_issue,'P54_BUILD_FLOW_OR_GENERATION_CONFLICT')

    def test_mixed_build_blocks(self):
        bad=replace(cast(2),evidence=replace(cast(2).evidence,protocol_build='Dofus 9.9'))
        self.assertEqual(audit_historical_actor_continuity(identity(),(bad,)).first_issue,'P54_BUILD_FLOW_OR_GENERATION_CONFLICT')

    def test_mixed_fight_blocks(self):
        bad=replace(cast(3),fight_id=402)
        r=audit_historical_actor_continuity(identity(),(life('TURN_OWNER_OBSERVED',2,41),bad))
        self.assertEqual((r.status,r.first_issue),('BLOCKED_EVIDENCE','P54_MIXED_FIGHT_IDENTITIES'))

    def test_fight_must_follow_identity_source(self):
        r=audit_historical_actor_continuity(identity(packet=5),(cast(4),))
        self.assertEqual(r.first_issue,'P54_IDENTITY_TO_FIGHT_SOURCE_NOT_STRICTLY_ORDERED')

    def test_same_packet_higher_message_index_is_allowed(self):
        ident=HistoricalIdentityObservation(ev(ID_ADAPTER,'jnj',5,0),'Curseni',41,301,777)
        r=audit_historical_actor_continuity(ident,(cast(5,41,index=1),))
        self.assertEqual(r.status,'RESEARCH_ACTOR_CONTINUITY_ONLY')

    def test_reordered_fight_sources_block(self):
        r=audit_historical_actor_continuity(identity(),(cast(3),life('TURN_END_OBSERVED',2,41)))
        self.assertEqual(r.first_issue,'P54_IDENTITY_TO_FIGHT_SOURCE_NOT_STRICTLY_ORDERED')

    def test_empty_sequence_is_partial_not_success(self):
        r=audit_historical_actor_continuity(identity(),())
        self.assertEqual((r.status,r.first_issue),('PARTIAL_EVIDENCE','P54_FIGHT_OBSERVATIONS_MISSING'))

    def test_wrong_input_types_fail_closed(self):
        self.assertEqual(audit_historical_actor_continuity('fake',()).status,'BLOCKED_EVIDENCE')
        self.assertEqual(audit_historical_actor_continuity(identity(),('fake',)).status,'BLOCKED_EVIDENCE')
        self.assertEqual(audit_historical_actor_continuity(identity(),[cast(2)]).status,'BLOCKED_EVIDENCE')

    def test_historical_identity_wrong_build_is_blocked(self):
        fake=replace(identity(),evidence=replace(identity().evidence,protocol_build='Dofus 9.9'))
        r=audit_historical_actor_continuity(fake,(cast(2),))
        self.assertEqual(r.first_issue,'P54_IDENTITY_WITNESS_NOT_HISTORICAL_RESEARCH')

    def test_result_boundary_does_not_count_as_actor_reference(self):
        r=audit_historical_actor_continuity(identity(),(result(2),))
        self.assertEqual((r.status,r.local_actor_references,r.result_boundaries),('PARTIAL_EVIDENCE',0,1))

    def test_contract_is_immutable_and_never_actionable(self):
        r=audit_historical_actor_continuity(identity(),(cast(2),))
        with self.assertRaises((AttributeError,TypeError)):
            r.actionable=True
        self.assertFalse(r.actionable)
        self.assertFalse(r.current_client_certified)
        self.assertFalse(r.account_binding_verified)

if __name__=='__main__':unittest.main()

class P54FullHistoricalChainTests(unittest.TestCase):
    def _host(self):
        from anka_contracts.client import WindowObservation, WindowScan
        from anka_capture.windows_flows import TcpEndpoint
        T=10**10
        K1=('192.0.2.1',45670,'198.51.100.7',40400)
        K2=('192.0.2.1',45671,'198.51.100.7',40400)
        wins=(WindowObservation(1101,101,9101,'Dofus.exe','Dofus',1280,649,96,False),
              WindowObservation(1102,102,9102,'Dofus.exe','Dofus',1280,649,96,False))
        before=WindowScan(T,wins);after=WindowScan(T+1000,wins)
        tcp=(TcpEndpoint(*K1,101,5),TcpEndpoint(*K2,102,5))
        return before,after,tcp,tcp,{'flow-a':K1,'flow-b':K2}

    def _ident(self,token,name,actor):
        digest=sha256(token.encode()).hexdigest()
        e=EvidenceRef(BUILD,ID_ADAPTER,'jnj',1,3,digest,message_index=0)
        return HistoricalIdentityObservation(e,name,actor,300+actor,777)

    def _cast_for(self,token,actor,packet=2):
        digest=sha256(token.encode()).hexdigest()
        e=EvidenceRef(BUILD,'dofus_3_7_10_10_p46_combat_history','jsq',packet,3,digest,message_index=0)
        return HistoricalCombatObservation('CAST_WIRE_OBSERVED',e,401,wire_action_type=300,
            actor_id=actor,spell_id=123,spell_level_record_id=456,target_cell_id=250)

    def test_two_processes_two_characters_two_actor_continuities(self):
        from anka_app.ingress_readiness import historical_process_character_actor_topology
        host=self._host();ids={'flow-a':self._ident('flow-a','Curseni',41),'flow-b':self._ident('flow-b','Sosoking',42)}
        fights={'flow-a':(self._cast_for('flow-a',41),),'flow-b':(self._cast_for('flow-b',42),)}
        r=historical_process_character_actor_topology(*host,ids,fights,expected_character_names=('Curseni','Sosoking'))
        self.assertEqual((r['status'],r['actor_continuity_verified']),('HISTORICAL_ACTOR_CANDIDATES_ONLY',2))
        self.assertEqual(r['historical_process_character_candidates'],2)
        self.assertFalse(r['cross_flow_ordering_verified'])
        self.assertFalse(r['account_binding_verified'] or r['current_build_certified'] or r['actionable'])

    def test_swapped_actor_on_one_flow_is_partial_not_verified(self):
        from anka_app.ingress_readiness import historical_process_character_actor_topology
        host=self._host();ids={'flow-a':self._ident('flow-a','Curseni',41),'flow-b':self._ident('flow-b','Sosoking',42)}
        fights={'flow-a':(self._cast_for('flow-a',99),),'flow-b':(self._cast_for('flow-b',42),)}
        r=historical_process_character_actor_topology(*host,ids,fights,expected_character_names=('Curseni','Sosoking'))
        self.assertEqual((r['status'],r['actor_continuity_verified'],r['actor_continuity_partial']),('PARTIAL_CANDIDATES',1,1))

    def test_cross_flow_fight_evidence_blocks_that_account(self):
        from anka_app.ingress_readiness import historical_process_character_actor_topology
        host=self._host();ids={'flow-a':self._ident('flow-a','Curseni',41),'flow-b':self._ident('flow-b','Sosoking',42)}
        fights={'flow-a':(self._cast_for('flow-b',41),),'flow-b':(self._cast_for('flow-b',42),)}
        r=historical_process_character_actor_topology(*host,ids,fights,expected_character_names=('Curseni','Sosoking'))
        self.assertEqual((r['status'],r['actor_continuity_blocked']),('BLOCKED_AMBIGUOUS',1))

    def test_missing_second_fight_trace_is_partial(self):
        from anka_app.ingress_readiness import historical_process_character_actor_topology
        host=self._host();ids={'flow-a':self._ident('flow-a','Curseni',41),'flow-b':self._ident('flow-b','Sosoking',42)}
        r=historical_process_character_actor_topology(*host,ids,{'flow-a':(self._cast_for('flow-a',41),)},expected_character_names=('Curseni','Sosoking'))
        self.assertEqual((r['status'],r['missing_fight_witnesses']),('PARTIAL_CANDIDATES',1))

    def test_dirty_p53_topology_blocks_before_actor_promotion(self):
        from anka_app.ingress_readiness import historical_process_character_actor_topology
        before,after,bt,at,keys=self._host();ids={'flow-a':self._ident('flow-a','Curseni',41),'flow-b':self._ident('flow-b','Sosoking',42)}
        # two names claimed by the same process through the host owner evidence
        from anka_capture.windows_flows import TcpEndpoint
        dirty=(replace(bt[0],pid=101),replace(bt[1],pid=101))
        r=historical_process_character_actor_topology(before,after,dirty,dirty,keys,ids,{},expected_character_names=('Curseni','Sosoking'))
        self.assertEqual((r['status'],r['reason']),('BLOCKED_AMBIGUOUS','P54_P53_TOPOLOGY_NOT_CLEAN'))

    def test_report_does_not_export_private_identity_or_network_data(self):
        import json
        from anka_app.ingress_readiness import historical_process_character_actor_topology
        host=self._host();ids={'flow-a':self._ident('flow-a','Curseni',41),'flow-b':self._ident('flow-b','Sosoking',42)}
        fights={'flow-a':(self._cast_for('flow-a',41),),'flow-b':(self._cast_for('flow-b',42),)}
        text=json.dumps(historical_process_character_actor_topology(*host,ids,fights,expected_character_names=('Curseni','Sosoking')))
        for secret in ('Curseni','Sosoking','flow-a','flow-b','192.0.2.1','198.51.100.7','45670','45671','1101','1102'):
            with self.subTest(secret=secret):self.assertNotIn(secret,text)
