"""Independent payload/framing fixtures for the actual CapturePoll -> P6 -> P47 boundary."""
from __future__ import annotations
import hashlib
from dataclasses import replace
from pathlib import Path
import unittest

from anka_contracts.capture import CapturedTcpSegment, CapturePoll
from anka_contracts.historical_lifecycle import LegacyFightScope
from anka_protocol.adapters.historical_lifecycle import BUILD
from anka_app.historical_transport_bridge import replay_historical_capture_polls

ROOT=Path(__file__).resolve().parents[1]

def var(n):
    out=[]
    while n>=128:
        out.append((n&127)|128); n>>=7
    out.append(n)
    return bytes(out)

def field(n,blob):return var((n<<3)|2)+var(len(blob))+blob

def scalar(n,value):return var(n<<3)+var(value)

def frame(name,body):
    payload=field(1,b'type.ankama.com/'+name.encode())+field(2,body)
    return var(len(payload))+payload

class P48CaptureToResearch(unittest.TestCase):
    def setUp(self):
        self.flow='isolated_p48_capture_flow'
        self.scope=LegacyFightScope(42,hashlib.sha256(self.flow.encode()).hexdigest(),1,BUILD)
        self.body=frame('jvj',scalar(3,33))+frame('jup',scalar(2,33))+frame('jwp',b'')

    def seg(self,n,seq,payload=b'',flow=None,flags=0,direction='server_to_client'):
        return CapturedTcpSegment(flow or self.flow,direction,seq,payload,n,flags)

    def polls(self,*segments,source='source_gen1',dropped=0,overflowed=False,visibility='AVAILABLE_CLEAN',exhausted=True):
        return (CapturePoll(source,tuple(segments),dropped,overflowed,exhausted,visibility),)

    def go(self,*segments,**kw):
        return replay_historical_capture_polls(self.polls(*segments,**kw),scope=self.scope,root=ROOT)

    def test_clean_syn_framed_stream_reaches_p47_without_authority(self):
        r=self.go(self.seg(1,100,flags=2),self.seg(2,101,self.body))
        self.assertEqual((r.status,r.first_issue,r.transport_status,r.protocol_status),
          ('RESEARCH_TRANSPORT_ONLY',None,'OBSERVED_NO_DETECTED_GAPS','HISTORICAL_WIRE_OBSERVATION_ONLY'))
        self.assertEqual((r.source_segments,r.selected_server_messages,r.foreign_server_messages),(2,3,0))
        self.assertEqual([e.kind for e in r.replay.observations],
          ['TURN_OWNER_OBSERVED','TURN_END_OBSERVED','FIGHT_RESULT_BOUNDARY_OBSERVED'])
        self.assertFalse(r.source_completeness_verified)
        self.assertFalse(r.account_binding_verified)
        self.assertFalse(r.actionable)
        self.assertFalse(r.current_client_certified)
        self.assertEqual((r.canonical_commits,r.physical_input_sent),(0,False))

    def test_split_tcp_frame_preserves_semantic_order(self):
        a,b=self.body[:9],self.body[9:]
        r=self.go(self.seg(1,100,flags=2),self.seg(2,101,a),self.seg(3,101+len(a),b))
        self.assertEqual(r.status,'RESEARCH_TRANSPORT_ONLY')
        self.assertEqual(r.replay.decoded_messages,3)

    def test_structurally_valid_frame_without_any_is_not_silently_ignored(self):
        # Valid top-level protobuf, but no recognized game Any envelope.
        empty_semantic_frame = var(len(scalar(3,44))) + scalar(3,44)
        wire=frame('jvj',scalar(3,33))+empty_semantic_frame+frame('jup',scalar(2,33))
        r=self.go(self.seg(1,100,flags=2),self.seg(2,101,wire))
        self.assertEqual(r.status,'PARTIAL_EVIDENCE')
        self.assertEqual(r.first_issue,'P48_NON_GAME_OR_UNCLASSIFIED_FRAME')
        self.assertEqual(r.selected_server_messages,2)

    def test_unknown_between_known_framed_messages_is_not_silently_discarded(self):
        bad=frame('surprise',b'\x08\x01')
        wire=frame('jvj',scalar(3,33))+bad+frame('jup',scalar(2,33))
        r=self.go(self.seg(1,100,flags=2),self.seg(2,101,wire))
        self.assertEqual((r.status,r.first_issue,r.replay.unmapped_wire_messages),
          ('PARTIAL_EVIDENCE','P47_UNMAPPED_WIRE_SEMANTICS',1))

    def test_unanchored_capture_rejected_even_if_messages_can_be_framed(self):
        r=self.go(self.seg(1,101,self.body))
        self.assertEqual((r.status,r.blocking_issue),('BLOCKED_EVIDENCE','P48_TRANSPORT_NOT_CONTIGUOUS'))
        self.assertEqual(r.selected_server_messages,0)

    def test_gap_is_quarantined(self):
        a,b=self.body[:10],self.body[10:]
        r=self.go(self.seg(1,100,flags=2),self.seg(2,101,a),self.seg(3,111+2,b))
        self.assertEqual(r.status,'BLOCKED_EVIDENCE')
        self.assertEqual(r.blocking_issue,'P48_TRANSPORT_NOT_CONTIGUOUS')

    def test_missing_driver_loss_visibility_is_never_accepted_as_clean(self):
        for kw in ({'visibility':'UNKNOWN'},{'visibility':'AVAILABLE_DROPPED'},
                   {'dropped':1},{'overflowed':True}):
            with self.subTest(kw=kw):
                r=self.go(self.seg(1,100,flags=2),self.seg(2,101,self.body),**kw)
                self.assertEqual(r.blocking_issue,'P48_CAPTURE_LOSS_OR_DRIVER_VISIBILITY_UNKNOWN')
                self.assertTrue(r.capture_loss_visible)

    def test_changed_poll_source_generation_blocked(self):
        first=CapturePoll('generation-a',(self.seg(1,100,flags=2),),0,False,False,'AVAILABLE_CLEAN')
        second=CapturePoll('generation-b',(self.seg(2,101,self.body),),0,False,True,'AVAILABLE_CLEAN')
        r=replay_historical_capture_polls((first,second),scope=self.scope,root=ROOT)
        self.assertEqual((r.status,r.blocking_issue),('BLOCKED_EVIDENCE','P48_CAPTURE_GENERATION_CHANGED'))

    def test_nonfinal_capture_poll_is_partial(self):
        r=self.go(self.seg(1,100,flags=2),self.seg(2,101,self.body),exhausted=False)
        self.assertEqual((r.status,r.first_issue),('PARTIAL_EVIDENCE','P48_CAPTURE_POLL_BOUNDARY_INCOMPLETE'))
        self.assertEqual(r.selected_server_messages,3)

    def test_cross_flow_messages_never_masquerade_as_selected(self):
        other='separate_game_socket'
        data=frame('jvj',scalar(3,77))
        r=self.go(self.seg(1,100,flags=2),self.seg(2,101,self.body),
                  self.seg(3,999,flags=2,flow=other),self.seg(4,1000,data,flow=other))
        self.assertEqual((r.status,r.selected_server_messages,r.foreign_server_messages),
                        ('RESEARCH_TRANSPORT_ONLY',3,1))
        self.assertEqual([e.kind for e in r.replay.observations],
           ['TURN_OWNER_OBSERVED','TURN_END_OBSERVED','FIGHT_RESULT_BOUNDARY_OBSERVED'])

    def test_scope_generation_mismatch_fails(self):
        r=replay_historical_capture_polls(self.polls(self.seg(1,100,flags=2),self.seg(2,101,self.body)),
                 scope=replace(self.scope,generation=2),root=ROOT)
        self.assertEqual((r.status,r.blocking_issue),('BLOCKED_EVIDENCE','P48_FLOW_GENERATION_MISMATCH'))

    def test_incomplete_final_frame_cannot_be_clean(self):
        r=self.go(self.seg(1,100,flags=2),self.seg(2,101,self.body[:-5]))
        self.assertEqual((r.status,r.blocking_issue),('BLOCKED_EVIDENCE','P48_PROTOCOL_FRAMING_UNTRUSTED'))
        self.assertLess(r.selected_server_messages,3)

    def test_invalid_protobuf_frame_does_not_fabricate_lifecycle_event(self):
        wire=var(1)+b'\xff'
        r=self.go(self.seg(1,100,flags=2),self.seg(2,101,wire))
        self.assertEqual((r.status,r.blocking_issue),('BLOCKED_EVIDENCE','P48_PROTOCOL_FRAMING_UNTRUSTED'))
        self.assertEqual(r.selected_server_messages,0)

    def test_wrong_protocol_build_rejected(self):
        wrong=replace(self.scope,protocol_build='Dofus 3.7.11.11')
        r=replay_historical_capture_polls(self.polls(self.seg(1,100,flags=2),self.seg(2,101,self.body)),
            scope=wrong,root=ROOT)
        self.assertEqual(r.status,'BLOCKED_EVIDENCE')
        self.assertFalse(r.current_client_certified)

    def test_capture_repeated_source_ordinals_are_blocked(self):
        r=self.go(self.seg(1,100,flags=2),self.seg(2,101,self.body[:8]),
                  self.seg(2,109,self.body[8:]))
        self.assertEqual((r.status,r.blocking_issue),('BLOCKED_EVIDENCE','P48_CAPTURE_ORDER_INVALID'))

    def test_no_packets_does_not_report_clean(self):
        r=replay_historical_capture_polls(self.polls(),scope=self.scope,root=ROOT)
        self.assertEqual((r.status,r.first_issue,r.selected_server_messages),
            ('PARTIAL_EVIDENCE','P48_NO_SELECTED_SEGMENTS',0))

    def test_malformed_poll_segment_is_reported_not_crashed(self):
        # CapturePoll currently validates the tuple size, not element classes.
        bad=CapturePoll('generation',('not-a-tcp-segment',),0,False,True,'AVAILABLE_CLEAN')
        report=replay_historical_capture_polls((bad,),scope=self.scope,root=ROOT)
        self.assertEqual(report.blocking_issue,'P48_SEGMENT_TYPE_INVALID')
        self.assertFalse(report.actionable)

    def test_wrong_poll_object_fails_closed(self):
        r=replay_historical_capture_polls(('not_poll',),scope=self.scope,root=ROOT)
        self.assertEqual((r.status,r.blocking_issue),('BLOCKED_EVIDENCE','P48_POLL_TYPE_INVALID'))

if __name__=='__main__':unittest.main()
