"""Independent P45↔P46 single-flow chronology safety regression tests."""
from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace
from anka_contracts.protocol import WireMessage
from anka_contracts.historical_lifecycle import LegacyFightScope
from anka_protocol.adapters.historical_lifecycle import HistoricalLifecycleDecoder, BUILD
from anka_protocol.adapters.historical_combat import HistoricalCombatDecoder
from anka_protocol.historical_combined_audit import audit_historical_combined


def var(v):
    data=bytearray()
    while v>=128: data.append((v&127)|128); v>>=7
    data.append(v)
    return bytes(data)

def f(n,v): return var(n<<3)+var(v)

def sub(n,p): return var((n<<3)|2)+var(len(p))+p


class P46CrossDecoderResearchTests(unittest.TestCase):
    def setUp(self):
        self.scope=LegacyFightScope(29,hashlib.sha256(b'one_socket').hexdigest(),4,BUILD)
        self.life=HistoricalLifecycleDecoder(requested_build=BUILD)
        self.combat=HistoricalCombatDecoder(requested_build=BUILD)

    def event(self, name, body, packet, idx=0):
        msg=WireMessage('server_to_client',name,body,packet,'one_socket',4,idx)
        decoder=self.life if name in ('jvj','jup','jvi','jxd') else self.combat
        result=decoder.decode(msg,scope=self.scope)
        self.assertEqual(result.status,'OBSERVATIONS_ONLY',result.failure_code)
        return result.observations[0]

    def owner(self,n,packet):return self.event('jvj',f(3,n),packet)
    def end(self,n,packet):return self.event('jup',f(2,n),packet)
    def cast(self,n,packet):
        return self.event('jsq',f(22,300)+f(36,n)+sub(2,sub(2,f(1,7)+f(2,88))+f(5,251)),packet)
    def terminal(self,packet):return self.event('jwp',b'',packet)

    def test_same_flow_owner_cast_end_terminal_keeps_all_outcome_unknown(self):
        report=audit_historical_combined((self.owner(33,1),self.cast(33,2),self.end(33,3),self.terminal(4)))
        self.assertEqual(report.status,'RESEARCH_CHRONOLOGY_NOT_CERTIFIED')
        self.assertEqual((report.casts_observed,report.result_boundaries),(1,1))
        self.assertFalse(report.physical_input_sent)
        self.assertEqual(report.canonical_commits,0)
        self.assertIn('FIGHT_VICTORY_AND_WORLD_REENTRY_UNVERIFIED',report.limitations)

    def test_unknown_turn_owner_must_not_be_invented(self):
        r=audit_historical_combined((self.cast(33,1),self.terminal(2)))
        self.assertEqual((r.status,r.first_issue),('INSUFFICIENT_EVIDENCE','P46_CAST_WITHOUT_OWNER_EVIDENCE'))

    def test_cast_by_different_actor_is_discrepancy_not_false_schema_rejection(self):
        r=audit_historical_combined((self.owner(33,1),self.cast(34,2),self.end(33,3)))
        self.assertEqual(r.status,'RESEARCH_DISCREPANCY_NOT_CERTIFIED')
        self.assertEqual(r.caster_owner_discrepancies,1)

    def test_cast_cannot_arrive_after_terminal_in_same_scope(self):
        r=audit_historical_combined((self.terminal(1),self.cast(33,2)))
        self.assertEqual(r.first_issue,'P46_COMBINED_EVENT_AFTER_RESULT')

    def test_duplicate_wire_provenance_across_two_decoders(self):
        r=audit_historical_combined((self.owner(33,1),self.cast(33,1)))
        self.assertEqual(r.first_issue,'P46_COMBINED_DUPLICATE_OR_REORDERED_SOURCE')

    def test_missing_end_cannot_certify_owner_switch(self):
        r=audit_historical_combined((self.owner(33,1),self.owner(34,2)))
        self.assertEqual(r.first_issue,'P46_COMBINED_OWNER_SWITCH_WITHOUT_END')

    def test_wrong_end_actor_detected(self):
        r=audit_historical_combined((self.owner(33,1),self.end(34,2)))
        self.assertEqual(r.first_issue,'P46_COMBINED_TURN_END_ACTOR_MISMATCH')

    def test_missing_owner_for_end_detected(self):
        r=audit_historical_combined((self.end(33,1),))
        self.assertEqual(r.first_issue,'P46_COMBINED_TURN_END_WITHOUT_OWNER')

    def test_cross_flow_mismatch_even_when_fight_id_equal(self):
        cast=self.cast(33,2)
        changed=replace(cast,evidence=replace(cast.evidence,flow_digest='f'*64))
        r=audit_historical_combined((self.owner(33,1),changed))
        self.assertEqual(r.first_issue,'P46_COMBINED_MIXED_SCOPE')

    def test_cross_fight_mismatch_even_when_flow_equal(self):
        item=replace(self.cast(33,2),fight_id=72)
        r=audit_historical_combined((self.owner(33,1),item))
        self.assertEqual(r.status,'SCOPE_CONFLICT')

    def test_same_owner_in_next_turn_when_completed_old_turn_valid(self):
        r=audit_historical_combined((self.owner(33,1),self.end(33,2),self.owner(33,3),self.cast(33,4)))
        self.assertEqual(r.status,'RESEARCH_CHRONOLOGY_NOT_CERTIFIED')

    def test_empty_audit_reports_evidence_gap(self):
        self.assertEqual(audit_historical_combined(()).first_issue,'P46_COMBINED_EMPTY')

if __name__=='__main__':unittest.main()
