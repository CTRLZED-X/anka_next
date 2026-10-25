"""Agent 02 protocol-evolution and consumer-impact regressions.

The suite pins fail-closed properties needed for frequent protocol replacement.
It does not grant current-build, live, Canonical, or physical-input authority.
"""
from __future__ import annotations

import unittest

from anka_contracts.protocol import AdapterReleaseDescriptor
from anka_protocol.adapters.dofus_3_7_10_10.adapter import Historical371010Adapter
from anka_protocol.adapters.dofus_3_7_10_10.manifest import descriptor as historical_descriptor
from anka_protocol.certification.impact import semantic_impact_report
from anka_protocol.registry import (
    ProtocolActivationRejected,
    ProtocolAdapterNotFound,
    ProtocolRegistry,
)
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


def envelope(payload: bytes, *, direction: str = "server_to_client") -> WireEnvelope:
    return WireEnvelope(
        "capture-agent02-protocol",
        "client-cra",
        "conn-agent02-protocol",
        direction,
        0,
        1,
        "2026-10-25T14:00:00+00:00",
        1,
        payload,
        "COMPLETE",
        len(payload),
        1,
        1,
        "TEST_FIXTURE",
    )


class DummyAdapter:
    def __init__(self, descriptor: AdapterReleaseDescriptor):
        self.descriptor = descriptor


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
