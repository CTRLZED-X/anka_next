"""Independent Chat 08 regression for stale SYN after terminal TCP evidence.

An exact retransmission of the generation's original SYN must not be promoted
into a fresh clean connection merely because FIN/RST was already observed.
"""
from __future__ import annotations

import unittest

from anka_capture.stream import TransportEnvelopeAssembler
from anka_contracts.capture import CapturedTcpSegment


def segment(seq: int, payload: bytes = b"", *, number: int, flags: int = 0):
    return CapturedTcpSegment(
        "flow-agent08",
        "server_to_client",
        seq,
        payload,
        number,
        flags,
        f"2026-10-25T15:00:{number:02d}+00:00",
        20_000 + number,
        "TEST_FIXTURE",
    )


class TestAgent08TerminalSynRetransmission(unittest.TestCase):
    def test_identical_original_syn_after_fin_does_not_create_clean_generation(self):
        assembler = TransportEnvelopeAssembler(
            capture_session_id="capture-agent08-terminal-syn",
            flow_clients={"flow-agent08": "client-cra"},
        )

        assembler.feed(segment(100, number=1, flags=0x02))
        first = assembler.feed(
            segment(101, b"A", number=2, flags=0x18)
        )[0]
        self.assertEqual(first.connection_generation, 1)

        assembler.feed(segment(102, number=3, flags=0x01))

        # Delayed duplicate of the original SYN.  It cannot prove a new
        # generation because its sequence identity is exactly the old one.
        self.assertEqual(
            assembler.feed(segment(100, number=4, flags=0x02)),
            (),
        )

        stale_payload = assembler.feed(
            segment(101, b"B", number=5, flags=0x18)
        )[0]

        self.assertEqual(
            stale_payload.connection_generation,
            1,
            "An old identical SYN retransmission was incorrectly promoted to a "
            "fresh connection generation.",
        )
        self.assertNotEqual(stale_payload.continuity, "RECONNECTED")
        self.assertEqual(assembler.health().reconnections, 0)
        self.assertEqual(assembler.health().status, "UNCERTAIN")


if __name__ == "__main__":
    unittest.main()
