"""P45 independently authored historical shape oracles; synthetic bytes, NOT live proof."""
from __future__ import annotations
import hashlib
import unittest
from anka_contracts.protocol import WireMessage
from anka_contracts.historical_lifecycle import LegacyFightScope, LegacyFightObservation
from anka_protocol.adapters.historical_lifecycle import HistoricalLifecycleDecoder, BUILD
from anka_protocol.historical_timeline import audit_historical_timeline


def vi(number):
    out=bytearray()
    while number>127:
        out.append((number&127)|128);number>>=7
    out.append(number);return bytes(out)

def fld(field,value):
    return vi(field<<3)+vi(value)

def signed(v):
    return v if v>=0 else (1<<64)+v


class HistoricalLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.decoder=HistoricalLifecycleDecoder(requested_build=BUILD)
        self.scope=LegacyFightScope(101,hashlib.sha256(b'CRA_TCP_FLOW').hexdigest(),3,BUILD)

    def msg(self, name, body, *, packet=10, index=0, direction='server_to_client', flow='CRA_TCP_FLOW', generation=3):
        return WireMessage(direction,name,body,packet,flow,generation,index)

    def obs(self,name,body,**opts):
        result=self.decoder.decode(self.msg(name,body,**opts),scope=self.scope)
        self.assertEqual(result.status,'OBSERVATIONS_ONLY',result.failure_code)
        self.assertEqual(result.canonical_commits,0)
        self.assertFalse(result.physical_input_sent)
        return result.observations[0]

    def test_round_from_old_jvi_field1(self):
        o=self.obs('jvi',fld(1,4))
        self.assertEqual((o.kind,o.round_number,o.fight_id),('ROUND_OBSERVED',4,101))
        self.assertEqual(o.authority,'HISTORICAL_RESEARCH_ONLY')

    def test_turn_actor_signed_with_explicit_round_index(self):
        o=self.obs('jvj',fld(3,signed(-31))+fld(6,1)+fld(7,5))
        self.assertEqual((o.actor_id,o.round_number,o.wire_turn_index),(-31,5,1))

    def test_owner_without_round_or_index_must_remain_unknown(self):
        o=self.obs('jvj',fld(3,31))
        self.assertIsNone(o.round_number)
        self.assertIsNone(o.wire_turn_index)

    def test_end_field2(self):
        o=self.obs('jup',fld(2,signed(-31)))
        self.assertEqual((o.kind,o.actor_id),('TURN_END_OBSERVED',-31))

    def test_ready_explicit_false_and_true(self):
        for n,expected in ((0,False),(1,True)):
            with self.subTest(n=n):
                o=self.obs('jxd',fld(2,33)+fld(3,n))
                self.assertIs(o.ready,expected)

    def test_same_flow_round_owner_end_is_coherent_research_not_authority(self):
        items=(self.obs('jvi',fld(1,3),packet=1),
               self.obs('jvj',fld(3,33)+fld(7,3),packet=2),
               self.obs('jup',fld(2,33),packet=3),
               self.obs('jvj',fld(3,34)+fld(7,3),packet=4))
        result=audit_historical_timeline(items)
        self.assertEqual(result.status,'RESEARCH_SEQUENCE_COHERENT_NOT_CERTIFIED')
        self.assertEqual((result.pending_owner,result.last_observed_round),(34,3))
        self.assertFalse(result.live_ready)

    def test_no_owner_proof_for_bare_end(self):
        result=audit_historical_timeline((self.obs('jup',fld(2,33)),))
        self.assertEqual(result.first_issue,'P45_END_WITHOUT_PROVEN_OWNER')

    def test_end_wrong_actor_rejected(self):
        items=(self.obs('jvj',fld(3,33),packet=1),self.obs('jup',fld(2,34),packet=2))
        self.assertEqual(audit_historical_timeline(items).first_issue,'P45_END_ACTOR_MISMATCH')

    def test_owner_switch_without_end_rejected(self):
        items=(self.obs('jvj',fld(3,33),packet=1),self.obs('jvj',fld(3,34),packet=2))
        self.assertEqual(audit_historical_timeline(items).first_issue,'P45_OWNER_SWITCH_WITHOUT_END')

    def test_round_regression_rejected(self):
        items=(self.obs('jvi',fld(1,3),packet=1),self.obs('jvi',fld(1,2),packet=2))
        self.assertEqual(audit_historical_timeline(items).first_issue,'P45_ROUND_REGRESSION')

    def test_duplicate_source_rejected(self):
        a=self.obs('jvi',fld(1,2));b=self.obs('jvi',fld(1,2))
        self.assertEqual(audit_historical_timeline((a,b)).first_issue,'P45_DUPLICATE_OR_REORDERED_SOURCE')

    def test_cross_flow_cannot_be_globally_ordered(self):
        a=self.obs('jvi',fld(1,2),packet=1)
        b=self.decoder.decode(self.msg('jvi',fld(1,2),flow='ENU_TCP_FLOW',packet=2),
            scope=LegacyFightScope(101,hashlib.sha256(b'ENU_TCP_FLOW').hexdigest(),3,BUILD)).observations[0]
        self.assertEqual(audit_historical_timeline((a,b)).first_issue,'P45_MIXED_FLOW_FIGHT_OR_BUILD')

    def test_wrong_fight_rejected(self):
        a=self.obs('jvi',fld(1,2),packet=1)
        b=LegacyFightObservation('ROUND_OBSERVED',self.obs('jvi',fld(1,3),packet=2).evidence,202,round_number=3)
        self.assertEqual(audit_historical_timeline((a,b)).status,'SCOPE_CONFLICT')

    def test_wrong_build_uses_block(self):
        result=HistoricalLifecycleDecoder(requested_build='Dofus 3.7.11.11').decode(self.msg('jvi',fld(1,2)),scope=self.scope)
        self.assertEqual(result.status,'BUILD_MISMATCH')

    def test_wrong_scope_generation_and_flow(self):
        for altered in (self.msg('jvi',fld(1,2),generation=4),self.msg('jvi',fld(1,2),flow='FOLLOWER')):
            with self.subTest(case=altered):
                self.assertEqual(self.decoder.decode(altered,scope=self.scope).status,'SCOPE_UNVERIFIED')

    def test_empty_flow_key_not_a_valid_capture_proof(self):
        empty=LegacyFightScope(101,hashlib.sha256(b'').hexdigest(),3,BUILD)
        result=self.decoder.decode(self.msg('jvi',fld(1,3),flow=''),scope=empty)
        self.assertEqual(result.status,'SCOPE_UNVERIFIED')

    def test_missing_scope_blocked(self):
        self.assertEqual(self.decoder.decode(self.msg('jvi',fld(1,2)),scope=None).status,'SCOPE_UNVERIFIED')

    def test_client_direction_rejected(self):
        r=self.decoder.decode(self.msg('jup',fld(2,33),direction='client_to_server'),scope=self.scope)
        self.assertEqual((r.status,r.failure_code),('QUARANTINED','P45_UNTRUSTED_DIRECTION'))

    def test_unknown_wire_no_mapping(self):
        self.assertEqual(self.decoder.decode(self.msg('unk',b''),scope=self.scope).status,'NO_MAPPING')

    def test_duplicate_field_quarantined(self):
        self.assertEqual(self.decoder.decode(self.msg('jup',fld(2,33)+fld(2,34)),scope=self.scope).status,'QUARANTINED')

    def test_missing_field_quarantined(self):
        for name in ('jvi','jvj','jup','jxd'):
            with self.subTest(name=name):
                self.assertEqual(self.decoder.decode(self.msg(name,b''),scope=self.scope).status,'QUARANTINED')

    def test_out_of_range_round_or_zero_actor_quarantined(self):
        for name,payload in [('jvi',fld(1,0)),('jvi',fld(1,1_000_001)),('jvj',fld(3,0)),('jup',fld(2,0))]:
            with self.subTest(name=name,raw=payload):
                self.assertEqual(self.decoder.decode(self.msg(name,payload),scope=self.scope).status,'QUARANTINED')

    def test_non_boolean_ready_quarantined(self):
        self.assertEqual(self.decoder.decode(self.msg('jxd',fld(2,33)+fld(3,2)),scope=self.scope).status,'QUARANTINED')

    def test_truncated_proto_quarantined(self):
        self.assertEqual(self.decoder.decode(self.msg('jvi',b'\x08\x80'),scope=self.scope).status,'QUARANTINED')

    def test_repeated_unrelated_fields_cannot_disguise_missing_required(self):
        self.assertEqual(self.decoder.decode(self.msg('jup',fld(1,4)+fld(1,5)),scope=self.scope).status,'QUARANTINED')

    def test_duplicate_turn_index_quarantined(self):
        self.assertEqual(self.decoder.decode(self.msg('jvj',fld(3,33)+fld(6,1)+fld(6,2)),scope=self.scope).status,'QUARANTINED')

if __name__=='__main__':unittest.main()
