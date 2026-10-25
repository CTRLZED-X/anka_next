"""P26 adversarial tests for read-only capture at the real startup boundary."""
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from anka_app.cli import ROOT, _command
from anka_app.configuration import load_user_config
from anka_app.ingress_readiness import (
    probe_start_ingress, stable_flow_hints, _safe_receipt, _windows_sample)
from anka_contracts.client import WindowObservation, WindowScan
from anka_capture.windows_flows import TcpEndpoint
from anka_observability.api import LocalDiagnostics
from anka_observability.bundle import verify_incident

CFG = load_user_config(ROOT/'config/user.json')
TEST_CFG = replace(CFG, capture=replace(CFG.capture, server_ports=(40400,), interface='test-interface', duration_seconds=60))
READY_HOST = {'platform': 'WINDOWS', 'candidate_windows': 2, 'account_binding_states': ['PENDING', 'PENDING'], 'capture': {'scapy_installed': True, 'server_port_candidates': 1}}


def receipt():
    return {'status': 'UNCERTIFIED', 'selected_segments': 6, 'queue_dropped': 0,
            'invalid_frames': 0, 'rejected_frames': 0, 'unsupported_frames': 1,
            'transport': {'unanchored_directions': 1, 'unresolved_gap_directions': 0,
                          'observed_generations': 2, 'reconnections': 0,
                          'duplicate_segments': 1, 'reordered_segments': 0,
                          'metadata_limit_reached': False, 'packet_order_uncertain': False},
            'flow_attribution': {'status': 'NOT_ATTESTED',
                                 'counts': {'PROVISIONAL': 1, 'AMBIGUOUS': 0, 'UNMATCHED': 1}},
            'leaked_ip': '203.0.113.77', 'raw_payload': b'SECRET', 'physical_input_sent': True,
            'account_binding_verified': True, 'live_ready': True}


def scan(*items, errors=()):
    return WindowScan(10000, tuple(items), tuple(errors))


def win(hwnd=55, pid=123, generation=333):
    return WindowObservation(hwnd, pid, generation, 'Dofus.exe', 'NAME - Dofus', 1280, 649, 96, False)


def row(pid=123, remote_ip='198.51.100.7', state=5):
    return TcpEndpoint('127.0.0.1', 49152, remote_ip, 40400, pid, state)


