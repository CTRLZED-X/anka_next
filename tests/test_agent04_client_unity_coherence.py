"""Chat 04 adversarial regressions for exact window/Unity projection coherence."""
from __future__ import annotations

import json
import socket
import struct
import tempfile
import unittest
from pathlib import Path

from anka_client.bridge_discovery import probe_bridge_range
from anka_client.calibration import load_calibration_profile
from anka_client.unity_bridge import ReadOnlyBridgeInspector
from anka_client.win32_bridge_ownership import _loopback_listener_owners
from anka_contracts.client import WindowObservation


PORT = 8765
PID = 2020
CREATED = 123456000
ROOT = Path(__file__).resolve().parents[1]


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


class SequenceReader:
    def __init__(self, *payloads: dict):
        self.payloads = list(payloads)

    def get_json(self, port: int, route: str) -> dict:
        if not self.payloads:
            raise AssertionError('unexpected extra bridge read')
        return dict(self.payloads.pop(0))


class OwnerSequence:
    def __init__(self, *owners: tuple[int,int] | None):
        self.owners = list(owners)

    def __call__(self, port: int) -> tuple[int,int] | None:
        if not self.owners:
            raise AssertionError('unexpected extra listener-owner query')
        return self.owners.pop(0)


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

    def test_map_generation_change_between_health_reads_blocks(self):
        first = health()
        second = health()
        second['mapGeneration'] += 1
        result = ReadOnlyBridgeInspector(SequenceReader(first, {}, second)).inspect_coordinates(
            window(), PORT, map_id=42042
        )
        self.assertEqual((result.status, result.reason),
                         ('BLOCKED', 'BRIDGE_GENERATION_CHANGED_DURING_READ'))

    def test_camera_change_between_health_reads_blocks(self):
        first = health()
        second = health()
        second['cameraFingerprint'] = 'camera-2'
        result = ReadOnlyBridgeInspector(SequenceReader(first, {}, second)).inspect_coordinates(
            window(), PORT, map_id=42042
        )
        self.assertEqual((result.status, result.reason),
                         ('BLOCKED', 'BRIDGE_GENERATION_CHANGED_DURING_READ'))

    def test_zero_projection_generation_never_counts_ready(self):
        stale = health()
        stale['coordinateGeneration'] = 0
        report = probe_bridge_range(
            (window(),), port_start=PORT, port_count=1,
            reader_factory=lambda: FakeReader(stale),
        )
        self.assertEqual(report['status'], 'COMPLETE_PROCESS_MATCH')
        self.assertEqual(report['projection_ready_matches'], 0)

    def test_listener_owner_pid_must_match_health_pid(self):
        report = probe_bridge_range(
            (window(),), port_start=PORT, port_count=1,
            reader_factory=lambda: FakeReader(health()),
            listener_owner_resolver=lambda _port: (9999, CREATED),
        )
        self.assertEqual(report['status'], 'NOT_DETECTED')
        self.assertEqual(report['listener_owner_rejections'], 1)
        self.assertEqual(report['projection_ready_matches'], 0)

    def test_listener_owner_must_remain_stable_across_health_read(self):
        report = probe_bridge_range(
            (window(),), port_start=PORT, port_count=1,
            reader_factory=lambda: FakeReader(health()),
            listener_owner_resolver=OwnerSequence((PID, CREATED), (9999, CREATED)),
        )
        self.assertEqual(report['status'], 'NOT_DETECTED')
        self.assertEqual(report['listener_owner_rejections'], 1)

    def test_verified_listener_owner_allows_exact_window_projection(self):
        report = probe_bridge_range(
            (window(),), port_start=PORT, port_count=1,
            reader_factory=lambda: FakeReader(health()),
            listener_owner_resolver=lambda _port: (PID, CREATED),
        )
        self.assertEqual(report['status'], 'COMPLETE_PROCESS_MATCH')
        self.assertTrue(report['listener_owner_proof_active'])
        self.assertEqual(report['listener_owner_rejections'], 0)
        self.assertEqual(report['projection_ready_matches'], 1)

    def test_listener_owner_recycled_pid_generation_is_rejected(self):
        report = probe_bridge_range(
            (window(),), port_start=PORT, port_count=1,
            reader_factory=lambda: FakeReader(health()),
            listener_owner_resolver=lambda _port: (PID, CREATED + 1),
        )
        self.assertEqual(report['status'], 'NOT_DETECTED')
        self.assertEqual(report['listener_owner_rejections'], 1)
        self.assertEqual(report['projection_ready_matches'], 0)

    def test_windows_tcp_owner_table_parser_accepts_only_loopback_listener(self):
        loopback = struct.unpack('<I', socket.inet_aton('127.0.0.1'))[0]
        other = struct.unpack('<I', socket.inet_aton('0.0.0.0'))[0]
        encoded_port = socket.htons(PORT)
        rows = [
            (2, loopback, encoded_port, 0, 0, PID),
            (2, other, encoded_port, 0, 0, 9999),
            (5, loopback, encoded_port, 0, 0, 8888),
        ]
        raw = struct.pack('<I', len(rows)) + b''.join(struct.pack('<6I', *row) for row in rows)
        self.assertEqual(_loopback_listener_owners(raw, PORT), {PID})

    def test_windows_tcp_owner_table_parser_rejects_truncation(self):
        raw = struct.pack('<I', 2) + struct.pack('<6I', 2, 0, 0, 0, 0, PID)
        with self.assertRaisesRegex(OSError, 'TCP_LISTENER_TABLE_TRUNCATED'):
            _loopback_listener_owners(raw, PORT)

    def test_calibration_loader_rejects_string_coordinate_coercion(self):
        data = {
            'schema_version': 1,
            'source_sha256': 'a' * 64,
            'client_size': {'width': 1280, 'height': 649},
            'spell_slots': {'1': {'x': '467', 'y': 583, 'verified': True}},
            'controls': {},
            'directions': {},
            'status': 'TEST_CURRENT',
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'calibration.json'
            path.write_text(json.dumps(data), encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'INVALID_CALIBRATION_POINT_TYPE'):
                load_calibration_profile(path)

    def test_calibration_loader_rejects_bool_schema_and_geometry(self):
        base = {
            'source_sha256': 'a' * 64,
            'client_size': {'width': 1280, 'height': 649},
            'spell_slots': {},
            'controls': {},
            'directions': {},
            'status': 'TEST_CURRENT',
        }
        cases = [
            dict(base, schema_version=True),
            dict(base, schema_version=1, client_size={'width': True, 'height': 649}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'calibration.json'
            for payload in cases:
                with self.subTest(payload=payload):
                    path.write_text(json.dumps(payload), encoding='utf8')
                    with self.assertRaises(ValueError):
                        load_calibration_profile(path)

    def test_native_transient_projection_loss_forces_retry(self):
        source = (ROOT / 'native/unity_bridge/AutomaticMapAdapter.cs').read_text(encoding='utf8')
        tick_loss = '''_coordinates = NotReadyCoordinates("COORDINATE_NOT_READY", _lastError);
            _coordinateByCell.Clear();
            _lastProjectionSignature = null;
            return;'''
        rebuild_loss = '''_coordinates = NotReadyCoordinates("COORDINATE_NOT_READY", _lastError);
                _coordinateByCell.Clear();
                _lastProjectionSignature = null;
                return;'''
        self.assertIn(tick_loss, source)
        self.assertIn(rebuild_loss, source)

    def test_native_projection_signature_tracks_hwnd_replacement(self):
        source = (ROOT / 'native/unity_bridge/CoordinateProjection.cs').read_text(encoding='utf8')
        self.assertIn('window.Handle.ToInt64().ToString()', source)


if __name__ == '__main__':
    unittest.main()
