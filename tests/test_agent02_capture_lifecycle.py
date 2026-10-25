"""Agent 02 deterministic Windows capture lifecycle race regressions."""
from __future__ import annotations

import sys
import types
import unittest
from threading import Event, Thread
from unittest.mock import patch

from anka_capture.windows_live import WindowsLiveCapture


class TestAgent02CaptureCallbackQuiesce(unittest.TestCase):
    def test_callback_admitted_before_quiesce_is_not_silently_dropped(self):
        entered = Event()
        release = Event()
        stop_called = Event()

        class IP:
            pass

        class TCP:
            pass

        class FakeIp:
            src = "192.0.2.1"
            dst = "198.51.100.2"

        class FakeTcp:
            sport = 53000
            dport = 40400
            seq = 100
            flags = 0x18
            payload = b"ADMITTED-BEFORE-QUIESCE"

        class Packet:
            def __init__(self):
                self._blocked = False

            def haslayer(self, layer):
                if layer is IP and not self._blocked:
                    self._blocked = True
                    entered.set()
                    self.assert_release()
                return layer in (IP, TCP)

            @staticmethod
            def assert_release():
                if not release.wait(timeout=2):
                    raise RuntimeError("TEST_CALLBACK_RELEASE_TIMEOUT")

            def __getitem__(self, layer):
                if layer is IP:
                    return FakeIp()
                if layer is TCP:
                    return FakeTcp()
                raise KeyError(layer)

        class Sniffer:
            def __init__(self, **_):
                pass

            def start(self):
                pass

            def stop(self):
                stop_called.set()

        inet = types.ModuleType("scapy.layers.inet")
        inet.IP = IP
        inet.TCP = TCP
        layers = types.ModuleType("scapy.layers")
        layers.inet = inet
        scapy = types.ModuleType("scapy")
        scapy.layers = layers

        modules = {
            "scapy": scapy,
            "scapy.layers": layers,
            "scapy.layers.inet": inet,
        }

        with patch.dict(sys.modules, modules):
            source = WindowsLiveCapture(
                interface="stub",
                server_ports=(40400,),
                require_windows=False,
                sniffer_factory=Sniffer,
                lifecycle_timeout_seconds=2,
            )
            source.start()

            callback = Thread(target=source.ingest_packet, args=(Packet(),), daemon=True)
            callback.start()
            self.assertTrue(entered.wait(timeout=1))

            errors = []
            shutdown = Thread(
                target=lambda: self._quiesce(source, errors),
                daemon=True,
            )
            shutdown.start()
            self.assertTrue(stop_called.wait(timeout=1))

            # The stop fence is now active, but the callback crossed it before
            # quiesce and therefore must still finish into the bounded queue.
            release.set()
            callback.join(timeout=1)
            shutdown.join(timeout=1)
            self.assertFalse(callback.is_alive())
            self.assertFalse(shutdown.is_alive())
            self.assertEqual(errors, [])

            poll = source.poll(max_segments=10, timeout_seconds=0)
            self.assertEqual(len(poll.segments), 1)
            self.assertEqual(poll.segments[0].payload, b"ADMITTED-BEFORE-QUIESCE")
            self.assertEqual(poll.dropped, 0)
            self.assertTrue(poll.exhausted)

    def test_late_backend_start_is_boundedly_stopped_after_start_quiesce_timeout(self):
        start_entered = Event()
        release_start = Event()
        stop_called = Event()
        holder = {}

        class Recorder:
            def __init__(self):
                self.marked = 0
                self.closed = 0

            def mark_incomplete(self):
                self.marked += 1

            def close(self):
                self.closed += 1
                return {
                    "status": "INCOMPLETE_RECORDED",
                    "frames": 0,
                    "known_recording_gaps": max(1, self.marked),
                }

        class BlockingStartSniffer:
            def __init__(self, **kwargs):
                self.prn = kwargs.get("prn")
                holder["sniffer"] = self

            def start(self):
                start_entered.set()
                if not release_start.wait(timeout=2):
                    raise RuntimeError("TEST_START_RELEASE_TIMEOUT")

            def stop(self):
                stop_called.set()

        recorder = Recorder()
        source = WindowsLiveCapture(
            interface="stub",
            server_ports=(40400,),
            require_windows=False,
            sniffer_factory=BlockingStartSniffer,
            evidence_recorder=recorder,
            lifecycle_timeout_seconds=0.05,
        )

        start_errors = []
        starter = Thread(
            target=lambda: self._start(source, start_errors),
            daemon=True,
        )
        starter.start()
        self.assertTrue(start_entered.wait(timeout=1))

        with self.assertRaisesRegex(RuntimeError, "LIVE_CAPTURE_START_QUIESCE_TIMEOUT"):
            source.quiesce()
        self.assertTrue(source.queue.stats().source_closed)
        self.assertGreaterEqual(recorder.marked, 1)

        release_start.set()
        starter.join(timeout=1)
        self.assertFalse(starter.is_alive())
        self.assertEqual(start_errors, ["LIVE_CAPTURE_START_QUIESCE_TIMEOUT"])
        self.assertTrue(stop_called.wait(timeout=1))

        stats = source.safe_stats()
        self.assertEqual(stats["lifecycle_error"], "LIVE_CAPTURE_START_QUIESCE_TIMEOUT")
        self.assertIsNone(stats["secondary_cleanup_error"])
        self.assertEqual(stats["raw_evidence"]["status"], "INCOMPLETE_RECORDED")
        self.assertGreaterEqual(stats["raw_evidence"]["known_recording_gaps"], 1)

        accepted_before = stats["accepted_segments"]
        source.ingest_packet(object())  # stop fence returns before packet parsing
        self.assertEqual(source.safe_stats()["accepted_segments"], accepted_before)
        with self.assertRaisesRegex(RuntimeError, "LIVE_CAPTURE_START_QUIESCE_TIMEOUT"):
            source.stop()

    @staticmethod
    def _start(source, errors):
        try:
            source.start()
        except BaseException as exc:
            errors.append(str(exc))

    @staticmethod
    def _quiesce(source, errors):
        try:
            source.quiesce()
        except BaseException as exc:
            errors.append(type(exc).__name__)


if __name__ == "__main__":
    unittest.main()
