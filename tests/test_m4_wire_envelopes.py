from __future__ import annotations
import ast
from pathlib import Path
import unittest
from anka_capture.replay import replay_segments
from anka_capture.stream import TransportEnvelopeAssembler
from anka_contracts.capture import CapturedTcpSegment,CapturePoll

ROOT=Path(__file__).resolve().parents[1]

def seg(seq,payload=b'',*,n=1,flags=0,flow='flow-a',direction='client_to_server'):
    return CapturedTcpSegment(flow,direction,seq,payload,n,flags,
        f'2026-10-22T00:00:{n:02d}+00:00',1000+n,'TEST_FIXTURE')

def asm(**kwargs): return TransportEnvelopeAssembler(capture_session_id='capture-test',flow_clients={'flow-a':'client-cra','flow-b':'client-enu'},**kwargs)

class TestM4OrderedEnvelopes(unittest.TestCase):
    def test_ordered_stream_emits_exact_offsets(self):
        a=asm();self.assertEqual(a.feed(seg(100,n=1,flags=2)),())
        x=a.feed(seg(101,b'abc',n=2))[0];y=a.feed(seg(104,b'de',n=3))[0]
        self.assertEqual((x.payload,x.transport_start_offset,x.effective_transport_end_offset,x.continuity),(b'abc',0,3,'COMPLETE'))
        self.assertEqual((y.payload,y.transport_start_offset,y.effective_transport_end_offset,y.continuity),(b'de',3,5,'COMPLETE'))
        self.assertEqual((x.client_instance_id,x.connection_generation),('client-cra',1))
        self.assertEqual(a.health().status,'CLEAN')

    def test_out_of_order_is_buffered_and_reassembled_without_gap(self):
        a=asm();a.feed(seg(100,n=1,flags=2))
        self.assertEqual(a.feed(seg(104,b'de',n=2)),())
        out=a.feed(seg(101,b'abc',n=3))
        self.assertEqual([x.payload for x in out],[b'abc',b'de'])
        self.assertTrue(all(x.continuity=='COMPLETE' for x in out))
        self.assertEqual(a.health().unresolved_gaps,0)
        self.assertEqual(a.health().reordered_segments,1)

    def test_unresolved_gap_is_explicit_at_finish_and_offset_includes_missing_bytes(self):
        a=asm();a.feed(seg(100,n=1,flags=2));first=a.feed(seg(101,b'ab',n=2))[0]
        self.assertEqual(a.feed(seg(106,b'xy',n=3)),())
        late=a.finish()[0]
        self.assertEqual(first.effective_transport_end_offset,2)
        self.assertEqual((late.transport_start_offset,late.effective_transport_end_offset,late.continuity),(5,7,'GAP_BEFORE'))
        self.assertEqual(a.health().status,'UNCERTAIN')

    def test_retransmission_and_overlap_do_not_duplicate_bytes(self):
        a=asm();a.feed(seg(100,n=1,flags=2));a.feed(seg(101,b'abcd',n=2))
        self.assertEqual(a.feed(seg(101,b'abcd',n=3)),())
        out=a.feed(seg(103,b'cdef',n=4))
        self.assertEqual([x.payload for x in out],[b'ef'])
        self.assertGreaterEqual(a.health().duplicate_segments,1)

    def test_reconnect_rotates_connection_generation(self):
        a=asm();a.feed(seg(100,n=1,flags=2));x=a.feed(seg(101,b'a',n=2))[0]
        a.feed(seg(500,n=3,flags=2));y=a.feed(seg(501,b'b',n=4))[0]
        self.assertNotEqual(x.connection_id,y.connection_id)
        self.assertEqual((x.connection_generation,y.connection_generation),(1,2))
        self.assertEqual(y.continuity,'RECONNECTED')
        self.assertEqual(a.health().reconnects,1)

    def test_midstream_without_syn_is_never_called_complete(self):
        a=asm();x=a.feed(seg(800,b'abc',n=1))[0]
        self.assertEqual(x.continuity,'GAP_BEFORE')
        self.assertEqual(a.health().status,'UNCERTAIN')

