"""Independent Chat 08 capture lifecycle regression.

A capture backend whose start completes after a quiesce timeout must not be left
running indefinitely. Callback fencing is necessary but is not equivalent to
stopping the packet-capture backend.
"""
from __future__ import annotations

from threading import Event, Thread
import unittest

from anka_capture.windows_live import WindowsLiveCapture


class TestAgent08CaptureLateStartCleanup(unittest.TestCase):
    def test_backend_that_finishes_start_after_quiesce_timeout_is_stopped(self):
        start_entered = Event()
        allow_start_to_return = Event()
        stop_called = Event()
        start_errors: list[BaseException] = []

        class Sniffer:
            def __init__(self, **_kwargs):
                pass

            def start(self):
                start_entered.set()
                if not allow_start_to_return.wait(timeout=2):
                    raise RuntimeError("TEST_START_RELEASE_TIMEOUT")

            def stop(self):
                stop_called.set()

        source = WindowsLiveCapture(
            interface="stub",
            server_ports=(40400,),
            require_windows=False,
            sniffer_factory=Sniffer,
            lifecycle_timeout_seconds=0.05,
        )

        def run_start():
            try:
                source.start()
            except BaseException as exc:
                start_errors.append(exc)

        starter = Thread(target=run_start, daemon=True)
        starter.start()
        self.assertTrue(start_entered.wait(timeout=1))

        with self.assertRaisesRegex(
            RuntimeError, "LIVE_CAPTURE_START_QUIESCE_TIMEOUT"
        ):
            source.quiesce()

        # The backend finishes starting only after the lifecycle has already
        # failed closed. It must then be actively stopped rather than remaining
        # alive behind only a callback-entry fence.
        allow_start_to_return.set()
        starter.join(timeout=1)
        self.assertFalse(starter.is_alive())
        self.assertEqual(start_errors, [])
        self.assertTrue(
            stop_called.wait(timeout=1),
            "Late backend start returned after quiesce timeout but backend.stop() "
            "was never invoked.",
        )


if __name__ == "__main__":
    unittest.main()
