"""Agent 02 adversarial transport-finality regressions.

These tests exercise the definitive Capture -> WireEnvelope boundary directly.
They intentionally do not claim current-build Protocol or live acceptance.
"""
from __future__ import annotations

import unittest

from anka_capture.stream import TransportEnvelopeAssembler
from anka_contracts.capture import CapturedTcpSegment


def seg(seq: int, payload: bytes = b"", *, n: int, flags: int = 0,
        direction: str = "server_to_client") -> CapturedTcpSegment:
    return CapturedTcpSegment(
        "flow-a", direction, seq, payload, n, flags,
        f"2026-10-25T14:00:{n:02d}+00:00", 10_000 + n, "TEST_FIXTURE",
    )


def assembler() -> TransportEnvelopeAssembler:
    return TransportEnvelopeAssembler(
        capture_session_id="capture-agent02-finality",
        flow_clients={"flow-a": "client-cra"},
    )


class TestAgent02TransportFinality(unittest.TestCase):
    def test_pending_gap_is_uncertain_before_finish_and_survives_reconnect(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02))
        a.feed(seg(101, b"A", n=2, flags=0x18))

        self.assertEqual(a.feed(seg(110, b"late", n=3, flags=0x18)), ())
        before = a.health()
        self.assertEqual(before.status, "UNCERTAIN")
        self.assertGreaterEqual(before.unresolved_gaps, 1)

        a.feed(seg(500, n=4, flags=0x02))
        after_reconnect = a.feed(seg(501, b"B", n=5, flags=0x18))
        self.assertEqual(len(after_reconnect), 1)
        self.assertEqual(after_reconnect[0].continuity, "RECONNECTED")
        self.assertEqual(after_reconnect[0].connection_generation, 2)

        after = a.health()
        self.assertEqual(after.status, "UNCERTAIN")
        self.assertGreaterEqual(after.unresolved_gaps, 1)

    def test_payload_after_fin_is_never_complete_in_same_generation(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02))
        first = a.feed(seg(101, b"A", n=2, flags=0x18))[0]
        self.assertEqual(first.continuity, "COMPLETE")

        self.assertEqual(a.feed(seg(102, n=3, flags=0x01)), ())
        post_fin = a.feed(seg(102, b"B", n=4, flags=0x18))[0]
        self.assertEqual(post_fin.connection_generation, 1)
        self.assertEqual(post_fin.continuity, "GAP_INSIDE")
        self.assertEqual(post_fin.payload, b"B")
        self.assertEqual(a.health().status, "UNCERTAIN")

    def test_fin_is_half_close_and_does_not_poison_opposite_direction(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02, direction="server_to_client"))
        a.feed(seg(500, n=2, flags=0x02, direction="client_to_server"))
        a.feed(seg(101, b"S", n=3, flags=0x18, direction="server_to_client"))
        a.feed(seg(501, b"C", n=4, flags=0x18, direction="client_to_server"))

        a.feed(seg(102, n=5, flags=0x01, direction="server_to_client"))
        opposite = a.feed(seg(502, b"X", n=6, flags=0x18,
                              direction="client_to_server"))[0]
        self.assertEqual(opposite.connection_generation, 1)
        self.assertEqual(opposite.continuity, "COMPLETE")
        self.assertEqual(a.health().status, "CLEAN")

    def test_rst_fences_both_half_streams(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02, direction="server_to_client"))
        a.feed(seg(500, n=2, flags=0x02, direction="client_to_server"))
        a.feed(seg(101, b"S", n=3, flags=0x18, direction="server_to_client"))
        a.feed(seg(501, b"C", n=4, flags=0x18, direction="client_to_server"))

        self.assertEqual(a.feed(seg(102, n=5, flags=0x04,
                                    direction="server_to_client")), ())
        after_reset = a.feed(seg(502, b"X", n=6, flags=0x18,
                                 direction="client_to_server"))[0]
        self.assertEqual(after_reset.continuity, "RESET")
        self.assertEqual(after_reset.connection_generation, 1)
        self.assertEqual(a.health().status, "UNCERTAIN")

    def test_syn_after_terminal_evidence_rotates_generation(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02))
        old = a.feed(seg(101, b"A", n=2, flags=0x18))[0]
        a.feed(seg(102, n=3, flags=0x01))

        a.feed(seg(500, n=4, flags=0x02))
        new = a.feed(seg(501, b"B", n=5, flags=0x18))[0]
        self.assertEqual((old.connection_generation, new.connection_generation), (1, 2))
        self.assertNotEqual(old.connection_id, new.connection_id)
        self.assertEqual(new.continuity, "RECONNECTED")

    def test_reconnect_marker_never_overwrites_first_gap_fence(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02))
        a.feed(seg(101, b"A", n=2, flags=0x18))
        a.feed(seg(500, n=3, flags=0x02))

        self.assertEqual(a.feed(seg(510, b"late", n=4, flags=0x18)), ())
        flushed = a.finish()
        self.assertEqual(len(flushed), 1)
        self.assertEqual(flushed[0].connection_generation, 2)
        self.assertEqual(flushed[0].continuity, "GAP_BEFORE")
        self.assertNotEqual(flushed[0].continuity, "RECONNECTED")
        self.assertEqual(a.health().status, "UNCERTAIN")

    def test_pending_bytes_beyond_fin_are_fenced_when_gap_closes(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02))
        self.assertEqual(a.feed(seg(103, b"X", n=2, flags=0x18)), ())

        out = a.feed(seg(101, b"ab", n=3, flags=0x19))
        self.assertEqual([x.payload for x in out], [b"ab", b"X"])
        self.assertEqual([x.continuity for x in out], ["COMPLETE", "GAP_INSIDE"])
        self.assertEqual(a.health().status, "UNCERTAIN")


if __name__ == "__main__":
    unittest.main()