class TestM4ScopeAndLoss(unittest.TestCase):
    def test_two_flows_same_server_port_remain_client_scoped(self):
        a=asm();
        a.feed(seg(10,n=1,flags=2,flow='flow-a'));a.feed(seg(20,n=2,flags=2,flow='flow-b'))
        x=a.feed(seg(11,b'cra',n=3,flow='flow-a'))[0];y=a.feed(seg(21,b'enu',n=4,flow='flow-b'))[0]
        self.assertEqual((x.client_instance_id,y.client_instance_id),('client-cra','client-enu'))

    def test_unbound_flow_is_not_guessed(self):
        a=asm();r=a.feed(seg(1,b'x',flow='unknown'))
        self.assertEqual(r,());self.assertEqual(a.health().ambiguous_or_unbound_segments,1);self.assertEqual(a.health().status,'UNCERTAIN')

    def test_poll_loss_fences_next_emitted_bytes(self):
        a=asm();a.consume_poll(CapturePoll('g',(seg(100,n=1,flags=2),),0,False,False,'AVAILABLE_CLEAN'))
        clean=a.consume_poll(CapturePoll('g',(seg(101,b'a',n=2),),0,False,False,'AVAILABLE_CLEAN'))[0]
        lost=CapturePoll('g',(),1,False,False,'AVAILABLE_DROPPED');a.consume_poll(lost)
        after=a.consume_poll(CapturePoll('g',(seg(102,b'b',n=3),),0,False,False,'AVAILABLE_CLEAN'))[0]
        self.assertEqual(clean.continuity,'COMPLETE');self.assertEqual(after.continuity,'GAP_INSIDE')
        self.assertEqual(a.health().capture_loss_fences,1)

    def test_pending_bound_overflow_is_explicit_uncertainty(self):
        a=asm(max_pending_segments=2);a.feed(seg(100,n=1,flags=2))
        for n,seq in enumerate((110,120,130),2): a.feed(seg(seq,b'x',n=n))
        h=a.health();self.assertEqual(h.status,'UNCERTAIN');self.assertGreaterEqual(h.buffer_overflow_fences,1)

class TestM4ReplayParity(unittest.TestCase):
    def test_replay_and_poll_path_use_same_envelope_schema_and_values(self):
        rows=(seg(100,n=1,flags=2),seg(104,b'd',n=2),seg(101,b'abc',n=3))
        expected=replay_segments(rows,capture_session_id='capture-test',flow_clients={'flow-a':'client-cra'})
        a=TransportEnvelopeAssembler(capture_session_id='capture-test',flow_clients={'flow-a':'client-cra'})
        actual=a.consume_poll(CapturePoll('gen',rows,0,False,True,'AVAILABLE_CLEAN'))+a.finish()
        fields=lambda xs:[(x.connection_id,x.direction,x.transport_start_offset,x.effective_transport_end_offset,x.payload,x.continuity,x.connection_generation) for x in xs]
        self.assertEqual(fields(actual),fields(expected))

    def test_legacy_timestamp_absence_is_labeled_not_fabricated_as_live(self):
        raw=CapturedTcpSegment('flow-a','client_to_server',1,b'x',1)
        x=replay_segments((raw,),capture_session_id='capture-test',flow_clients={'flow-a':'client-cra'})[0]
        self.assertEqual(x.timestamp_provenance,'REPLAY_ORDINAL')

class TestM4Architecture(unittest.TestCase):
    def test_capture_has_no_protocol_imports(self):
        bad=[]
        for p in (ROOT/'src/anka_capture').glob('*.py'):
            tree=ast.parse(p.read_text())
            for n in ast.walk(tree):
                if isinstance(n,ast.ImportFrom) and (n.module or '').startswith('anka_protocol'): bad.append(str(p))
                if isinstance(n,ast.Import) and any(x.name.startswith('anka_protocol') for x in n.names): bad.append(str(p))
        self.assertEqual(bad,[])

if __name__=='__main__':unittest.main()
