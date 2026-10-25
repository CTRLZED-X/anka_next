"""P65: interrupted optional raw capture must never resemble completed evidence."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anka_capture.evidence_recording import ConsentedPcapngRecorder
from anka_capture.pcapng import pcapng_packet_count
from anka_capture.windows_live import WindowsLiveCapture, capture_bounded_sample
from anka_capture.api import CaptureRejected, inspect_pcapng
import struct


def tcp_frame(*, payload=b'hello'):
    ip = bytearray(20)
    ip[0] = 0x45
    ip[2:4] = (40 + len(payload)).to_bytes(2, 'big')
    ip[8] = 64
    ip[9] = 6
    ip[12:16] = bytes((192, 0, 2, 1))
    ip[16:20] = bytes((198, 51, 100, 2))
    tcp = bytearray(20)
    tcp[:4] = struct.pack('!HH', 53000, 40400)
    tcp[12] = 0x50
    tcp[13] = 0x18
    return bytes(12) + b'\x08\x00' + bytes(ip) + bytes(tcp) + payload


class FakeSniffer:
    def __init__(self, **_):
        self.started = False
    def start(self):
        self.started = True
    def stop(self):
        pass


class StopFailureSniffer(FakeSniffer):
    def stop(self):
        raise OSError('private capture device and address')


class AbortIntegrity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def source(self, factory=FakeSniffer):
        recorder = ConsentedPcapngRecorder(self.dir, server_ports=(40400,))
        live = WindowsLiveCapture(interface='test', server_ports=(40400,),
                                  sniffer_factory=factory, require_windows=False,
                                  evidence_recorder=recorder)
        self.assertTrue(recorder.record(tcp_frame(payload=b'PRIVATE-CONTENT')))
        return live, recorder

    def assert_incomplete(self, source, recorder):
        r = source.safe_stats()['raw_evidence']
        self.assertEqual(r['status'], 'INCOMPLETE_RECORDED')
        self.assertGreaterEqual(r['known_recording_gaps'], 1)
        with self.assertRaises((CaptureRejected, ValueError)):
            inspect_pcapng(recorder.final_path, server_ports=(40400,))
        self.assertNotIn('PRIVATE-CONTENT', str(r))

    def test_exception_while_polling_seals_incomplete_file(self):
        source, recorder = self.source()
        def fail_poll(**_):
            raise RuntimeError('private poll endpoint')
        source.poll = fail_poll
        with self.assertRaisesRegex(RuntimeError, 'private poll endpoint'):
            capture_bounded_sample(interface='test', server_ports=(40400,),
                                   duration_seconds=1, source=source,
                                   require_windows=False)
        self.assert_incomplete(source, recorder)

    def test_callback_exception_seals_incomplete_file(self):
        source, recorder = self.source()
        def bad_consumer(_):
            raise ValueError('private decoder error')
        with self.assertRaisesRegex(ValueError, 'private decoder error'):
            capture_bounded_sample(interface='test', server_ports=(40400,),
                                   duration_seconds=1, source=source,
                                   require_windows=False, on_poll=bad_consumer)
        self.assert_incomplete(source, recorder)

    def test_sniffer_shutdown_failure_remains_unsealed_and_incomplete(self):
        source, recorder = self.source(StopFailureSniffer)
        source.start()
        with self.assertRaisesRegex(RuntimeError, 'LIVE_CAPTURE_STOP_FAILED'):
            source.stop()
        # A backend stop error does not prove callback quiescence.  Finalizing the
        # raw artifact here would falsely make an uncertain capture look sealed.
        self.assertIsNone(source.safe_stats()['raw_evidence'])
        self.assertFalse(recorder.final_path.exists())

    def test_clean_normal_shutdown_does_not_forge_loss(self):
        source, recorder = self.source()
        source.start(); source.stop()
        r = source.safe_stats()['raw_evidence']
        self.assertEqual(r['status'], 'RECORDED_UNCERTIFIED')
        self.assertEqual(r['known_recording_gaps'], 0)
        self.assertEqual(pcapng_packet_count(recorder.final_path), 1)

    def test_abort_is_idempotent_prior_to_stop(self):
        source, recorder = self.source()
        source.start()
        source.mark_capture_interrupted()
        source.stop()
        self.assert_incomplete(source, recorder)
        self.assertEqual(source.safe_stats()['raw_evidence']['known_recording_gaps'], 1)
        source.stop()
        self.assertEqual(source.safe_stats()['raw_evidence']['known_recording_gaps'], 1)

    def test_stop_before_start_never_finalizes_a_clean_capture(self):
        source, recorder = self.source()
        source.stop()
        self.assert_incomplete(source, recorder)

    def test_exception_on_sniffer_start_stays_incomplete(self):
        class FailStart(FakeSniffer):
            def start(self):
                raise OSError('capture denied')
        source, recorder = self.source(FailStart)
        with self.assertRaisesRegex(RuntimeError, 'LIVE_CAPTURE_START_FAILED'):
            source.start()
        self.assert_incomplete(source, recorder)


if __name__ == '__main__':
    unittest.main()
