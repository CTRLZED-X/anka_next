"""Chat 04 adversarial regressions for exact window/Unity projection coherence."""
from __future__ import annotations

import unittest

from anka_app.cli import ROOT
from anka_client.bridge_discovery import probe_bridge_range
from anka_client.unity_bridge import ReadOnlyBridgeInspector
from anka_contracts.client import WindowObservation


PORT = 8765
PID = 2020
CREATED = 123456000


def window(hwnd: int = 33, *, size: tuple[int, int] = (1280, 649)) -> WindowObservation:
    return WindowObservation(
        hwnd, PID, CREATED, 'Dofus.exe', 'Dofus', size[0], size[1], 96, False,
        True, False, '3.7.10.10'
    )


def health(*, hwnd: int = 33, width: int = 1280, height: int = 649) -> dict:
    return {
        'source': 'unity_bridge',
        'available': True,
        'status': 'MAP_COORDINATES_READY',
        'processId': PID,
        'processStartTime': CREATED,
        'bridgePort': PORT,
        'loadedMapId': 42042,
        'mapGeneration': 7,
        'coordinateGeneration': 9,
        'sourceVerified': True,
        'sourceClientWidth': width,
        'sourceClientHeight': height,
        'projectionSignature': 'projection-9',
        'windowFingerprint': f'{hwnd}:10:20:{width}:{height}',
        'cameraFingerprint': 'camera-1',
        'cellGeometryFingerprint': 'cells-1',
    }


class FakeReader:
    def __init__(self, payload: dict):
        self.payload = payload

    def get_json(self, port: int, route: str) -> dict:
        if route == '/health':
            return dict(self.payload)
        raise AssertionError('coordinates should not be read after a health/window mismatch')


class Agent04ClientUnityCoherenceTests(unittest.TestCase):
    def test_projection_ready_requires_exact_hwnd_not_only_pid_generation(self):
        target = window(33)
        report = probe_bridge_range(
            (target,), port_start=PORT, port_count=1,
            reader_factory=lambda: FakeReader(health(hwnd=44)),
        )
        self.assertEqual(report['status'], 'COMPLETE_PROCESS_MATCH')
        self.assertEqual(report['process_generation_matches'], 1)
        self.assertEqual(report['projection_ready_matches'], 0)

    def test_same_process_multiple_windows_is_ambiguous_not_complete(self):
        report = probe_bridge_range(
            (window(33), window(44)), port_start=PORT, port_count=1,
            reader_factory=lambda: FakeReader(health(hwnd=33)),
        )
        self.assertEqual(report['status'], 'AMBIGUOUS_PROCESS_MATCH')
        self.assertEqual(report['ambiguous_window_process_generations'], 1)
        self.assertEqual(report['projection_ready_matches'], 0)

    def test_coordinate_inspector_rejects_wrong_hwnd_before_coordinate_read(self):
        result = ReadOnlyBridgeInspector(FakeReader(health(hwnd=44))).inspect_coordinates(
            window(33), PORT, map_id=42042
        )
        self.assertEqual((result.status, result.reason),
                         ('BLOCKED', 'BRIDGE_WINDOW_HANDLE_MISMATCH'))

    def test_native_projection_signature_tracks_hwnd_replacement(self):
        source = (ROOT / 'native/unity_bridge/CoordinateProjection.cs').read_text(encoding='utf8')
        self.assertIn('window.Handle.ToInt64().ToString()', source)


if __name__ == '__main__':
    unittest.main()