class TestP26PassiveIngress(unittest.TestCase):
    def test_linux_never_captures_even_with_valid_windows_hints(self):
        r = probe_start_ingress(TEST_CFG, READY_HOST, platform='posix',
                                sample=lambda _: self.fail('capture called'))
        self.assertEqual(r['reason'], 'WINDOWS_ONLY')
        self.assertFalse(r['capture_attempted'])

    def test_empty_operator_capture_config_uses_auto_scope(self):
        r = probe_start_ingress(CFG, READY_HOST, platform='nt', sample=lambda _: receipt())
        self.assertEqual(r['status'],'CAPTURED_UNCERTIFIED')
        self.assertTrue(r['capture_attempted'])

    def test_missing_interface_uses_internal_auto_interface(self):
        c = replace(TEST_CFG, capture=replace(TEST_CFG.capture, interface=None))
        r=probe_start_ingress(c, READY_HOST, platform='nt', sample=lambda _: receipt())
        self.assertEqual(r['status'],'CAPTURED_UNCERTIFIED')

    def test_absent_game_window_never_capture(self):
        h = dict(READY_HOST, candidate_windows=0)
        r = probe_start_ingress(TEST_CFG, h, platform='nt', sample=lambda _: self.fail('capture called'))
        self.assertEqual(r['reason'], 'GAME_WINDOW_CANDIDATE_MISSING')

    def test_invalid_candidate_count_never_capture(self):
        for value in (None, '2', True, -1):
            with self.subTest(value=value):
                h = dict(READY_HOST, candidate_windows=value)
                self.assertEqual(probe_start_ingress(TEST_CFG, h, platform='nt')['status'], 'SKIPPED')

    def test_unattested_accounts_do_not_block_observe_only_capture(self):
        h = dict(READY_HOST, account_binding_states=['BLOCKED', 'BLOCKED'])
        r = probe_start_ingress(TEST_CFG, h, platform='nt', sample=lambda _: receipt())
        self.assertEqual(r['status'],'CAPTURED_UNCERTIFIED')
        self.assertFalse(r['account_binding_verified'])

    def test_malformed_host_snapshot_never_capture(self):
        for host in (None, [], {}, dict(READY_HOST, capture=None)):
            with self.subTest(host=str(host)[:40]):
                r = probe_start_ingress(TEST_CFG, host, platform='nt', sample=lambda _: self.fail('capture called'))
                self.assertEqual(r['status'], 'SKIPPED')

    def test_scapy_unavailable_never_capture(self):
        h = dict(READY_HOST, capture={'scapy_installed': False})
        self.assertEqual(probe_start_ingress(TEST_CFG, h, platform='nt')['reason'],
                         'OPTIONAL_CAPTURE_DEPENDENCY_MISSING')

    def test_host_platform_mismatch_never_capture(self):
        h = dict(READY_HOST, platform='NON_WINDOWS')
        self.assertEqual(probe_start_ingress(TEST_CFG, h, platform='nt')['reason'],
                         'HOST_SNAPSHOT_NOT_WINDOWS')

    def test_read_only_capture_always_uncertified(self):
        result = probe_start_ingress(TEST_CFG, READY_HOST, platform='nt', sample=lambda c: receipt())
        self.assertEqual(result['status'], 'CAPTURED_UNCERTIFIED')
        self.assertTrue(result['capture_attempted'])
        for k in ('live_certified', 'physical_input_permitted', 'account_binding_verified',
                  'packet_payload_persisted'):
            self.assertFalse(result[k])
        self.assertEqual(result['receipt']['driver_loss_visibility'], 'UNKNOWN')

    def test_privacy_allowlist_blocks_arbitrary_data(self):
        result = probe_start_ingress(TEST_CFG, READY_HOST, platform='nt', sample=lambda _: receipt())
        serialized = json.dumps(result)
        for secret in ('203.0.113.77', 'SECRET', 'test-interface', 'Curseni', 'Sosoking', 'leaked_ip', 'raw_payload'):
            self.assertNotIn(secret, serialized)

    def test_capture_exception_replaced_with_category(self):
        def broken(_):
            raise RuntimeError('secret/path/private/203.0.113.5')
        result = probe_start_ingress(TEST_CFG, READY_HOST, platform='nt', sample=broken)
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['reason'], 'CAPTURE_SAMPLE_FAILED')
        self.assertNotIn('203.0.113.5', json.dumps(result))
        self.assertFalse(result['physical_input_permitted'])

    def test_malformed_receipt_fails_closed(self):
        for obj in (None, {}, [], {'status': 'LIVE_CERTIFIED'}, {'status': 'UNCERTIFIED', 'transport': {}}):
            with self.subTest(obj=str(obj)[:20]):
                result = probe_start_ingress(TEST_CFG, READY_HOST, platform='nt', sample=lambda _, v=obj: v)
                self.assertEqual(result['status'], 'FAILED')

    def test_cannot_forge_negative_or_boolean_counter(self):
        for bad in (-1, True, 10**13, '0', 1.5):
            obj = receipt()
            obj['selected_segments'] = bad
            self.assertEqual(probe_start_ingress(TEST_CFG, READY_HOST, platform='nt',
                                                 sample=lambda _, v=obj: v)['status'], 'FAILED')

    def test_cannot_forge_driver_clean_status(self):
        obj = receipt()
        obj['driver_loss_visibility'] = 'AVAILABLE_CLEAN'
        obj['live_ready'] = True
        result = _safe_receipt(obj)
        self.assertEqual(result['driver_loss_visibility'], 'UNKNOWN')
        self.assertNotIn('live_ready', result)

    def test_missing_transport_boolean_refused(self):
        obj = receipt()
        del obj['transport']['metadata_limit_reached']
        self.assertEqual(probe_start_ingress(TEST_CFG, READY_HOST, platform='nt', sample=lambda _: obj)['status'], 'FAILED')

    def test_unknown_status_refused(self):
        obj = receipt()
        obj['status'] = 'PASS'
        self.assertEqual(probe_start_ingress(TEST_CFG, READY_HOST, platform='nt', sample=lambda _: obj)['status'], 'FAILED')

    def test_transport_loss_remains_uncertified(self):
        obj = receipt()
        obj['status'] = 'LOSS_DETECTED'
        obj['queue_dropped'] = 3
        result = probe_start_ingress(TEST_CFG, READY_HOST, platform='nt', sample=lambda _: obj)
        self.assertEqual(result['receipt']['status'], 'LOSS_DETECTED')
        self.assertFalse(result['live_certified'])

    def test_loss_without_matching_status_does_not_certify(self):
        obj = receipt()
        obj['queue_dropped'] = 4
        result = probe_start_ingress(TEST_CFG, READY_HOST, platform='nt', sample=lambda _: obj)
        self.assertEqual(result['status'], 'FAILED')
        self.assertFalse(result['live_certified'])

    def test_false_loss_report_rejected(self):
        obj = receipt()
        obj['status'] = 'LOSS_DETECTED'
        self.assertEqual(probe_start_ingress(TEST_CFG, READY_HOST, platform='nt', sample=lambda _: obj)['status'], 'FAILED')

    def test_no_endpoints_exposed_by_attribution(self):
        r = stable_flow_hints(scan(win()), scan(win()), (row(),), (row(),),
                              {'flow_id': ('127.0.0.1', 49152, '198.51.100.7', 40400)})
        self.assertEqual(r['status'], 'NOT_ATTESTED')
        self.assertEqual(r['counts']['PROVISIONAL'], 1)
        self.assertNotIn('198.51.100.7', json.dumps(r))

    def test_windows_generation_changed_disallows_hint(self):
        r = stable_flow_hints(scan(win()), scan(win(generation=334)), (row(),), (row(),),
                              {'flow': ('127.0.0.1', 49152, '198.51.100.7', 40400)})
        self.assertEqual(r['counts']['UNMATCHED'], 1)

    def test_pid_reuse_with_new_hwnd_disallows_hint(self):
        r = stable_flow_hints(scan(win()), scan(win(hwnd=88)), (row(),), (row(),),
                              {'flow': ('127.0.0.1', 49152, '198.51.100.7', 40400)})
        self.assertEqual(r['counts']['UNMATCHED'], 1)

    def test_missing_tcp_at_one_boundary_disallows_hint(self):
        r = stable_flow_hints(scan(win()), scan(win()), (row(),), (),
                              {'flow': ('127.0.0.1', 49152, '198.51.100.7', 40400)})
        self.assertEqual(r['counts']['UNMATCHED'], 1)

    def test_unrelated_pid_disallows_hint(self):
        r = stable_flow_hints(scan(win()), scan(win()), (row(pid=900),), (row(pid=900),),
                              {'flow': ('127.0.0.1', 49152, '198.51.100.7', 40400)})
        self.assertEqual(r['counts']['UNMATCHED'], 1)

    def test_incomplete_scan_disallows_hints(self):
        r = stable_flow_hints(scan(win(), errors=('SCAN_FAILED',)), scan(win()), (row(),), (row(),),
                              {'flow': ('127.0.0.1', 49152, '198.51.100.7', 40400)})
        self.assertEqual(r['status'], 'UNAVAILABLE')

    def test_pid_only_unambiguous_at_one_boundary_disallows_hint(self):
        r = stable_flow_hints(scan(win(), win(hwnd=56)), scan(win()), (row(),), (row(),),
                              {'flow': ('127.0.0.1', 49152, '198.51.100.7', 40400)})
        self.assertEqual(r['counts']['UNMATCHED'], 1)

    def test_shared_pid_two_windows_disallows_hint(self):
        r = stable_flow_hints(scan(win(), win(hwnd=56)), scan(win(), win(hwnd=56)),
                              (row(),), (row(),),
                              {'flow': ('127.0.0.1', 49152, '198.51.100.7', 40400)})
        self.assertEqual(r['counts']['UNMATCHED'], 1)

    def test_invalid_flow_attribution_fails_closed(self):
        obj = receipt()
        obj['flow_attribution'] = {'status': 'AUTHORITATIVE'}
        self.assertEqual(probe_start_ingress(TEST_CFG, READY_HOST, platform='nt', sample=lambda _: obj)['status'], 'FAILED')

    def test_read_only_probe_writes_privacy_safe_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            obs = LocalDiagnostics(Path(directory))
            probe_start_ingress(TEST_CFG, READY_HOST, platform='nt', sample=lambda _: receipt(), observer=obs)
            incident = obs.export_incident('LIVE_RUNTIME_NOT_IMPLEMENTED', boundary='readiness.read_only_capture')
            self.assertEqual(verify_incident(incident)['status'], 'PASS')
            from zipfile import ZipFile
            with ZipFile(incident) as z:
                data = '\n'.join(z.read(n).decode('utf8', errors='replace') for n in z.namelist()
                                 if n.endswith(('.json', '.jsonl', '.md')))
            self.assertIn('readiness.passive_ingress_probe', data)
            self.assertNotIn('203.0.113.77', data)
            self.assertNotIn('raw_payload', data)

    def test_start_runs_probe_before_expected_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            obs = LocalDiagnostics(Path(directory))
            with patch('anka_app.cli._host_check', return_value=READY_HOST), \
                 patch('anka_app.ingress_readiness.probe_start_ingress', return_value={'status': 'SKIPPED'}) as sample:
                with self.assertRaisesRegex(RuntimeError, 'START_CAPTURE_EVIDENCE_MISSING'):
                    _command('start', obs, [])
            self.assertEqual(sample.call_count, 1)
            self.assertEqual(sample.call_args.kwargs['observer'], obs)
            obs.finish('BLOCKED')

    def test_setup_does_not_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            obs = LocalDiagnostics(Path(directory))
            with patch('anka_app.ingress_readiness.probe_start_ingress') as sample:
                result = _command('setup', obs, [])
            sample.assert_not_called()
            self.assertFalse(result['live_ready'])
            obs.finish()

    def test_only_two_operator_launchers(self):
        self.assertEqual({f.name for f in ROOT.glob('*.bat')}, {'setup.bat', 'start.bat'})


