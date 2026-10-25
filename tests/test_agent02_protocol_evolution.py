"""Agent 02 protocol-evolution and consumer-impact regressions.

The suite pins fail-closed properties needed for frequent protocol replacement.
It does not grant current-build, live, Canonical, or physical-input authority.
"""
from __future__ import annotations

import unittest

from anka_capture.stream import TransportEnvelopeAssembler
from anka_contracts.capture import CapturedTcpSegment, CapturePoll
from anka_contracts.protocol import AdapterReleaseDescriptor, ProtocolAdmissionDecision
from anka_protocol.adapters.dofus_3_7_10_10.adapter import Historical371010Adapter
from anka_protocol.adapters.dofus_3_7_10_10.manifest import descriptor as historical_descriptor
from anka_protocol.certification.impact import semantic_impact_report
from anka_protocol.registry import (
    ProtocolActivationRejected,
    ProtocolAdapterNotFound,
    ProtocolRegistry,
)
from anka_protocol.sdk import ProtocolTransaction
from anka_protocol.sdk.opaque import OpaquePolicy
from anka_contracts.wire import WireEnvelope


def release(release_id: str, build: str, lifecycle: str = "STAGED") -> AdapterReleaseDescriptor:
    return AdapterReleaseDescriptor(
        release_id,
        build,
        "0" * 64,
        "1" * 64,
        1,
        0,
        lifecycle,
        capabilities=("TURN_OWNER_OBSERVED",),
        certified_scenarios=(),
        action_scopes=("end_turn",) if lifecycle == "ACTION_SCOPED_CERTIFIED" else (),
    )


def varint(value: int) -> bytes:
    out = []
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def field(number: int, value: bytes) -> bytes:
    return varint((number << 3) | 2) + varint(len(value)) + value


def framed_any(name: str, body: bytes) -> bytes:
    any_message = field(1, b"type.ankama.com/" + name.encode("ascii")) + field(2, body)
    return varint(len(any_message)) + any_message


def envelope(payload: bytes, *, direction: str = "server_to_client",
             continuity: str = "COMPLETE", producer: int = 1,
             connection: str = "conn-agent02-protocol", generation: int = 1) -> WireEnvelope:
    return WireEnvelope(
        "capture-agent02-protocol",
        "client-cra",
        connection,
        direction,
        0,
        producer,
        "2026-10-25T14:00:00+00:00",
        producer,
        payload,
        continuity,
        len(payload),
        generation,
        producer,
        "TEST_FIXTURE",
    )


class DummyAdapter:
    def __init__(self, descriptor: AdapterReleaseDescriptor):
        self.descriptor = descriptor


class RecordingAdmission:
    def __init__(self):
        self.seen = []

    def admit_candidate_batch(self, batch):
        self.seen.append(batch)
        return ProtocolAdmissionDecision("COMMITTED", len(self.seen), None)


JTK = bytes.fromhex(
    "0a1b221110010a0d080b10feffffffffffffffff01220610170a020805108906"
)


