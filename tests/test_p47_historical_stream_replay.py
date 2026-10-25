"""P47 independent wire-to-research integration and negative/provenance tests."""
from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace

from anka_contracts.historical_lifecycle import LegacyFightScope
from anka_contracts.protocol import WireMessage
from anka_protocol.adapters.historical_lifecycle import BUILD
from anka_protocol.historical_stream_replay import (
    MAX_WIRE_OBSERVATIONS, replay_historical_server_stream,
)


def var(n):
    out=bytearray()
    while n>=128:
        out.append((n&127)|128);n>>=7
    out.append(n)
    return bytes(out)


def f(k,n): return var(k<<3)+var(n)
def sub(k,blob):return var((k<<3)|2)+var(len(blob))+blob


def cast(n=33): return f(22,300)+f(36,n)+sub(2,sub(2,f(1,7)+f(2,88))+f(5,251))
def push(n=44):return f(22,5)+sub(5,f(1,n)+f(2,101)+f(3,109))
def teleport(n=44):return f(22,4)+sub(20,f(1,109)+f(2,n))


class P47WireReplayTests(unittest.TestCase):
    def setUp(self):
        self.flow='verified_fixture_server_socket'
        self.scope=LegacyFightScope(24,hashlib.sha256(self.flow.encode()).hexdigest(),3,BUILD)

    def msg(self,name='jvj',body=None,n=1,idx=0,**kwargs):
        if body is None:body=f(3,33)
        return WireMessage('server_to_client',name,body,n,self.flow,3,idx,**kwargs)

    def replay(self,*events,scope=None):
        return replay_historical_server_stream(tuple(events),scope=self.scope if scope is None else scope)

    def test_full_lifecycle_plus_combat_in_one_source_stream(self):
        r=self.replay(self.msg('jvi',f(1,1),1),self.msg('jvj',f(3,33),2),
          self.msg('jsq',cast(),3),self.msg('jsq',push(),4),
          self.msg('jsq',teleport(),5),self.msg('jup',f(2,33),6),
          self.msg('jwp',b'',7))
        self.assertEqual(r.status,'RESEARCH_REPLAY_ONLY')
        self.assertEqual((r.wire_messages_seen,r.decoded_messages,r.unsupported_actions,r.unmapped_wire_messages),(7,7,0,0))
        self.assertEqual((r.chronology_status,r.lifecycle_audit_status,r.combat_audit_status),(
            'RESEARCH_CHRONOLOGY_NOT_CERTIFIED','RESEARCH_SEQUENCE_COHERENT_NOT_CERTIFIED','RESEARCH_SEQUENCE_COHERENT_NOT_CERTIFIED'))
        self.assertEqual([x.kind for x in r.observations],['ROUND_OBSERVED','TURN_OWNER_OBSERVED','CAST_WIRE_OBSERVED',
            'DISPLACEMENT_OBSERVED','DISPLACEMENT_OBSERVED','TURN_END_OBSERVED','FIGHT_RESULT_BOUNDARY_OBSERVED'])
        self.assertFalse(r.source_completeness_verified)
        self.assertFalse(r.current_client_certified)
        self.assertFalse(r.actionable)
        self.assertEqual(r.canonical_commits,0)
        self.assertFalse(r.physical_input_sent)
        self.assertEqual(r.observations[-1].outcome,'UNKNOWN')

    def test_unknown_wire_between_owner_and_cast_must_not_disappear(self):
        r=self.replay(self.msg(n=1),self.msg('opaque',b'\x08\x01',2),self.msg('jsq',cast(),3))
        self.assertEqual((r.status,r.first_issue,r.unmapped_wire_messages),
                         ('PARTIAL_EVIDENCE','P47_UNMAPPED_WIRE_SEMANTICS',1))
        self.assertEqual(r.decoded_messages,2)
        self.assertEqual(r.unknown_wire_names,('opaque',))

    def test_unsupported_action_preserved_as_gap_instead_of_dropped(self):
        r=self.replay(self.msg(n=1),self.msg('jsq',f(22,888),2),self.msg('jsq',cast(),3))
        self.assertEqual((r.status,r.first_issue,r.unsupported_actions),
                         ('PARTIAL_EVIDENCE','P46_JSQ_ACTION_EFFECT_UNSUPPORTED',1))
        self.assertEqual(r.decoded_messages,2)

    def test_wrong_flow_between_valid_packets_blocks_and_does_not_decode_its_content(self):
        r=self.replay(self.msg(n=1),replace(self.msg('jsq',cast(),2),flow_key='foreign_socket'))
        self.assertEqual((r.status,r.first_issue,r.decoded_messages),
                         ('BLOCKED_EVIDENCE','P47_FLOW_OR_GENERATION_MISMATCH',1))

    def test_missing_or_incompatible_scope_is_blocked(self):
        for scope in (None,replace(self.scope,protocol_build='Dofus 3.7.11.11'), 'fake'):
            with self.subTest(scope=scope):
                result=replay_historical_server_stream((self.msg(),),scope=scope)
                self.assertEqual(result.first_issue,'P47_SCOPE_OR_BUILD_UNVERIFIED')
                self.assertFalse(result.actionable)

    def test_reversed_and_duplicate_wire_source_rejected_even_with_unmapped_middle(self):
        for seq in (
            (self.msg(n=3),self.msg('misc',b'',3)),
            (self.msg(n=3),self.msg('misc',b'',2)),
            (self.msg(n=3),self.msg(n=3)),
            (self.msg(n=3,idx=1),self.msg('jvi',f(1,1),3,idx=0)),
        ):
            with self.subTest(seq=seq):
                r=self.replay(*seq)
                self.assertEqual(r.first_issue,'P47_REPEATED_OR_REORDERED_WIRE_SOURCE')
                self.assertEqual(r.status,'BLOCKED_EVIDENCE')

    def test_two_different_messages_within_same_packet_valid(self):
        r=self.replay(self.msg('jvj',f(3,33),1,idx=0),self.msg('jsq',cast(),1,idx=1))
        self.assertEqual((r.status,r.decoded_messages),('RESEARCH_REPLAY_ONLY',2))

    def test_wrong_direction_recognized_and_unrecognized_always_block(self):
        for name in ('jvj','jsq','strange'):
            with self.subTest(name=name):
                r=self.replay(replace(self.msg(name,n=1),direction='client_to_server'))
                self.assertEqual(r.first_issue,'P47_SERVER_ONLY_DIRECTION_REQUIRED')

    def test_cross_generation_is_blocked(self):
        r=self.replay(self.msg(n=1),replace(self.msg('jup',f(2,33),n=2),generation=4))
        self.assertEqual((r.first_issue,r.status),('P47_FLOW_OR_GENERATION_MISMATCH','BLOCKED_EVIDENCE'))

    def test_caster_not_owner_is_not_falsely_called_illegal_cast(self):
        r=self.replay(self.msg(n=1),self.msg('jsq',cast(44),2))
        self.assertEqual(r.chronology_status,'RESEARCH_DISCREPANCY_NOT_CERTIFIED')
        self.assertEqual(r.first_issue,'P46_CASTER_NOT_OBSERVED_TURN_OWNER')
        self.assertEqual(r.status,'PARTIAL_EVIDENCE')

    def test_cast_without_owner_is_partial_not_success(self):
        r=self.replay(self.msg('jsq',cast(),1))
        self.assertEqual((r.status,r.first_issue),('PARTIAL_EVIDENCE','P46_CAST_WITHOUT_OWNER_EVIDENCE'))

    def test_cast_after_fight_result_rejected(self):
        r=self.replay(self.msg('jwp',b'',1),self.msg('jsq',cast(),2))
        self.assertEqual((r.status,r.first_issue),('BLOCKED_EVIDENCE','P46_COMBINED_EVENT_AFTER_RESULT'))

    def test_owner_switch_without_end_rejected(self):
        r=self.replay(self.msg(n=1),self.msg('jvj',f(3,44),2))
        self.assertEqual(r.status,'BLOCKED_EVIDENCE')
        self.assertEqual(r.first_issue,'P46_COMBINED_OWNER_SWITCH_WITHOUT_END')

    def test_turn_round_regression_caught_from_lifecycle_audit(self):
        r=self.replay(self.msg('jvi',f(1,5),1),self.msg('jvi',f(1,4),2))
        self.assertEqual((r.status,r.first_issue),('BLOCKED_EVIDENCE','P45_ROUND_REGRESSION'))

    def test_malformed_wire_fails_and_does_not_create_event(self):
        r=self.replay(self.msg(n=1),self.msg('jsq',b'\xff',2))
        self.assertEqual((r.status,r.first_issue,r.decoded_messages),
                         ('BLOCKED_EVIDENCE','P46_COMBAT_SCHEMA_OR_VALUE_DRIFT',1))

    def test_corrupt_lifecycle_wire_is_quarantined(self):
        r=self.replay(self.msg('jvj',b'\xff'))
        self.assertEqual((r.status,r.first_issue),('BLOCKED_EVIDENCE','P45_SCHEMA_OR_VALUE_DRIFT'))

    def test_no_input_and_empty_input_are_not_green(self):
        r=self.replay()
        self.assertEqual((r.status,r.first_issue),('PARTIAL_EVIDENCE','P47_NO_WIRE_EVIDENCE'))
        self.assertEqual(replay_historical_server_stream([],scope=self.scope).status,'BLOCKED_EVIDENCE')

    def test_non_wire_message_is_quarantined(self):
        r=self.replay(self.msg(n=1),'not-wire')
        self.assertEqual((r.status,r.first_issue,r.wire_messages_seen),
                         ('BLOCKED_EVIDENCE','P47_NOT_A_WIRE_MESSAGE',2))

    def test_many_unmapped_names_are_bounded_and_reported(self):
        r=self.replay(*(self.msg('unknown'+str(i),b'',i+1) for i in range(80)))
        self.assertEqual((r.status,r.unmapped_wire_messages),('PARTIAL_EVIDENCE',80))
        self.assertEqual(len(r.unknown_wire_names),24)
        self.assertEqual(r.decoded_messages,0)

    def test_input_limit_bounded_and_fails_without_decoding(self):
        r=self.replay(*([self.msg()]* (MAX_WIRE_OBSERVATIONS+1)))
        self.assertEqual((r.status,r.first_issue,r.wire_messages_seen),
                         ('BLOCKED_EVIDENCE','P47_STREAM_SIZE_OR_TYPE_INVALID',0))

    def test_transport_continuity_is_never_implied_by_incrementing_packet_ids(self):
        r=self.replay(self.msg(n=1),self.msg('jup',f(2,33),n=1000))
        self.assertEqual(r.status,'RESEARCH_REPLAY_ONLY')
        self.assertFalse(r.source_completeness_verified)

    def test_known_successful_decode_never_enters_canonical_authority(self):
        r=self.replay(self.msg(n=1))
        self.assertEqual((r.authority,r.canonical_commits,r.physical_input_sent,r.current_client_certified),
                         ('HISTORICAL_RESEARCH_ONLY',0,False,False))

    def test_earlier_soft_gap_does_not_hide_later_hard_boundary(self):
        r=self.replay(self.msg('strange',b'',1),replace(self.msg(n=2),flow_key='wrong'))
        self.assertEqual(r.first_issue,'P47_UNMAPPED_WIRE_SEMANTICS')
        self.assertEqual(r.blocking_issue,'P47_FLOW_OR_GENERATION_MISMATCH')
        self.assertEqual(r.status,'BLOCKED_EVIDENCE')

    def test_flow_key_wrong_type_or_invalid_unicode_is_quarantined(self):
        for key in (None, 0, '\ud800', 'x'*2000):
            with self.subTest(key=str(key)[:25]):
                msg=replace(self.msg(),flow_key=key)
                r=self.replay(msg)
                self.assertEqual((r.status,r.first_issue),('BLOCKED_EVIDENCE','P47_FLOW_KEY_INVALID'))

    def test_total_payload_limit_prevents_unbounded_full_flow_analysis(self):
        # All instances obey the individual 2MB WireMessage limit, yet exceed
        # the global replay budget. Do not treat a truncated trace as complete.
        bulk=b'\x00'*1_900_000
        stream=tuple(self.msg('unknown',bulk,n=i+1) for i in range(9))
        r=self.replay(*stream)
        self.assertEqual((r.status,r.first_issue),('BLOCKED_EVIDENCE','P47_UNMAPPED_WIRE_SEMANTICS'))
        self.assertEqual(r.unmapped_wire_messages,8)
        self.assertEqual(r.blocking_issue,'P47_STREAM_BODY_BUDGET_EXCEEDED')
        self.assertFalse(r.source_completeness_verified)

if __name__=='__main__':unittest.main()
