import unittest
from anka_capture.transport import TransportAuditor
from anka_contracts.capture import CapturedTcpSegment

def s(number,seq,data=b'', flags=0, flow='test', direction='client_to_server'):
    return CapturedTcpSegment(flow,direction,seq,data,number,flags)

class TestTransportHealth(unittest.TestCase):
    def test_no_syn_is_uncertain_not_green(self):
        health=TransportAuditor().audit((s(1,500,b'opaque'),))
        self.assertEqual(health.status,'TRANSPORT_UNCERTAIN')
        self.assertEqual(health.unanchored_directions,1)
    def test_unresolved_hole_is_uncertain(self):
        health=TransportAuditor().audit((s(1,100,flags=2),s(2,101,b'AA'),s(3,110,b'BB')))
        self.assertEqual(health.unresolved_gap_directions,1)
    def test_resolved_reordering(self):
        health=TransportAuditor().audit((s(1,100,flags=2),s(2,105,b'BB'),s(3,101,b'AAAA')))
        self.assertEqual(health.unresolved_gap_directions,0)
        self.assertEqual(health.reordered_segments,1)
        self.assertEqual(health.status,'OBSERVED_NO_DETECTED_GAPS')
    def test_duplicate_segment(self):
        health=TransportAuditor().audit((s(1,100,flags=2),s(2,101,b'A'),s(3,101,b'A')))
        self.assertEqual(health.duplicates,1)
    def test_reconnection_resets_generation(self):
        health=TransportAuditor().audit((s(1,100,flags=2),s(2,101,b'A'),s(3,300,flags=2),s(4,301,b'BB')))
        self.assertEqual(health.reconnects,1)
        self.assertEqual(health.unresolved_gap_directions,0)
    def test_fin_without_new_syn_not_verified(self):
        health=TransportAuditor().audit((s(1,100,flags=2),s(2,101,b'A',flags=1),s(3,102,b'B')))
        self.assertEqual(health.status,'TRANSPORT_UNCERTAIN')
    def test_sequence_wrap_unverified(self):
        health=TransportAuditor().audit((s(1,0xfffffffe,flags=2),s(2,0xffffffff,b'AB')))
        self.assertEqual(health.status,'TRANSPORT_UNCERTAIN')
    def test_packet_order_rejection(self):
        with self.assertRaisesRegex(ValueError,'CAPTURE_PACKET_ORDER_INVALID'):
            TransportAuditor().audit((s(1,100,flags=2),s(1,101,b'x')))
    def test_payload_redacted_from_repr(self):
        seg=s(1,101,b'SECRET123',flow='192.0.2.1')
        self.assertNotIn('SECRET123',repr(seg));self.assertNotIn('192.0.2.1',repr(seg))

class TestMultipleGenerations(unittest.TestCase):
    def test_previous_generation_gap_survives_new_clean_connection(self):
        health=TransportAuditor().audit((s(1,100,flags=2),s(2,105,b'AA'),s(3,300,flags=2),s(4,301,b'B')))
        self.assertEqual(health.unresolved_gap_directions,1)
        self.assertEqual(health.status,'TRANSPORT_UNCERTAIN')
    def test_retransmitted_identical_syn_is_not_reconnect(self):
        health=TransportAuditor().audit((s(1,100,flags=2),s(2,100,flags=2),s(3,101,b'A')))
        self.assertEqual(health.reconnects,0)
        self.assertEqual(health.duplicates,1)
    def test_gap_one_generation_and_second_complete(self):
        health=TransportAuditor().audit((s(1,100,flags=2),s(2,115,b'A'),s(3,200,flags=2),s(4,201,b'OK')))
        self.assertEqual(health.status,'TRANSPORT_UNCERTAIN')

class TestHandshakeEdges(unittest.TestCase):
    def test_late_identical_syn_retransmission_does_not_reset_stream(self):
        health=TransportAuditor().audit((s(1,100,flags=2),s(2,101,b'AAAA'),s(3,100,flags=2),s(4,105,b'BB')))
        self.assertEqual(health.reconnects,0)
        self.assertEqual(health.duplicates,1)
        self.assertEqual(health.unresolved_gap_directions,0)

class TestFutureLiveSourceContract(unittest.TestCase):
    def test_poll_loss_cannot_be_misreported_complete(self):
        from anka_contracts.capture import CapturePoll
        poll=CapturePoll('capture-gen-1',(),1,False,False)
        self.assertFalse(poll.transport_evidence_complete)
        self.assertFalse(CapturePoll('capture-gen-1',(),0,True,False).transport_evidence_complete)
        self.assertTrue(CapturePoll('capture-gen-1',(),0,False,False).transport_evidence_complete)
    def test_poll_max_bounds(self):
        from anka_contracts.capture import CapturePoll
        with self.assertRaisesRegex(ValueError,'POLL_BATCH_TOO_LARGE'):
            CapturePoll('cap-1',tuple(s(i+1,100) for i in range(4097)),0,False,False)
    def test_poll_does_not_expose_payload_in_repr(self):
        from anka_contracts.capture import CapturePoll
        poll=CapturePoll('cap-1',(s(1,100,b'SECRETXYZ'),),0,False,False)
        self.assertNotIn('SECRETXYZ',repr(poll))
