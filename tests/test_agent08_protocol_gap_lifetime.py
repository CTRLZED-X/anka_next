"""Independent Chat 08 regression for transport-gap lifetime.

Rejecting one GAP/RESET envelope is insufficient if Protocol then resumes decoding
later bytes in the same connection generation using parser state from before the
gap. Once continuity is lost, the generation's mutable decoder context is no
longer trustworthy.
"""
from __future__ import annotations

import unittest

from anka_contracts.protocol import ProtocolAdmissionDecision
from anka_contracts.wire import WireEnvelope
from anka_protocol.adapters.dofus_3_7_10_10.adapter import Historical371010Adapter
from anka_protocol.adapters.dofus_3_7_10_10.manifest import descriptor
from anka_protocol.sdk import ProtocolTransaction


JTK = bytes.fromhex(
    "0a1b221110010a0d080b10feffffffffffffffff01220610170a020805108906"
)


def _varint(value: int) -> bytes:
    out = []
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def _field(number: int, value: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _framed_any(name: str, body: bytes) -> bytes:
    any_message = _field(1, b"type.ankama.com/" + name.encode()) + _field(2, body)
    return _varint(len(any_message)) + any_message


def _envelope(payload: bytes, *, sequence: int, continuity: str) -> WireEnvelope:
    return WireEnvelope(
        "capture-agent08-gap",
        "client-cra",
        "conn-agent08-gap",
        "server_to_client",
        sequence * 100,
        sequence,
        "2026-10-25T15:00:00+00:00",
        sequence,
        payload,
        continuity=continuity,
        connection_generation=1,
        source_packet_number=sequence,
        timestamp_provenance="TEST_FIXTURE",
    )


class _Admission:
    def __init__(self):
        self.batches = []

    def admit_candidate_batch(self, batch):
        self.batches.append(batch)
        return ProtocolAdmissionDecision("COMMITTED", 10)


class TestAgent08ProtocolGapLifetime(unittest.TestCase):
    def test_gap_poison_prevents_reuse_of_pre_gap_partial_decoder_context(self):
        adapter = Historical371010Adapter(
            descriptor=descriptor(),
            account_id="acct-cra",
            client_instance_id="client-cra",
            connection_id="conn-agent08-gap",
            connection_generation=1,
        )
        admission = _Admission()
        transaction = ProtocolTransaction(adapter, admission)

        complete_message = _framed_any("jtk", JTK)
        cut = max(2, len(complete_message) // 2)

        prefix = transaction.process(
            _envelope(
                complete_message[:cut],
                sequence=1,
                continuity="COMPLETE",
            )
        )
        self.assertEqual(prefix.status, "COMMITTED")
        self.assertEqual(prefix.batch.candidates, ())

        gap = transaction.process(
            _envelope(b"UNCERTAIN-BYTES", sequence=2, continuity="GAP_INSIDE")
        )
        self.assertEqual(gap.status, "REJECTED_TRANSPORT")

        # The later bytes happen to complete the pre-gap partial frame if the old
        # parser buffer is reused. That is exactly what must never become
        # authoritative after continuity was lost.
        after_gap = transaction.process(
            _envelope(
                complete_message[cut:],
                sequence=3,
                continuity="COMPLETE",
            )
        )

        self.assertNotEqual(
            after_gap.status,
            "COMMITTED",
            "Protocol accepted post-gap semantics by reusing decoder context from "
            "before the continuity break.",
        )
        self.assertTrue(
            transaction.poisoned,
            "A continuity break must fence the connection generation until a new "
            "generation/runtime is established.",
        )
        self.assertEqual(
            len(admission.batches),
            1,
            "No post-gap batch may reach Canonical admission in the same generation.",
        )


if __name__ == "__main__":
    unittest.main()
