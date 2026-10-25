"""P64: falsifiable capture evidence path, no Windows or Scapy required."""
import os
import struct
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from anka_app.ingress_readiness import _safe_raw_evidence, _safe_receipt
from anka_capture.api import inspect_pcapng, CaptureRejected
from anka_capture.evidence_recording import (
    ConsentedPcapngRecorder, MAX_EVIDENCE_FRAMES, _selected_ipv4_tcp,
)
from anka_capture.pcapng import pcapng_packet_count
from anka_capture.windows_live import WindowsLiveCapture
from anka_app.configuration import load_user_config, ConfigurationError


def tcp_frame(*, payload=b'hello', sport=53000, dport=40400,
              protocol=6, fragmented=False, ethertype=b'\x08\x00'):
    ip = bytearray(20)
    ip[0] = 0x45
    ip[2:4] = (40+len(payload)).to_bytes(2, 'big')
    ip[6:8] = (0x2000 if fragmented else 0).to_bytes(2, 'big')
    ip[8] = 64
    ip[9] = protocol
    ip[12:16] = b'\xc0\x00\x02\x01'
    ip[16:20] = b'\xc6\x33\x64\x02'
    tcp = bytearray(20)
    tcp[0:4] = struct.pack('!HH', sport, dport)
    tcp[4:8] = (100).to_bytes(4, 'big')
    tcp[12] = 0x50
    tcp[13] = 0x18
    return bytes(12) + ethertype + bytes(ip) + bytes(tcp) + payload


