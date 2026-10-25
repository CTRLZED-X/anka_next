"""P49: saved PCAPNG can inform research but cannot attest capture loss or accounts."""
from __future__ import annotations
import hashlib
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest import TestCase, mock

from tests.capture_fixtures import packet, pcapng
from anka_contracts.capture import CapturePoll, CapturedTcpSegment
from anka_contracts.historical_lifecycle import LegacyFightScope
from anka_protocol.adapters.historical_lifecycle import BUILD
from anka_capture.pcapng import read_pcapng_tcp_segments
from anka_app.historical_pcapng_bridge import inspect_historical_pcapng
from anka_app.historical_transport_bridge import replay_historical_capture_polls

ROOT = Path(__file__).resolve().parents[1]


def var(n):
    out=[]
    while n >= 128:
        out.append((n & 127) | 128)
        n >>= 7
    return bytes(out + [n])


def field(n, data):
    return var(n << 3 | 2) + var(len(data)) + data


def msg(name, body):
    env=field(1, ('type.ankama.com/' + name).encode()) + field(2, body)
    return var(len(env)) + env


class P49PcapngResearch(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'forensic.pcapng'
        self.wire=(msg('jvj', var(3 << 3) + var(33)) +
                   msg('jup', var(2 << 3) + var(33)) + msg('jwp', b''))
        self.original=pcapng(packet(100, flags=2, data=b'', reverse=True),
            packet(101, flags=0x18, data=self.wire, reverse=True))
        self.path.write_bytes(self.original)
        segment=read_pcapng_tcp_segments(self.path, server_ports={40400})[0]
        self.scope=LegacyFightScope(42, hashlib.sha256(segment.flow_id.encode()).hexdigest(), 1, BUILD)

    def inspect(self, scope=None):
        return inspect_historical_pcapng(self.path, root=ROOT,
            ports=(40400,), scope=scope or self.scope)

    def test_complete_synthetic_pcap_is_only_a_forensic_observation(self):
        r=self.inspect()
        self.assertEqual((r.status,r.reason),('BLOCKED_EVIDENCE','P49_DRIVER_LOSS_AND_ACCOUNT_PROOF_MISSING'))
        self.assertEqual((r.packet_records,r.observed_historical_events),(2,3))
        self.assertEqual([x.kind for x in r.transport_research.replay.observations],
            ['TURN_OWNER_OBSERVED','TURN_END_OBSERVED','FIGHT_RESULT_BOUNDARY_OBSERVED'])
        self.assertEqual(r.transport_research.blocking_issue,'P48_CAPTURE_LOSS_OR_DRIVER_VISIBILITY_UNKNOWN')
        self.assertEqual(r.transport_research.protocol_status,'INCOMPLETE_EVIDENCE_OBSERVATION_ONLY')
        self.assertFalse(r.actionable)
        self.assertFalse(r.current_client_certified)
        self.assertFalse(r.source_completeness_verified)
        self.assertFalse(r.account_binding_verified)
        self.assertFalse(r.physical_input_sent)
        self.assertEqual(r.canonical_commits,0)
        self.assertNotIn('192.0.2.',repr(r))
        self.assertNotIn('type.ankama.com',repr(r))

    def test_wrong_flow_does_not_manufacture_player_observations(self):
        wrong=replace(self.scope,flow_digest='b'*64)
        r=self.inspect(wrong)
        self.assertEqual((r.reason,r.observed_historical_events),('P49_NO_SELECTED_FLOW_PROOF',0))
        self.assertFalse(r.transport_research.account_binding_verified)

    def test_wrong_build_remains_unqualified(self):
        r=self.inspect(replace(self.scope,protocol_build='Dofus 3.7.11.11'))
        self.assertEqual(r.status,'BLOCKED_EVIDENCE')
        self.assertEqual(r.observed_historical_events,0)
        self.assertFalse(r.current_client_certified)

    def test_unknown_wire_is_visible_as_a_semantic_gap(self):
        wire=self.wire+msg('unmappedP49',b'\x08\x01')
        self.path.write_bytes(pcapng(packet(100,flags=2,data=b'',reverse=True),packet(101,flags=0x18,data=wire,reverse=True)))
        r=self.inspect()
        self.assertEqual(r.status,'BLOCKED_EVIDENCE')
        self.assertEqual(r.transport_research.replay.unmapped_wire_messages,1)
        self.assertEqual(r.observed_historical_events,3)

    def test_truncated_capture_returns_typed_failure_without_payload_or_path(self):
        self.path.write_bytes(self.original[:-11])
        r=self.inspect()
        self.assertEqual((r.status,r.reason,r.observed_historical_events),('BLOCKED_EVIDENCE','P49_PCAPNG_REJECTED',0))
        self.assertNotIn(str(self.path),repr(r))

    def test_changed_capture_between_inspection_and_replay_is_rejected(self):
        from anka_app import historical_pcapng_bridge as bridge
        original_inspect=bridge.inspect_pcapng
        def replace_after_inspect(*a,**kw):
            result=original_inspect(*a,**kw)
            self.path.write_bytes(self.original+b'\x00')
            return result
        with mock.patch.object(bridge,'inspect_pcapng',side_effect=replace_after_inspect):
            r=self.inspect()
        self.assertEqual((r.reason,r.observed_historical_events),('P49_CAPTURE_CHANGED',0))

    def test_wrong_ports_and_missing_scope_fail_closed(self):
        r=inspect_historical_pcapng(self.path, root=ROOT, ports=(), scope=self.scope)
        self.assertEqual(r.reason,'P49_PORTS_INVALID')
        r=inspect_historical_pcapng(self.path, root=ROOT, ports=(40400,), scope=None)
        self.assertEqual(r.reason,'P49_SCOPE_UNVERIFIED')

    def test_no_selected_packet_stays_blocked(self):
        r=inspect_historical_pcapng(self.path, root=ROOT, ports=(9999,), scope=self.scope)
        self.assertEqual((r.status,r.observed_historical_events),('BLOCKED_EVIDENCE',0))

    def test_forensic_mode_does_not_allow_explicit_dropped_or_overflowed(self):
        segment=CapturedTcpSegment('some_flow','server_to_client',100,b'',1,2)
        body=CapturedTcpSegment('some_flow','server_to_client',101,self.wire,2)
        scope=replace(self.scope, flow_digest=hashlib.sha256(b'some_flow').hexdigest())
        for dropped,overflowed in ((1,False),(0,True)):
            with self.subTest(dropped=dropped,overflowed=overflowed):
                poll=CapturePoll('gen',(segment,body),dropped,overflowed,True,'UNKNOWN')
                r=replay_historical_capture_polls((poll,),scope=scope,root=ROOT,
                    forensic_without_driver_proof=True)
                self.assertEqual(r.status,'BLOCKED_EVIDENCE')
                self.assertEqual(r.selected_server_messages,0)
                self.assertEqual(r.canonical_commits,0)

    def test_normal_p48_replay_does_not_assume_forensic_mode(self):
        first=CapturedTcpSegment('some_flow','server_to_client',100,b'',1,2)
        body=CapturedTcpSegment('some_flow','server_to_client',101,self.wire,2)
        scope=replace(self.scope,flow_digest=hashlib.sha256(b'some_flow').hexdigest())
        poll=CapturePoll('gen',(first,body),0,False,True,'UNKNOWN')
        r=replay_historical_capture_polls((poll,),scope=scope,root=ROOT)
        self.assertEqual(r.status,'BLOCKED_EVIDENCE')
        self.assertEqual(r.selected_server_messages,0)

    def test_malformed_selected_packet_cannot_become_valid_wire(self):
        self.path.write_bytes(pcapng(packet(100,flags=2,data=b'',reverse=True),
             packet(101,flags=0x18,data=var(1)+b'\xff',reverse=True)))
        r=self.inspect()
        self.assertEqual(r.status,'BLOCKED_EVIDENCE')
        self.assertEqual(r.observed_historical_events,0)
        self.assertNotEqual(r.transport_research.protocol_status,'HISTORICAL_WIRE_OBSERVATION_ONLY')
