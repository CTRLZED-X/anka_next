"""Agent 02 adversarial transport-finality regressions.

These tests exercise the definitive Capture -> WireEnvelope boundary directly.
They intentionally do not claim current-build Protocol or live acceptance.
"""
from __future__ import annotations

import unittest

from anka_capture.stream import TransportEnvelopeAssembler
from anka_capture.transport import TransportAuditor
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

    def test_fin_then_exact_original_syn_is_duplicate_not_fresh_generation(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02))
        a.feed(seg(101, b"A", n=2, flags=0x18))
        a.feed(seg(102, n=3, flags=0x01))

        self.assertEqual(a.feed(seg(100, n=4, flags=0x02)), ())
        self.assertEqual(a.health().reconnects, 0)
        stale = a.feed(seg(102, b"B", n=5, flags=0x18))[0]
        self.assertEqual(stale.connection_generation, 1)
        self.assertEqual(stale.continuity, "GAP_INSIDE")
        self.assertEqual(a.health().status, "UNCERTAIN")

    def test_rst_then_exact_original_syn_is_duplicate_not_fresh_generation(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02))
        a.feed(seg(101, b"A", n=2, flags=0x18))
        a.feed(seg(102, n=3, flags=0x04))

        self.assertEqual(a.feed(seg(100, n=4, flags=0x02)), ())
        self.assertEqual(a.health().reconnects, 0)
        stale = a.feed(seg(102, b"B", n=5, flags=0x18))[0]
        self.assertEqual(stale.connection_generation, 1)
        self.assertEqual(stale.continuity, "RESET")
        self.assertEqual(a.health().status, "UNCERTAIN")

    def test_terminal_different_syn_still_establishes_distinguishable_generation(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02))
        a.feed(seg(101, b"A", n=2, flags=0x18))
        a.feed(seg(102, n=3, flags=0x01))

        a.feed(seg(500, n=4, flags=0x02))
        fresh = a.feed(seg(501, b"B", n=5, flags=0x18))[0]
        self.assertEqual(fresh.connection_generation, 2)
        self.assertEqual(fresh.continuity, "RECONNECTED")
        self.assertEqual(a.health().reconnects, 1)

    def test_identical_syn_terminal_rule_matches_metadata_auditor(self):
        segments = (
            seg(100, n=1, flags=0x02),
            seg(101, b"A", n=2, flags=0x18),
            seg(102, n=3, flags=0x01),
            seg(100, n=4, flags=0x02),
            seg(102, b"B", n=5, flags=0x18),
        )
        a = assembler()
        emitted = []
        for item in segments:
            emitted.extend(a.feed(item))
        detailed = a.health()
        metadata = TransportAuditor().audit(segments)

        self.assertEqual(detailed.reconnects, 0)
        self.assertEqual(metadata.reconnects, 0)
        self.assertGreaterEqual(detailed.duplicate_segments, 1)
        self.assertGreaterEqual(metadata.duplicates, 1)
        self.assertEqual(detailed.status, "UNCERTAIN")
        self.assertEqual(metadata.status, "TRANSPORT_UNCERTAIN")
        self.assertEqual(emitted[-1].connection_generation, 1)
        self.assertNotIn(emitted[-1].continuity, ("COMPLETE", "RECONNECTED"))

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


