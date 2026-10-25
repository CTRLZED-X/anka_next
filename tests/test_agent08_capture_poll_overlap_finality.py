"""Chat 08 adversarial regression for same-poll overlap-conflict finality.

Failure specification:
A CapturePoll may contain a clean envelope candidate followed later in that same
poll by a fully overlapped conflicting retransmission. Because consume_poll()
returns only after every segment has been processed, any conflict discovered
before return must fence every not-yet-admitted envelope from that connection
generation. Returning an earlier COMPLETE envelope after health is already
UNCERTAIN launders the conflict into downstream Protocol authority.
"""
from __future__ import annotations

import unittest

from anka_capture.stream import TransportEnvelopeAssembler
from anka_contracts.capture import CapturedTcpSegment, CapturePoll


FLOW = "tcp-chat08-poll-finality"


def seg(
    seq: int,
    payload: bytes = b"",
    *,
    packet: int,
    flags: int = 0x18,
    direction: str = "server_to_client",
) -> CapturedTcpSegment:
    return CapturedTcpSegment(
        FLOW,
        direction,
        seq,
        payload,
        packet,
        flags,
    )


class TestAgent08CapturePollOverlapFinality(unittest.TestCase):
    def test_same_poll_conflict_fences_all_returned_same_generation_envelopes(self):
        assembler = TransportEnvelopeAssembler(
            capture_session_id="capture-chat08-poll-finality",
            flow_clients={FLOW: "client-cra"},
        )

        clean_payload = b"semantic-frame"
        conflicting = bytes([clean_payload[0] ^ 1]) + clean_payload[1:]

        poll = CapturePoll(
            "source-chat08-poll-finality",
            (
                seg(100, packet=1, flags=0x02),
                seg(101, clean_payload, packet=2),
                seg(101, conflicting, packet=3),
            ),
            0,
            False,
            False,
            "AVAILABLE_CLEAN",
        )

        returned = assembler.consume_poll(poll)
        health = assembler.health()

        self.assertEqual(health.status, "UNCERTAIN")
        self.assertGreaterEqual(health.unresolved_gaps, 1)

        trusted = {
            "COMPLETE",
            "CONTIGUOUS",
            "RECONNECTED",
        }
        unsafe = [
            envelope
            for envelope in returned
            if envelope.connection_generation == 1
            and envelope.continuity in trusted
        ]
        self.assertEqual(
            unsafe,
            [],
            "same-poll conflict must retroactively fence or suppress every "
            "not-yet-admitted same-generation clean envelope",
        )


if __name__ == "__main__":
    unittest.main()
