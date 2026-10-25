"""P66: stop accepting frames BEFORE drain; seal PCAPNG AFTER drain verdict."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anka_capture.api import CaptureRejected, inspect_pcapng
from anka_capture.evidence_recording import ConsentedPcapngRecorder
from anka_capture.windows_live import WindowsLiveCapture, capture_bounded_sample
from anka_contracts.capture import CapturedTcpSegment
import struct


class FakeSniffer:
    def __init__(self, **_):
        pass
    def start(self):
        pass
    def stop(self):
        pass


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


class DrainSealing(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def source(self):
        recorder = ConsentedPcapngRecorder(self.folder, server_ports=(40400,))
        self.assertTrue(recorder.record(tcp_frame(payload=b'PRIVATE-P66')))
        live = WindowsLiveCapture(interface='test', server_ports=(40400,),
                                  sniffer_factory=FakeSniffer, require_windows=False,
                                  evidence_recorder=recorder)
        self.assertTrue(live.queue.push(CapturedTcpSegment('flow_test', 'client_to_server',
                            11, b'hello', 1, 0x18)))
        return live, recorder

    def execute(self, source, callback=None):
        with patch('anka_capture.windows_live.monotonic_ns',
                   side_effect=[0, 1_000_000_001]):
            return capture_bounded_sample(interface='test', server_ports=(40400,),
                                          duration_seconds=1, source=source,
                                          require_windows=False, on_poll=callback)

    def assert_rejected(self, source, recorder):
        report = source.safe_stats()['raw_evidence']
        self.assertIsNotNone(report)
        self.assertEqual(report['status'], 'INCOMPLETE_RECORDED')
        self.assertGreater(report['known_recording_gaps'], 0)
        with self.assertRaises((CaptureRejected, ValueError)):
            inspect_pcapng(recorder.final_path, server_ports=(40400,))

    def test_final_drain_consumer_failure_seals_loss(self):
        source, recorder = self.source()
        def consumer(_poll):
            if source._stopped:
                raise RuntimeError('PRIVATE_POST_STOP_FAILURE')
        with self.assertRaisesRegex(RuntimeError, 'PRIVATE_POST_STOP_FAILURE'):
            self.execute(source, consumer)
        self.assert_rejected(source, recorder)

    def test_final_drain_poll_failure_seals_loss(self):
        source, recorder = self.source()
        original_poll = source.poll
        def polling(**kwargs):
            if source._stopped:
                raise ValueError('PRIVATE_DRAIN_FAILED')
            return original_poll(**kwargs)
        source.poll = polling
        with self.assertRaisesRegex(ValueError, 'PRIVATE_DRAIN_FAILED'):
            self.execute(source)
        self.assert_rejected(source, recorder)

    def test_final_drain_auditor_failure_seals_loss(self):
        from anka_capture.live import LiveCaptureAudit
        source, recorder = self.source()
        prior = LiveCaptureAudit.observe
        def broken(audit, poll):
            if poll.exhausted:
                raise ValueError('PRIVATE_AUDIT_FAILED')
            return prior(audit, poll)
        with patch.object(LiveCaptureAudit, 'observe', broken):
            with self.assertRaisesRegex(ValueError, 'PRIVATE_AUDIT_FAILED'):
                self.execute(source)
        self.assert_rejected(source, recorder)

    def test_successful_drain_keeps_recorder_open_until_consumer_finishes(self):
        source, recorder = self.source()
        completed = []
        def consumer(poll):
            self.assertFalse(recorder._closed, 'finalized before drain consumer')
            if poll.segments:
                completed.append(len(poll.segments))
        receipt = self.execute(source, consumer)
        self.assertEqual(completed, [1])
        self.assertTrue(recorder._closed)
        self.assertEqual(receipt['raw_evidence']['status'], 'RECORDED_UNCERTIFIED')
        self.assertEqual(inspect_pcapng(recorder.final_path,
                                       server_ports=(40400,)).selected_segments, 1)

    def test_direct_stop_still_closes_recorder(self):
        source, recorder = self.source()
        source.start()
        source.stop()
        self.assertTrue(recorder._closed)
        self.assertEqual(source.safe_stats()['raw_evidence']['status'], 'RECORDED_UNCERTIFIED')
        source.stop()
        self.assertEqual(source.safe_stats()['raw_evidence']['known_recording_gaps'], 0)

    def test_quiesce_then_abort_then_finalize_exactly_once(self):
        source, recorder = self.source()
        source.start()
        source.quiesce()
        self.assertTrue(source._stopped)
        self.assertFalse(recorder._closed)
        source.mark_capture_interrupted()
        source.stop()
        self.assert_rejected(source, recorder)
        self.assertEqual(source.safe_stats()['raw_evidence']['known_recording_gaps'], 1)
        source.stop()
        self.assertEqual(source.safe_stats()['raw_evidence']['known_recording_gaps'], 1)


if __name__ == '__main__':
    unittest.main()