class TestAgent02ProtocolEvolution(unittest.TestCase):
    def test_active_old_build_is_never_nearest_version_fallback(self):
        old = release("adapter-agent02-old", "Dofus 9.9.1", "ACTION_SCOPED_CERTIFIED")
        registry = ProtocolRegistry()
        registry.register(old, lambda **_: DummyAdapter(old))
        registry.activate(
            old.adapter_release_id,
            physical_input_disarmed=True,
            unresolved_may_have_sent=False,
            fresh_connection_generation=True,
        )
        with self.assertRaises(ProtocolAdapterNotFound):
            registry.select_active_exact("Dofus 9.9.2")

    def test_new_release_cannot_silently_replace_active_release_for_same_build(self):
        first = release("adapter-agent02-first", "Dofus 9.9.9", "ACTION_SCOPED_CERTIFIED")
        second = release("adapter-agent02-second", "Dofus 9.9.9", "ACTION_SCOPED_CERTIFIED")
        registry = ProtocolRegistry()
        registry.register(first, lambda **_: DummyAdapter(first))
        registry.register(second, lambda **_: DummyAdapter(second))
        registry.activate(
            first.adapter_release_id,
            physical_input_disarmed=True,
            unresolved_may_have_sent=False,
            fresh_connection_generation=True,
        )
        with self.assertRaisesRegex(ProtocolActivationRejected, "PROTOCOL_BUILD_ALREADY_HAS_ACTIVE_RELEASE"):
            registry.activate(
                second.adapter_release_id,
                physical_input_disarmed=True,
                unresolved_may_have_sent=False,
                fresh_connection_generation=True,
            )

    def test_removed_turn_owner_semantics_blocks_affected_consumers(self):
        report = semantic_impact_report(
            {"TURN_OWNER_OBSERVED": (("actor_id", "1"),)},
            {},
        )
        self.assertTrue(report.blocks_build)
        self.assertEqual(report.changed_kinds, ("TURN_OWNER_OBSERVED",))
        impact = report.impacts[0]
        self.assertEqual(impact.change, "REMOVED")
        self.assertEqual(impact.safety_effect, "BLOCK_BUILD")
        self.assertIn("anka_coordination", impact.consumers)
        self.assertIn("anka_execution", impact.consumers)
        self.assertIn("end_turn", impact.action_scopes)

    def test_changed_resource_semantics_blocks_cast_and_move_consumers(self):
        report = semantic_impact_report(
            {"ACTOR_RESOURCE_ABSOLUTE": (("resource", "AP"),)},
            {"ACTOR_RESOURCE_ABSOLUTE": (("resource", "MP"),)},
        )
        self.assertTrue(report.blocks_build)
        impact = report.impacts[0]
        self.assertEqual(impact.change, "CHANGED")
        self.assertIn("cast", impact.action_scopes)
        self.assertIn("move", impact.action_scopes)

    def transaction(self, *, generation=1, connection="conn-agent02-protocol"):
        admission = RecordingAdmission()
        adapter = Historical371010Adapter(
            descriptor=historical_descriptor(),
            account_id="acct-cra",
            client_instance_id="client-cra",
            connection_id=connection,
            connection_generation=generation,
        )
        return ProtocolTransaction(adapter, admission), adapter, admission

    def test_partial_prefix_gap_suffix_cannot_resume_semantic_admission(self):
        txn, adapter, admission = self.transaction()
        framed = framed_any("jtk", JTK)
        cut = max(2, len(framed) // 2)

        first = txn.process(envelope(framed[:cut], producer=1))
        self.assertEqual(first.status, "COMMITTED")
        self.assertEqual(first.batch.decode_health, "FRAMING_IN_PROGRESS")
        before_gap = adapter.checkpoint_runtime_context()

        gap = txn.process(envelope(b"", continuity="GAP_INSIDE", producer=2))
        self.assertEqual(gap.status, "REJECTED_TRANSPORT")
        self.assertTrue(txn.poisoned)

        suffix = txn.process(envelope(framed[cut:], producer=3))
        self.assertEqual(suffix.status, "REJECTED_POISONED")
        self.assertEqual(len(admission.seen), 1)
        self.assertEqual(admission.seen[0].candidates, ())
        self.assertEqual(before_gap.digest, adapter.checkpoint_runtime_context().digest)

    def test_partial_prefix_reset_later_bytes_cannot_resume(self):
        txn, _adapter, admission = self.transaction()
        framed = framed_any("jtk", JTK)
        cut = max(2, len(framed) // 2)

        self.assertEqual(txn.process(envelope(framed[:cut], producer=1)).status, "COMMITTED")
        reset = txn.process(envelope(b"", continuity="RESET", producer=2))
        self.assertEqual(reset.status, "REJECTED_TRANSPORT")
        self.assertTrue(txn.poisoned)
        later = txn.process(envelope(framed[cut:], producer=3))
        self.assertEqual(later.status, "REJECTED_POISONED")
        self.assertEqual(len(admission.seen), 1)

    def test_gap_on_empty_decoder_context_still_fences_generation(self):
        txn, _adapter, admission = self.transaction()
        gap = txn.process(envelope(b"", continuity="GAP_BEFORE", producer=1))
        self.assertEqual(gap.status, "REJECTED_TRANSPORT")
        self.assertTrue(txn.poisoned)

        later = txn.process(envelope(framed_any("jtk", JTK), producer=2))
        self.assertEqual(later.status, "REJECTED_POISONED")
        self.assertEqual(admission.seen, [])

    def test_complete_after_transport_break_returns_poisoned_without_decoding(self):
        txn, adapter, admission = self.transaction()
        before = adapter.checkpoint_runtime_context()
        self.assertEqual(
            txn.process(envelope(b"", continuity="UNKNOWN", producer=1)).status,
            "REJECTED_TRANSPORT",
        )
        after_break = adapter.checkpoint_runtime_context()
        self.assertEqual(before.digest, after_break.digest)

        result = txn.process(envelope(framed_any("jtk", JTK), producer=2))
        self.assertEqual(result.status, "REJECTED_POISONED")
        self.assertEqual(after_break.digest, adapter.checkpoint_runtime_context().digest)
        self.assertEqual(admission.seen, [])

    def test_fresh_connection_generation_operates_after_old_generation_poison(self):
        old_txn, _old_adapter, old_admission = self.transaction()
        self.assertEqual(
            old_txn.process(envelope(b"", continuity="RESET", producer=1)).status,
            "REJECTED_TRANSPORT",
        )
        self.assertTrue(old_txn.poisoned)
        self.assertEqual(old_admission.seen, [])

        fresh_txn, _fresh_adapter, fresh_admission = self.transaction(
            generation=2, connection="conn-agent02-fresh"
        )
        result = fresh_txn.process(
            envelope(
                framed_any("jtk", JTK),
                producer=1,
                connection="conn-agent02-fresh",
                generation=2,
            )
        )
        self.assertEqual(result.status, "COMMITTED")
        self.assertEqual(result.batch.decode_health, "SEMANTIC_CANDIDATES")
        self.assertTrue(result.batch.candidates)
        self.assertEqual(len(fresh_admission.seen), 1)

    def test_no_admitted_semantic_batch_can_span_pre_gap_and_post_gap_bytes(self):
        txn, _adapter, admission = self.transaction()
        framed = framed_any("jtk", JTK)
        cut = max(2, len(framed) // 2)

        prefix = txn.process(envelope(framed[:cut], producer=1))
        self.assertEqual(prefix.batch.decode_health, "FRAMING_IN_PROGRESS")
        self.assertEqual(prefix.batch.candidates, ())
        txn.process(envelope(b"", continuity="GAP_INSIDE", producer=2))
        suffix = txn.process(envelope(framed[cut:], producer=3))

        self.assertEqual(suffix.status, "REJECTED_POISONED")
        self.assertEqual(len(admission.seen), 1)
        self.assertTrue(all(not batch.candidates for batch in admission.seen))

    def test_same_poll_overlap_conflict_prevents_semantic_commit(self):
        flow = "flow-agent02-poll-protocol"
        frame = framed_any("jtk", JTK)
        conflict = bytes([frame[0] ^ 1]) + frame[1:]
        assembler = TransportEnvelopeAssembler(
            capture_session_id="capture-agent02-protocol",
            flow_clients={flow: "client-cra"},
        )

        def captured(seq, payload=b"", *, packet, flags=0x18):
            return CapturedTcpSegment(
                flow,
                "server_to_client",
                seq,
                payload,
                packet,
                flags,
                f"2026-10-25T20:00:{packet:02d}+00:00",
                20_000 + packet,
                "TEST_FIXTURE",
            )

        returned = assembler.consume_poll(CapturePoll(
            "source-agent02-poll-protocol",
            (
                captured(100, packet=1, flags=0x02),
                captured(101, frame, packet=2),
                captured(101, conflict, packet=3),
            ),
            0,
            False,
            False,
            "AVAILABLE_CLEAN",
        ))

        self.assertEqual(assembler.health().status, "UNCERTAIN")
        self.assertTrue(returned)
        self.assertTrue(all(
            env.continuity not in ("COMPLETE", "CONTIGUOUS", "RECONNECTED")
            for env in returned
        ))

        first = returned[0]
        txn, _adapter, admission = self.transaction(
            generation=first.connection_generation,
            connection=first.connection_id,
        )
        results = [txn.process(env) for env in returned]

        self.assertTrue(txn.poisoned)
        self.assertTrue(all(result.status != "COMMITTED" for result in results))
        self.assertEqual(admission.seen, [])

    def test_unknown_wire_fences_entire_historical_adapter_batch(self):
        d = historical_descriptor()
        adapter = Historical371010Adapter(
            descriptor=d,
            account_id="acct-cra",
            client_instance_id="client-cra",
            connection_id="conn-agent02-protocol",
            connection_generation=1,
            opaque_policy=OpaquePolicy(),
        )
        batch = adapter.decode_envelope(envelope(framed_any("future_unknown", b"\x08\x01")))
        self.assertEqual(batch.decode_health, "UNKNOWN_CRITICAL")
        self.assertEqual(batch.candidates, ())
        self.assertEqual(len(batch.unknown_fingerprints), 1)
        self.assertIn("UNKNOWN_OR_UNPROVEN_WIRE", batch.failure_codes)

    def test_wrong_direction_known_semantic_is_quarantined_not_relabelled(self):
        d = historical_descriptor()
        adapter = Historical371010Adapter(
            descriptor=d,
            account_id="acct-cra",
            client_instance_id="client-cra",
            connection_id="conn-agent02-protocol",
            connection_generation=1,
        )
        # jtk is a known historical server->client semantic message. A
        # client->server occurrence must not be accepted as the same meaning.
        body = bytes.fromhex("0a1b221110010a0d080b10feffffffffffffffff01220610170a020805108906")
        batch = adapter.decode_envelope(
            envelope(framed_any("jtk", body), direction="client_to_server")
        )
        self.assertEqual(batch.decode_health, "UNKNOWN_CRITICAL")
        self.assertEqual(batch.candidates, ())


if __name__ == "__main__":
    unittest.main()
