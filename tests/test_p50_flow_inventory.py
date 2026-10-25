"""P50 privacy-preserving flow selection on synthetic PCAPNG bytes."""
from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from tests.capture_fixtures import packet, pcapng
from anka_capture.pcapng import read_pcapng_tcp_segments
from anka_contracts.historical_lifecycle import LegacyFightScope
from anka_protocol.adapters.historical_lifecycle import BUILD
from anka_app.historical_pcapng_inventory import (
    PcapngFlowInventory, FlowCandidate, inspect_pcapng_flow_inventory,
    replay_inventoried_pcapng_flow,
)

ROOT = Path(__file__).resolve().parents[1]


def var(n):
    value = bytearray()
    while n > 127:
        value.append(n & 127 | 128)
        n >>= 7
    return bytes(value + bytes([n]))


def field(num, data):
    return var(num << 3 | 2) + var(len(data)) + data


def frame(name, body):
    raw = field(1, ('type.ankama.com/' + name).encode()) + field(2, body)
    return var(len(raw)) + raw


class P50FlowInventory(TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'multiple-flows.pcapng'
        self.wire1 = frame('jvj', var(3 << 3) + var(33)) + frame('jup', var(2 << 3) + var(33))
        self.wire2 = frame('jvj', var(3 << 3) + var(44)) + frame('jup', var(2 << 3) + var(44))
        self.first = (
            packet(seq=100, flags=2, data=b'', reverse=True),
            packet(seq=500, flags=2, data=b'', sport=40401, dport=55001),
            packet(seq=101, flags=0x18, data=self.wire1, reverse=True),
            packet(seq=501, flags=0x18, data=self.wire2, sport=40401, dport=55001),
        )
        self.path.write_bytes(pcapng(*self.first))
        self.segments = read_pcapng_tcp_segments(self.path, server_ports={40400,40401})
        self.digest1 = hashlib.sha256(self.segments[0].flow_id.encode()).hexdigest()
        self.digest2 = hashlib.sha256(self.segments[1].flow_id.encode()).hexdigest()

    def inventory(self):
        return inspect_pcapng_flow_inventory(self.path, ports=(40400,40401))

    def scope(self, digest=None):
        return LegacyFightScope(42, digest or self.digest1, 1, BUILD)

    def test_two_flow_inventory_preserves_packet_order_and_direction(self):
        result = self.inventory()
        self.assertEqual((result.status, result.reason), ('CANDIDATES_ONLY','P50_ACCOUNT_IDENTITY_UNVERIFIED'))
        self.assertEqual((result.packet_records, result.selected_segments), (4,4))
        self.assertEqual([c.flow_digest for c in result.flows],[self.digest1,self.digest2])
        self.assertEqual([(c.first_packet_number,c.last_packet_number) for c in result.flows], [(1,3),(2,4)])
        self.assertEqual([(c.server_segments,c.client_segments) for c in result.flows], [(2,0),(2,0)])
        self.assertEqual([c.server_payload_segments for c in result.flows], [1,1])
        self.assertEqual([c.server_syn_seen for c in result.flows], [True,True])
        self.assertTrue(all(c.transport_status=='OBSERVED_NO_DETECTED_GAPS' for c in result.flows))
        self.assertFalse(result.account_binding_verified)
        self.assertFalse(result.current_client_certified)
        self.assertFalse(result.actionable)
        self.assertEqual(result.canonical_commits,0)
        self.assertNotIn('192.0.2.',repr(result))
        self.assertNotIn(str(self.path),repr(result))
        self.assertNotIn('type.ankama.com',repr(result))

    def test_inventoried_first_flow_replays_only_its_research_events(self):
        result = replay_inventoried_pcapng_flow(self.path, root=ROOT,
             ports=(40400,40401), inventory=self.inventory(), scope=self.scope())
        self.assertEqual((result.status,result.reason),('BLOCKED_EVIDENCE','P50_RESEARCH_ONLY'))
        self.assertEqual(result.research.observed_historical_events,2)
        self.assertEqual(result.research.transport_research.foreign_server_messages,2)
        self.assertEqual(result.research.transport_research.selected_server_messages,2)
        self.assertEqual([e.actor_id for e in result.research.transport_research.replay.observations],[33,33])
        self.assertFalse(result.account_binding_verified)
        self.assertEqual(result.canonical_commits,0)
        self.assertFalse(result.physical_input_sent)

    def test_second_flow_remains_independently_selected(self):
        result = replay_inventoried_pcapng_flow(self.path, root=ROOT,
             ports=(40400,40401), inventory=self.inventory(), scope=self.scope(self.digest2))
        self.assertEqual(result.reason,'P50_RESEARCH_ONLY')
        self.assertEqual([e.actor_id for e in result.research.transport_research.replay.observations],[44,44])

    def test_invalid_or_external_flow_is_rejected(self):
        inventory = self.inventory()
        with self.subTest('foreign flow'):
            res=replay_inventoried_pcapng_flow(self.path,root=ROOT,ports=(40400,40401),
                 inventory=inventory,scope=self.scope('a'*64))
            self.assertEqual(res.reason,'P50_FLOW_NOT_IN_INVENTORY')
            self.assertIsNone(res.research)
        with self.subTest('no inventory'):
            res=replay_inventoried_pcapng_flow(self.path,root=ROOT,ports=(40400,40401),
                 inventory=None,scope=self.scope())
            self.assertEqual(res.reason,'P50_INVENTORY_REQUIRED')

    def test_capture_replacement_after_inventory_rejected(self):
        inventory=self.inventory()
        self.path.write_bytes(pcapng(self.first[0],self.first[2]))
        result=replay_inventoried_pcapng_flow(self.path,root=ROOT,ports=(40400,40401),
            inventory=inventory,scope=self.scope())
        self.assertEqual(result.reason,'P50_INVENTORY_SOURCE_CHANGED')
        self.assertIsNone(result.research)

    def test_capture_corruption_and_wrong_ports(self):
        self.path.write_bytes(b'invalid')
        self.assertEqual(self.inventory().reason,'P50_PCAPNG_REJECTED')
        self.assertEqual(inspect_pcapng_flow_inventory(self.path,ports=()).reason,'P50_PORTS_INVALID')

    def test_no_selected_flow_is_explicit(self):
        report=inspect_pcapng_flow_inventory(self.path,ports=(1,))
        self.assertEqual((report.status,report.reason),('BLOCKED_EVIDENCE','P50_NO_SELECTED_FLOW'))
        self.assertEqual(report.flows,())

    def test_missing_syn_does_not_fake_completeness(self):
        self.path.write_bytes(pcapng(self.first[2],self.first[3]))
        report=self.inventory()
        self.assertTrue(all(not c.server_syn_seen for c in report.flows))
        self.assertTrue(all(c.transport_status=='TRANSPORT_UNCERTAIN' for c in report.flows))
        self.assertFalse(report.source_completeness_verified)

    def test_bidirectional_packet_count_and_fin_flags(self):
        self.path.write_bytes(pcapng(packet(101,flags=2,data=b''),
             packet(300,flags=2,data=b'',reverse=True),
             packet(102,flags=0x18,data=b'hello'),
             packet(301,flags=0x11,data=b'',reverse=True)))
        one=inspect_pcapng_flow_inventory(self.path,ports=(40400,)).flows[0]
        self.assertEqual((one.client_segments,one.server_segments),(2,2))
        self.assertTrue(one.client_syn_seen)
        self.assertTrue(one.server_syn_seen)
        self.assertTrue(one.fin_or_reset_seen)

    def test_too_many_candidate_flows_fails_closed(self):
        # The flow grouping receives a real parse; isolate the candidate ceiling.
        import anka_app.historical_pcapng_inventory as api
        with mock.patch.object(api,'MAX_DISCOVERED_FLOWS',1):
            self.assertEqual(self.inventory().reason,'P50_FLOW_LIMIT')

    def test_fabricated_candidate_is_not_a_signed_identity_witness(self):
        original=self.inventory()
        foreign=replace(original.flows[0],flow_digest='a'*64)
        forged=replace(original,flows=(foreign, original.flows[1]))
        result=replay_inventoried_pcapng_flow(self.path,root=ROOT,ports=(40400,40401),
            inventory=forged,scope=self.scope('a'*64))
        self.assertEqual(result.reason,'P50_INVENTORY_FLOWS_UNVERIFIED')
        self.assertIsNone(result.research)

    def test_fabricated_packet_boundaries_are_not_trusted(self):
        original=self.inventory()
        invented=replace(original.flows[0],last_packet_number=4)
        forged=replace(original,flows=(invented,original.flows[1]))
        result=replay_inventoried_pcapng_flow(self.path,root=ROOT,ports=(40400,40401),
            inventory=forged,scope=self.scope())
        self.assertEqual(result.reason,'P50_INVENTORY_FLOWS_UNVERIFIED')

    def test_replay_wrong_build_never_grants_authority(self):
        research=replay_inventoried_pcapng_flow(self.path,root=ROOT,ports=(40400,40401),
            inventory=self.inventory(),scope=replace(self.scope(),protocol_build='wrong-build'))
        self.assertEqual(research.reason,'P50_RESEARCH_ONLY')
        self.assertEqual(research.research.observed_historical_events,0)
        self.assertFalse(research.research.current_client_certified)

    def test_malformed_candidate_and_report_shapes_are_rejected(self):
        original=self.inventory()
        with self.assertRaises(ValueError):
            replace(original.flows[0], server_segments=-1)
        with self.assertRaises(ValueError):
            replace(original, flows=(original.flows[0],original.flows[0]))
        with self.assertRaises(ValueError):
            replace(original, reason='P50_WRONG')

    def test_inconsistent_replay_receipt_stays_blocked(self):
        import anka_app.historical_pcapng_inventory as api
        inventory=self.inventory()
        real=api.inspect_historical_pcapng(self.path,root=ROOT,ports=(40400,40401),scope=self.scope())
        with mock.patch.object(api, 'inspect_historical_pcapng', return_value=replace(real,packet_records=1)):
            # Never trust a wrapper's advertised packet count: compare its
            # capture receipt, which is derived from the P4 inspection.
            outcome=replay_inventoried_pcapng_flow(self.path,root=ROOT,ports=(40400,40401),
                inventory=inventory,scope=self.scope())
            self.assertEqual(outcome.reason,'P50_RESEARCH_ONLY')
            self.assertFalse(outcome.actionable)