class TestAgent02OverlapTruth(unittest.TestCase):
    def test_exact_same_range_same_bytes_is_proven_duplicate(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02))
        a.feed(seg(101, b"abcd", n=2))
        self.assertEqual(a.feed(seg(101, b"abcd", n=3)), ())
        h = a.health()
        self.assertEqual(h.status, "CLEAN")
        self.assertGreaterEqual(h.duplicate_segments, 1)
        self.assertEqual(h.unresolved_gaps, 0)

    def test_exact_same_range_different_bytes_is_transport_conflict(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02))
        a.feed(seg(101, b"A", n=2))
        self.assertEqual(a.feed(seg(101, b"B", n=3)), ())
        h = a.health()
        self.assertEqual(h.status, "UNCERTAIN")
        self.assertGreaterEqual(h.unresolved_gaps, 1)
        after = a.feed(seg(102, b"C", n=4))[0]
        self.assertEqual(after.continuity, "GAP_INSIDE")

    def test_partial_overlap_matching_bytes_emits_only_new_suffix(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02))
        a.feed(seg(101, b"abcd", n=2))
        out = a.feed(seg(103, b"cdef", n=3))
        self.assertEqual([x.payload for x in out], [b"ef"])
        self.assertEqual(out[0].continuity, "COMPLETE")
        self.assertEqual(a.health().status, "CLEAN")

    def test_partial_overlap_conflict_fences_new_suffix(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02))
        a.feed(seg(101, b"abcd", n=2))
        out = a.feed(seg(103, b"Xdef", n=3))
        self.assertEqual([x.payload for x in out], [b"ef"])
        self.assertEqual(out[0].continuity, "GAP_INSIDE")
        self.assertEqual(a.health().status, "UNCERTAIN")

    def test_shorter_exact_retransmission_requires_and_passes_byte_proof(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02))
        a.feed(seg(101, b"abcd", n=2))
        self.assertEqual(a.feed(seg(102, b"bc", n=3)), ())
        h = a.health()
        self.assertEqual(h.status, "CLEAN")
        self.assertGreaterEqual(h.duplicate_segments, 1)

    def test_longer_retransmission_verifies_overlap_before_extension(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02))
        a.feed(seg(101, b"ab", n=2))
        out = a.feed(seg(101, b"abcd", n=3))
        self.assertEqual([x.payload for x in out], [b"cd"])
        self.assertEqual(out[0].continuity, "COMPLETE")
        self.assertEqual(a.health().status, "CLEAN")

    def test_pending_reordered_overlap_uses_same_conflict_rule(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02))
        self.assertEqual(a.feed(seg(104, b"ZX", n=2)), ())
        out = a.feed(seg(101, b"abcd", n=3))
        self.assertEqual([x.payload for x in out], [b"abcd", b"X"])
        self.assertEqual(out[1].continuity, "GAP_INSIDE")
        self.assertEqual(a.health().status, "UNCERTAIN")

    def test_finish_pending_overlap_uses_same_conflict_rule(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02))
        self.assertEqual(a.feed(seg(110, b"abcd", n=2)), ())
        self.assertEqual(a.feed(seg(112, b"cX", n=3)), ())
        out = a.finish()
        self.assertEqual([x.payload for x in out], [b"abcd"])
        self.assertEqual(out[0].continuity, "GAP_BEFORE")
        self.assertEqual(a.health().status, "UNCERTAIN")
        self.assertGreaterEqual(a.health().unresolved_gaps, 1)

    def test_fin_boundary_retransmission_conflict_remains_uncertain(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02))
        a.feed(seg(101, b"ab", n=2, flags=0x19))
        self.assertEqual(a.feed(seg(101, b"aX", n=3)), ())
        self.assertEqual(a.health().status, "UNCERTAIN")
        post_fin = a.feed(seg(103, b"Z", n=4))[0]
        self.assertEqual(post_fin.continuity, "GAP_INSIDE")

    def test_new_generation_does_not_reuse_old_generation_byte_proof(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02))
        a.feed(seg(101, b"A", n=2))
        a.feed(seg(102, n=3, flags=0x04))
        a.feed(seg(500, n=4, flags=0x02))
        fresh = a.feed(seg(501, b"B", n=5))[0]
        self.assertEqual(fresh.connection_generation, 2)
        self.assertEqual(fresh.continuity, "RECONNECTED")

        # A stale old-generation byte range is not allowed to match against the
        # retired proof window. It is unverifiable in generation 2 and fails closed.
        self.assertEqual(a.feed(seg(101, b"A", n=6)), ())
        self.assertEqual(a.health().status, "UNCERTAIN")
        fenced = a.feed(seg(502, b"C", n=7))[0]
        self.assertEqual(fenced.connection_generation, 2)
        self.assertEqual(fenced.continuity, "GAP_INSIDE")

    def test_conflict_fences_opposite_direction_in_same_connection_generation(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02, direction="server_to_client"))
        a.feed(seg(500, n=2, flags=0x02, direction="client_to_server"))
        a.feed(seg(101, b"S", n=3, direction="server_to_client"))
        a.feed(seg(501, b"C", n=4, direction="client_to_server"))

        self.assertEqual(
            a.feed(seg(101, b"X", n=5, direction="server_to_client")),
            (),
        )
        opposite = a.feed(seg(502, b"D", n=6, direction="client_to_server"))[0]
        self.assertEqual(opposite.continuity, "GAP_INSIDE")
        self.assertEqual(a.health().status, "UNCERTAIN")

    def test_overlap_older_than_bounded_proof_window_is_unverifiable(self):
        a = assembler()
        a.feed(seg(100, n=1, flags=0x02))
        payload = b"A" * 4097
        a.feed(seg(101, payload, n=2))
        self.assertEqual(a.feed(seg(101, b"A", n=3)), ())
        h = a.health()
        self.assertEqual(h.status, "UNCERTAIN")
        self.assertEqual(h.duplicate_segments, 0)
        fenced = a.feed(seg(4198, b"B", n=4))[0]
        self.assertEqual(fenced.continuity, "GAP_INSIDE")

    def test_sequence_wrap_remains_conservatively_uncertain(self):
        a = assembler()
        a.feed(seg(0xFFFFFFFE, n=1, flags=0x02))
        self.assertEqual(a.feed(seg(0xFFFFFFFF, b"AB", n=2)), ())
        self.assertEqual(a.health().status, "UNCERTAIN")

    def test_metadata_auditor_also_rejects_conflicting_same_range_bytes(self):
        health = TransportAuditor().audit((
            seg(100, n=1, flags=0x02),
            seg(101, b"A", n=2),
            seg(101, b"B", n=3),
        ))
        self.assertEqual(health.status, "TRANSPORT_UNCERTAIN")
        self.assertGreaterEqual(health.unresolved_gap_directions, 1)
        self.assertEqual(health.duplicates, 0)


if __name__ == "__main__":
    unittest.main()
