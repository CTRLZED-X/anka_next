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

    @staticmethod
    def _quiesce(source, errors):
        try:
            source.quiesce()
        except BaseException as exc:
            errors.append(type(exc).__name__)


if __name__ == "__main__":
    unittest.main()