if __name__ == '__main__':
    unittest.main()

class TestP26WindowsCaptureComposition(unittest.TestCase):
    def test_composition_caps_duration_and_tracks_flow_hints(self):
        source = type('FakeSource', (), {'flow_keys_for_attribution': lambda self: {
            't': ('127.0.0.1',49152,'198.51.100.7',40400)}})()
        class FakeInventory:
            def __init__(self, names):
                self.names = names
            def scan(self):
                return scan(win(),win(hwnd=56,pid=124,generation=334))
        class FakeOwner:
            def snapshot(self):
                return (row(),)
        def sample(**kwargs):
            self.assertEqual(kwargs['duration_seconds'], 10)
            self.assertIs(kwargs['source'], source)
            return receipt()
        with patch('anka_client.win32_inventory.NativeWindowsInventory', FakeInventory), \
             patch('anka_capture.windows_flows.WindowsTcpOwnership', FakeOwner), \
             patch('anka_capture.windows_live.WindowsLiveCapture', return_value=source), \
             patch('anka_capture.windows_live.capture_bounded_sample', side_effect=sample):
            result = _windows_sample(TEST_CFG)
        self.assertEqual(result['flow_attribution']['counts']['PROVISIONAL'], 1)
        sanitized = _safe_receipt(result)
        self.assertNotIn('account_binding_verified', sanitized)
        self.assertEqual(sanitized['flow_attribution']['status'], 'NOT_ATTESTED')

    def test_composition_snapshot_failure_prevents_capture_scope_guess(self):
        class FakeInventory:
            def __init__(self, names): pass
            def scan(self): raise RuntimeError('windows inventory permission denied')
        class FakeOwner:
            def snapshot(self): return (row(),)
        with patch('anka_client.win32_inventory.NativeWindowsInventory', FakeInventory), \
             patch('anka_capture.windows_flows.WindowsTcpOwnership', FakeOwner):
            with self.assertRaises(RuntimeError):
                _windows_sample(TEST_CFG)

    def test_setup_prepares_capture_automatically_with_only_two_launchers(self):
        entry = (ROOT/'tools/windows/_entry.bat').read_text(encoding='utf8')
        self.assertIn('INSTALL_CAPTURE_DEPENDENCIES',entry)
        self.assertIn('requirements-windows-capture.txt',entry)
        self.assertNotIn("cfg.get('server_ports') and cfg.get('interface')",entry)
        self.assertIn('ANKA SETUP COMPLETED SUCCESSFULLY',entry)
        self.assertEqual({x.name for x in ROOT.glob('*.bat')},{'setup.bat','start.bat'})