class Recording(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def writer(self):
        return ConsentedPcapngRecorder(self.folder, server_ports=(40400,))

    def test_complete_saved_capture_round_trips_real_parser(self):
        w = self.writer()
        self.assertTrue(w.record(tcp_frame(payload=b'PROTO_MESSAGE'), captured_ns=1000000000))
        r = w.close()
        self.assertEqual(r['status'], 'RECORDED_UNCERTIFIED')
        self.assertEqual(r['frames'], 1)
        self.assertEqual(pcapng_packet_count(w.final_path), 1)
        receipt=inspect_pcapng(w.final_path, server_ports=(40400,))
        self.assertEqual(receipt.selected_segments, 1)
        self.assertFalse(receipt.live_capture_equivalent)
        self.assertFalse(receipt.protocol_decoded)
        self.assertEqual(receipt.source_sha256, r['sha256'])
        self.assertEqual(sha256(w.final_path.read_bytes()).hexdigest(), r['sha256'])
        self.assertEqual(w.close(), r)
        self.assertFalse(w.final_path.with_name(w.final_path.name+'.partial').exists())

    def test_known_gap_produces_real_pcapng_loss_metadata(self):
        w = self.writer()
        self.assertTrue(w.record(tcp_frame()))
        w.mark_incomplete()
        r = w.close()
        self.assertEqual(r['status'], 'INCOMPLETE_RECORDED')
        self.assertEqual(r['known_recording_gaps'], 1)
        with self.assertRaisesRegex(ValueError, 'reported lost packets'):
            pcapng_packet_count(w.final_path)
        with self.assertRaises(CaptureRejected):
            inspect_pcapng(w.final_path,server_ports=(40400,))

    def test_invalid_frames_never_persist(self):
        bad = (tcp_frame(dport=45000), tcp_frame(sport=40400),
               tcp_frame(protocol=17), tcp_frame(fragmented=True),
               tcp_frame(ethertype=b'\x86\xdd'), b'bad', tcp_frame()[:-8])
        for frame in bad:
            with self.subTest(reason=str(len(frame)) + ':' + repr(frame[12:14])):
                w = self.writer()
                self.assertFalse(w.record(frame))
                self.assertEqual(w.close()['status'], 'INCOMPLETE_RECORDED')
                with self.assertRaises(ValueError):
                    pcapng_packet_count(w.final_path)

    def test_frame_limit_fences_additional_records_and_reports_loss(self):
        w = self.writer()
        for i in range(MAX_EVIDENCE_FRAMES):
            self.assertTrue(w.record(tcp_frame(payload=b'')))
        self.assertFalse(w.record(tcp_frame()))
        r=w.close()
        self.assertEqual(r['frames'], MAX_EVIDENCE_FRAMES)
        self.assertEqual(r['known_recording_gaps'], 1)
        self.assertLess(w.final_path.stat().st_size, 8*1024*1024)
        with self.assertRaises(ValueError):
            pcapng_packet_count(w.final_path)

    def test_disk_write_failure_never_exposes_success(self):
        w = self.writer()
        with patch.object(w, '_write', side_effect=OSError('private disk name')):
            self.assertFalse(w.record(tcp_frame()))
        r=w.close()
        self.assertEqual(r['status'], 'INCOMPLETE_RECORDED')
        self.assertNotIn('private disk',str(r))

    def test_timestamp_validation_fails_closed(self):
        w = self.writer()
        for bad in (-1,2**64,1.25,True):
            self.assertFalse(w.record(tcp_frame(),captured_ns=bad))
        self.assertEqual(w.close()['known_recording_gaps'],4)

    def test_rejects_nonbytes_and_partial_ethernet_frames(self):
        self.assertFalse(_selected_ipv4_tcp('not bytes',(40400,)))
        self.assertFalse(_selected_ipv4_tcp(bytearray(tcp_frame()),(40400,)))
        self.assertFalse(_selected_ipv4_tcp(tcp_frame()[:22],(40400,)))

    def test_no_absolute_path_or_endpoint_in_public_receipt(self):
        w = self.writer()
        w.record(tcp_frame())
        receipt = _safe_raw_evidence(w.close())
        self.assertTrue(receipt['raw_capture_saved'])
        self.assertEqual(receipt['driver_loss_visibility'], 'UNKNOWN')
        self.assertNotIn(self.temp.name, str(receipt))
        self.assertNotIn('53000', str(receipt))
        self.assertNotIn('PROTO_MESSAGE', str(receipt))

    def test_forged_recording_receipts_refused(self):
        w=self.writer();w.record(tcp_frame()); base=w.close()
        for bad in ({**base,'sha256':'0'*8},
                    {**base,'driver_loss_visibility':'COMPLETE'},
                    {**base,'live_certified':True},
                    {**base,'physical_input_sent':True},
                    {**base,'known_recording_gaps':1}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):_safe_raw_evidence(bad)

    def test_disabled_default_public_receipt(self):
        self.assertEqual(_safe_raw_evidence(None)['status'], 'DISABLED')
        self.assertFalse(_safe_raw_evidence(None)['raw_capture_saved'])

    def test_output_file_restricted_on_non_windows(self):
        w=self.writer();w.record(tcp_frame());w.close()
        if os.name != 'nt':
            self.assertEqual(w.final_path.stat().st_mode & 0o777,0o600)

    def test_start_failure_seals_partial_as_incomplete(self):
        w=self.writer()
        def fail(**_):raise OSError('private windows capture device')
        src=WindowsLiveCapture(interface='fake',server_ports=(40400,),require_windows=False,
                               sniffer_factory=fail,evidence_recorder=w)
        with self.assertRaisesRegex(RuntimeError,'LIVE_CAPTURE_START_FAILED'):src.start()
        self.assertTrue(w.final_path.exists())
        self.assertEqual(w.close()['status'],'INCOMPLETE_RECORDED')


class Consent(unittest.TestCase):
    def test_real_project_default_is_off(self):
        from anka_app.cli import ROOT
        c=load_user_config(ROOT/'config/user.json')
        self.assertFalse(c.capture.save_raw_evidence)

    def test_opt_in_json_boolean_only(self):
        import json
        from anka_app.cli import ROOT
        original=json.loads((ROOT/'config/user.json').read_text('utf8'))
        original.setdefault('capture',{})
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'user.json'
            for value in ('true',1,[],None):
                original['capture']['save_raw_evidence']=value
                path.write_text(json.dumps(original))
                with self.assertRaises(ConfigurationError):load_user_config(path)
            original['capture']['save_raw_evidence']=True
            path.write_text(json.dumps(original))
            self.assertTrue(load_user_config(path).capture.save_raw_evidence)
            original['capture']['save_raw_evidence']=False
            path.write_text(json.dumps(original))
            self.assertFalse(load_user_config(path).capture.save_raw_evidence)

    def test_read_only_source_stats_do_not_show_evidence_path(self):
        from anka_app.ingress_readiness import _safe_raw_evidence
        self.assertEqual(_safe_raw_evidence(None)['raw_capture_saved'],False)

class PassiveCallback(unittest.TestCase):
    """Mock Scapy import/packet so callback is tested without installed Npcap."""
    def test_packet_callback_records_exact_selected_frame(self):
        import sys
        import types
        from unittest.mock import patch
        from anka_capture.windows_live import WindowsLiveCapture

        class IP:pass
        class TCP:pass
        class Ether:pass
        frame=tcp_frame(payload=b'LIVE_WIRE_BYTES')
        class FakeIp:
            src='192.0.2.1'
            dst='198.51.100.2'
            def __bytes__(self):return frame[14:]
        class FakeTcp:
            sport=53000; dport=40400; seq=100; flags=24
            payload=b'LIVE_WIRE_BYTES'
        class Packet:
            def haslayer(self, layer):return layer in (IP,TCP,Ether)
            def __getitem__(self, layer):
                if layer is IP:return FakeIp()
                if layer is TCP:return FakeTcp()
                if layer is Ether:return self
                raise KeyError(layer)
            def __bytes__(self):return frame
        inet=types.ModuleType('scapy.layers.inet');inet.IP=IP;inet.TCP=TCP
        l2=types.ModuleType('scapy.layers.l2');l2.Ether=Ether
        layers=types.ModuleType('scapy.layers'); layers.inet=inet;layers.l2=l2
        scapy=types.ModuleType('scapy');scapy.layers=layers
        with patch.dict(sys.modules, {'scapy':scapy,'scapy.layers':layers,
                                      'scapy.layers.inet':inet,'scapy.layers.l2':l2}):
            with tempfile.TemporaryDirectory() as folder:
                w=ConsentedPcapngRecorder(Path(folder), server_ports=(40400,))
                class StubSniffer:
                    def __init__(self,**kwargs):pass
                    def start(self):pass
                    def stop(self):pass
                src=WindowsLiveCapture(interface='stub',server_ports=(40400,),
                       require_windows=False,sniffer_factory=StubSniffer,
                       evidence_recorder=w)
                src.start();src.ingest_packet(Packet());src.stop()
                self.assertEqual(src.safe_stats()['raw_evidence']['frames'],1)
                self.assertEqual(src.safe_stats()['raw_evidence']['status'],'RECORDED_UNCERTIFIED')
                self.assertEqual(inspect_pcapng(w.final_path,server_ports=(40400,)).selected_segments,1)
                self.assertEqual(len(src.poll(max_segments=10,timeout_seconds=0).segments),1)

    def test_offline_start_never_creates_raw_evidence_without_consent(self):
        from anka_app.cli import ROOT
        self.assertFalse(load_user_config(ROOT/'config/user.json').capture.save_raw_evidence)
