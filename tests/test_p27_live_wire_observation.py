"""P27: real capture-to-Protocol boundary, privacy, loss, and fail-closed checks."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anka_app.cli import ROOT
from anka_app.configuration import load_user_config
from anka_app.ingress_readiness import _safe_receipt, _windows_sample, probe_start_ingress
from anka_capture.windows_live import capture_bounded_sample
from anka_contracts.capture import CapturePoll, CapturedTcpSegment
from anka_observability.api import LocalDiagnostics
from anka_observability.bundle import verify_incident
from anka_protocol.wire import FrameBuffer
from anka_protocol.adapters.historical import load_reference
from anka_protocol.api import ProtocolInspector

CFG = load_user_config(ROOT/'config/user.json')


def v(num: int) -> bytes:
    out = []
    while num >= 128:
        out.append((num & 127) | 128)
        num >>= 7
    return bytes(out + [num])


def fld(index: int, raw: bytes) -> bytes:
    return v(index * 8 + 2) + v(len(raw)) + raw


def frame(name='unknown_observed_type_P27') -> bytes:
    body = fld(1, b'type.ankama.com/' + name.encode()) + fld(2, b'\x08\x02')
    return v(len(body)) + body


def segment_pack(name='unknown_observed_type_P27', *, gap=False):
    payload = frame(name)
    return (CapturedTcpSegment('secret-flow-id', 'server_to_client', 100, b'', 1, 2),
            CapturedTcpSegment('secret-flow-id', 'server_to_client', 102 if gap else 101,
                               payload, 2))


def fake_polled_sample(name='unknown_observed_type_P27', *, gap=False, source='G1', lost=0):
    return CapturePoll(source, segment_pack(name, gap=gap), lost, lost != 0, False, 'UNKNOWN')


class SampleSource:
    """Fake Scapy source: only CapturePoll port, no Windows backend or physical input."""
    def __init__(self, polls):
        self.polls = list(polls)
        self.closed = False
        self.started = False
        self.stops = 0
    def start(self): self.started = True
    def poll(self, *, max_segments, timeout_seconds):
        if self.polls:
            return self.polls.pop(0)
        return CapturePoll('G1', (), 0, False, True, 'UNKNOWN')
    def stop(self): self.closed = True; self.stops += 1
    def safe_stats(self):
        return {'accepted_segments':2, 'queued_segments':0, 'queue_drop_total':0,
                'invalid_frames':0, 'rejected_frames':0, 'unsupported_frames':0}


class P27Tests(unittest.TestCase):
    def test_capture_sample_delivers_actual_poll_to_protocol_consumer(self):
        inspector = ProtocolInspector(load_reference(ROOT), requested_build='UNVERIFIED_CURRENT_CLIENT')
        source = SampleSource([fake_polled_sample()])
        # A fake clock advances after the first poll, avoiding real 1-second delay.
        with patch('anka_capture.windows_live.monotonic_ns', side_effect=[0, 0, 0, 2_000_000_000]):
            receipt = capture_bounded_sample(interface='mock', server_ports=(40400,),
                duration_seconds=1, source=source, on_poll=inspector.consume_poll)
        wire = inspector.finish()
        self.assertEqual(receipt['selected_segments'], 2)
        self.assertEqual(wire.selected_segments, 2)
        self.assertEqual(wire.framed_messages, 1)
        self.assertEqual(wire.unknown_messages, 1)
        self.assertTrue(wire.packet_loss_reported)  # Driver visibility UNKNOWN
        self.assertEqual(wire.canonical_events_emitted, 0)
        self.assertTrue(source.closed)

    def test_callback_exception_closes_live_source(self):
        source = SampleSource([fake_polled_sample()])
        def fail(_): raise RuntimeError('secret IP: 198.51.100.4')
        with patch('anka_capture.windows_live.monotonic_ns', side_effect=[0, 0, 0, 2_000_000_000]):
            with self.assertRaises(RuntimeError):
                capture_bounded_sample(interface='mock', server_ports=(40400,),
                    duration_seconds=1, source=source, on_poll=fail)
        self.assertTrue(source.closed)

    def test_unknown_and_known_are_historical_comparisons_not_certificates(self):
        catalog = load_reference(ROOT)
        name,direction=next(iter(catalog.known_keys))
        s1 = 'server_to_client' if direction == 'server_to_client' else 'client_to_server'
        for n,expected in ((name,1), ('unknown_observed_type_P27',0)):
            with self.subTest(name=n):
                inspector = ProtocolInspector(catalog, requested_build='UNVERIFIED_CURRENT_CLIENT')
                segments = segment_pack(n)
                if s1 != 'server_to_client':
                    segments = tuple(CapturedTcpSegment(s.flow_id,s1,s.seq,s.payload,s.packet_number,s.tcp_flags)
                                     for s in segments)
                inspector.consume_poll(CapturePoll('G1',segments,0,False,True,'UNKNOWN'))
                r=inspector.finish()
                self.assertEqual(r.classified_observations,expected if n==name else 0)
                self.assertEqual(r.status, 'UNSUPPORTED_BUILD_OBSERVATION_ONLY')
                self.assertFalse(r.gameplay_capabilities_certified)

    def test_gap_quarantines_not_certifies(self):
        inspector=ProtocolInspector(load_reference(ROOT),requested_build='UNVERIFIED_CURRENT_CLIENT')
        inspector.consume_poll(fake_polled_sample(gap=True))
        r=inspector.finish()
        self.assertGreater(r.quarantined_streams,0)
        self.assertEqual(r.framed_messages,0)

    def test_loss_and_stream_reset_do_not_prove_framing(self):
        inspector=ProtocolInspector(load_reference(ROOT),requested_build='UNVERIFIED_CURRENT_CLIENT')
        inspector.consume_poll(fake_polled_sample(lost=1))
        inspector.consume_poll(CapturePoll('G2', (), 0,False,True,'UNKNOWN'))
        self.assertTrue(inspector.finish().packet_loss_reported)

    def test_outgoing_receipt_privacy_and_uncertified_defaults(self):
        raw={ 'status':'UNCERTIFIED', 'selected_segments':2, 'queue_dropped':0,
              'invalid_frames':0,'rejected_frames':0,'unsupported_frames':0,
              'transport':{'unanchored_directions':0,'unresolved_gap_directions':0,
                           'observed_generations':1,'reconnections':0,'duplicate_segments':0,
                           'reordered_segments':0,'metadata_limit_reached':False,
                           'packet_order_uncertain':False},
              'protocol_wire': {'status':'UNSUPPORTED_BUILD_OBSERVATION_ONLY',
                    'selected_segments':2,'framed_messages':1,'classified_observations':0,
                    'unknown_messages':1,'direction_mismatches':0,'invalid_frames':0,
                    'quarantined_streams':0,'unanchored_streams':0,'packet_loss_reported':True,
                    'findings':[{'name':'private-content','payload':'SECRET'}],
                    'live_certified':True,'physical_input_permitted':True},
              'payload': b'SECRET', 'ip':'203.0.113.3'}
        safe = _safe_receipt(raw)
        self.assertEqual(safe['protocol_wire']['unknown_messages'],1)
        self.assertFalse(safe['protocol_wire']['current_build_certified'])
        self.assertFalse(safe['protocol_wire']['physical_input_permitted'])
        serialized=json.dumps(safe)
        for secret in ('SECRET','203.0.113.3','private-content','payload','findings'):
            self.assertNotIn(secret,serialized)

    def test_forged_wire_certification_fails_closed(self):
        raw={'status':'UNSUPPORTED_BUILD_OBSERVATION_ONLY','selected_segments':2,
             'framed_messages':1,'classified_observations':0,'unknown_messages':1,
             'direction_mismatches':0,'invalid_frames':0,'quarantined_streams':0,
             'unanchored_streams':0,'packet_loss_reported':True}
        from anka_app.ingress_readiness import _safe_protocol_observation
        for changes in ({'status':'CURRENT_BUILD_CERTIFIED'}, {'selected_segments':3},
                        {'unknown_messages':2}, {'packet_loss_reported':False},
                        {'classified_observations':True}, {'framed_messages':-1}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    _safe_protocol_observation({**raw,**changes},2)

    def test_missing_callback_is_observable_not_certified(self):
        from anka_app.ingress_readiness import _safe_protocol_observation
        self.assertEqual(_safe_protocol_observation(None,6)['status'],'NOT_OBSERVED')

    def test_canonical_journal_stays_unmodified(self):
        inspector=ProtocolInspector(load_reference(ROOT),requested_build='UNVERIFIED_CURRENT_CLIENT')
        inspector.consume_poll(fake_polled_sample())
        self.assertEqual(inspector.finish().canonical_events_emitted,0)

    def test_safe_observation_can_be_exported_without_raw_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs=LocalDiagnostics(Path(tmp))
            from anka_app.ingress_readiness import _safe_protocol_observation
            values={'status':'UNSUPPORTED_BUILD_OBSERVATION_ONLY','selected_segments':2,
                 'framed_messages':1,'classified_observations':0,'unknown_messages':1,
                 'direction_mismatches':0,'invalid_frames':0,'quarantined_streams':0,
                 'unanchored_streams':0,'packet_loss_reported':True,'message_name':'PRIVATE'}
            obs.record('readiness.protocol_wire',payload=_safe_protocol_observation(values,2))
            path=obs.export_incident('LIVE_RUNTIME_NOT_IMPLEMENTED',boundary='readiness.read_only_capture')
            self.assertEqual(verify_incident(path)['status'],'PASS')
            from zipfile import ZipFile
            with ZipFile(path) as z:
                data=''.join(z.read(n).decode('utf8','replace') for n in z.namelist()
                             if n.endswith(('.json','.jsonl','.md')))
            self.assertNotIn('PRIVATE',data)
            self.assertIn('protocol_wire', data)


if __name__=='__main__': unittest.main()

class P27WindowsCompositionTests(unittest.TestCase):
    def _run_sample(self, segment_poll):
        from anka_app.ingress_readiness import _windows_sample
        from anka_contracts.client import WindowObservation, WindowScan
        from unittest.mock import patch
        from dataclasses import replace
        config = replace(CFG, capture=replace(CFG.capture, server_ports=(40400,), interface='mock', duration_seconds=1))
        # The definitive live sampler fences the TCP snapshot with two exact
        # process-generation scans (and checks the generation once more after
        # capture).  This retained P27 integration fixture therefore models two
        # stable Dofus generations rather than the obsolete empty/single-scan
        # inventory used before the M12_003 PID-reuse hardening.
        stable_windows=(
            WindowObservation(101,2001,9001,'Dofus.exe','Curseni - Dofus',1280,649,96,False,True,False,'3.7.11.11'),
            WindowObservation(102,2002,9002,'Dofus.exe','Sosoking - Dofus',1280,649,96,False,False,False,'3.7.11.11'),
        )
        class Inventory:
            def __init__(self, names):pass
            def scan(self):return WindowScan(1,stable_windows,())
        class Owner:
            def snapshot(self):return ()
        class Live:
            def __init__(self,**kw): pass
            def flow_keys_for_attribution(self):return {}
        def capture_sample(**kw):
            self.assertTrue(callable(kw['on_poll']))
            self.assertEqual(kw['duration_seconds'],1)
            kw['on_poll'](segment_poll)
            data={'status':'UNCERTIFIED','selected_segments':len(segment_poll.segments),
                'queue_dropped':segment_poll.dropped,'invalid_frames':0,'rejected_frames':0,
                'unsupported_frames':0,'transport':{
                   'unanchored_directions':0,'unresolved_gap_directions':0,
                   'observed_generations':1,'reconnections':0,'duplicate_segments':0,
                   'reordered_segments':0,'metadata_limit_reached':False,
                   'packet_order_uncertain':False}}
            if segment_poll.dropped:data['status']='LOSS_DETECTED'
            return data
        with patch('anka_client.win32_inventory.NativeWindowsInventory',Inventory),\
             patch('anka_capture.windows_flows.WindowsTcpOwnership',Owner),\
             patch('anka_capture.windows_live.WindowsLiveCapture',Live),\
             patch('anka_capture.windows_live.capture_bounded_sample',side_effect=capture_sample):
            return _windows_sample(config)

    def test_actual_windows_composition_in_memory_wire_summary(self):
        value=self._run_sample(fake_polled_sample())
        safe=_safe_receipt(value)
        self.assertEqual(safe['protocol_wire']['framed_messages'],1)
        self.assertEqual(safe['protocol_wire']['unknown_messages'],1)
        self.assertEqual(safe['protocol_wire']['status'],'OBSERVED_UNCERTIFIED')
        self.assertEqual(safe['protocol_wire']['canonical_events_emitted'],0)
        self.assertNotIn('secret-flow-id',json.dumps(safe))
        self.assertNotIn('unknown_observed_type_P27',json.dumps(safe))

    def test_actual_windows_composition_preserves_gap(self):
        safe=_safe_receipt(self._run_sample(fake_polled_sample(gap=True)))
        self.assertGreater(safe['protocol_wire']['quarantined_streams'],0)
        self.assertEqual(safe['protocol_wire']['framed_messages'],0)
        self.assertFalse(safe['protocol_wire']['current_build_certified'])

    def test_actual_windows_composition_never_certifies_queue_loss(self):
        safe=_safe_receipt(self._run_sample(fake_polled_sample(lost=2)))
        self.assertEqual(safe['queue_dropped'],2)
        self.assertEqual(safe['status'],'LOSS_DETECTED')
        self.assertTrue(safe['protocol_wire']['incomplete_capture_evidence'])

    def test_no_extra_user_facing_launchers(self):
        self.assertEqual({p.name for p in ROOT.glob('*.bat')},{'setup.bat','start.bat'})
