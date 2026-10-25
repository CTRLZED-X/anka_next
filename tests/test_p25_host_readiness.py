"""P25 passive host evidence: deliberately adversarial injected Windows probes."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from dataclasses import replace

from anka_app.cli import ROOT, _command, _host_check
from anka_app.configuration import load_user_config
from anka_app.host_readiness import probe_host
from anka_client.discovery import bind_accounts
from anka_contracts.client import WindowScan, WindowObservation
from anka_capture.windows_flows import TcpEndpoint
from anka_observability.api import LocalDiagnostics
from anka_observability.bundle import verify_incident

C = load_user_config(ROOT/'config/user.json')
T = 88_000_000_000


def window(hwnd=101,pid=800,title='Curseni - Dofus',size=(1280,649),minimized=False):
    return WindowObservation(hwnd,pid,123456,'Dofus.exe',title,*size,96,minimized)

class Inventory:
    def __init__(self, snapshot):
        self.snapshot=snapshot
    def scan(self):
        return self.snapshot

def factory(scan):
    return lambda names: Inventory(scan)


def tcp(pid=800, state=5, ip='198.51.100.7'):
    return TcpEndpoint('127.0.0.1',8888,ip,12345,pid,state)


class TestP25HostReadiness(unittest.TestCase):
    def test_linux_never_invokes_windows_backend(self):
        def fail(*a,**k): raise AssertionError('must not access Windows')
        report=probe_host(C,platform='posix',inventory_factory=fail,tcp_snapshot=fail,scapy_available=fail)
        self.assertEqual(report['platform'],'NON_WINDOWS')
        self.assertEqual(report['tcp_ownership'],'WINDOWS_ONLY')
        self.assertFalse(report['live_certified'])
        self.assertFalse(report['physical_input_permitted'])
        self.assertIn('HOST_WINDOWS_ACCEPTANCE_NOT_PERFORMED',report['issues'])

    def test_windows_empty_inventory_still_not_certified(self):
        r=probe_host(C,platform='nt',inventory_factory=factory(WindowScan(T,())),
                     tcp_snapshot=lambda:(),scapy_available=lambda:True)
        self.assertEqual(r['candidate_windows'],0)
        self.assertEqual(r['identity_issues'],['NO_CANDIDATE_WINDOW']*len(C.players))
        self.assertIn('DOFUS_WINDOW_NOT_FOUND',r['issues'])
        self.assertIn('CURRENT_CHARACTER_IDENTITY_EVIDENCE_MISSING',r['issues'])
        self.assertEqual(r['capture']['scope_mode'],'AUTO_PROCESS_TCP')
        self.assertFalse(r['account_binding_verified'])

    def test_two_window_candidates_never_certified_by_matching_size(self):
        snap=WindowScan(T,(window(),window(102,801,'Sosoking - Dofus')))
        r=probe_host(C,platform='nt',inventory_factory=factory(snap),
                     tcp_snapshot=lambda:(tcp(),tcp(801),tcp(982),tcp(903,state=1)),
                     scapy_available=lambda:True)
        self.assertEqual(r['candidate_windows'],2)
        self.assertEqual(r['geometry_reference_matches'],2)
        self.assertEqual(r['tcp_candidate_processes'],2)  # excludes unrelated PIDs
        self.assertEqual(r['account_binding_states'],['PENDING','PENDING'])
        self.assertFalse(r['calibration_certified'])
        self.assertEqual(r['tcp_ownership'],'PROVISIONAL_PROCESS_HINT_ONLY')
        self.assertNotIn('198.51.100.7',json.dumps(r))
        self.assertNotIn('Curseni',json.dumps(r))
        self.assertNotIn('Sosoking',json.dumps(r))
        self.assertNotIn('8888',json.dumps(r))

    def test_minimized_and_wrong_geometry_visible(self):
        r=probe_host(C,platform='nt',inventory_factory=factory(WindowScan(T,(
            window(size=(900,500)),window(102,801,'Sosoking - Dofus',minimized=True)))),
            tcp_snapshot=lambda:(),scapy_available=lambda:False)
        self.assertIn('WINDOW_SIZE_DIFFERS_FROM_HISTORICAL_CALIBRATION',r['geometry_issues'])
        self.assertIn('WINDOW_MINIMIZED',r['identity_issues'])
        self.assertIn('CAPTURE_OPTIONAL_SCAPY_NOT_INSTALLED',r['issues'])

    def test_bad_window_scan_becomes_diagnostic_gap(self):
        def crash(*a): raise RuntimeError('secret-local-file')
        r=probe_host(C,platform='nt',inventory_factory=crash,tcp_snapshot=lambda:(),scapy_available=lambda:True)
        self.assertIn('WINDOW_INVENTORY_PROBE_FAILED',r['issues'])
        self.assertNotIn('secret-local-file',json.dumps(r))
        self.assertFalse(r['live_certified'])

    def test_inventory_partial_and_tcp_exception(self):
        r=probe_host(C,platform='nt',inventory_factory=factory(WindowScan(T,(window(),),('ENUM_WINDOWS_FAILED',))),
                     tcp_snapshot=lambda: (_ for _ in ()).throw(ValueError('remote_ip_secret')),
                     scapy_available=lambda:True)
        self.assertIn('WINDOW_INVENTORY_INCOMPLETE',r['issues'])
        self.assertEqual(r['tcp_ownership'],'UNAVAILABLE')
        self.assertNotIn('remote_ip_secret',json.dumps(r))

    def test_optional_dependency_exception_is_categorical(self):
        r=probe_host(C,platform='nt',inventory_factory=factory(WindowScan(T,())),
                     tcp_snapshot=lambda:(),scapy_available=lambda:1/0)
        self.assertIn('CAPTURE_DEPENDENCY_PROBE_FAILED',r['issues'])
        self.assertFalse(r['capture']['scapy_installed'])

    def test_tcp_no_connections_not_setup_failure(self):
        r=probe_host(C,platform='nt',inventory_factory=factory(WindowScan(T,())),
                     tcp_snapshot=lambda:(),scapy_available=lambda:True)
        self.assertNotIn('TCP_CONNECTIONS_MISSING',r['issues'])
        self.assertEqual(r['tcp_candidate_processes'],0)

    def test_real_readiness_does_not_accept_injected_host_proofs(self):
        from anka_app.readiness import assess_live_readiness
        self.assertFalse(assess_live_readiness().live_ready)
        self.assertFalse(assess_live_readiness().physical_input_enabled)

    def test_setup_is_installation_only_not_live_host_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            o=LocalDiagnostics(Path(temp))
            r=_command('setup',o,[])
            self.assertEqual(r['host_observation'],'NOT_RUN_DURING_SETUP_OR_CHECK')
            self.assertEqual(r['installation_status'],'READY')
            events=list(o.freeze().recent)
            self.assertNotIn('client.host_observation_completed',[e['event_name'] for e in events])
            o.finish()

    def test_start_records_host_probe_before_block(self):
        with tempfile.TemporaryDirectory() as temp:
            o=LocalDiagnostics(Path(temp))
            with self.assertRaisesRegex(RuntimeError,'START_WINDOWS_REQUIRED'):
                _command('start',o,[])
            events=list(o.freeze().recent)
            self.assertIn('client.host_observation_completed',[e['event_name'] for e in events])
            o.finish('BLOCKED')

    def test_host_probe_event_keeps_failure_evidence_in_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            o=LocalDiagnostics(Path(temp))
            _host_check(o)
            path=o.export_incident('START_CHARACTER_IDENTITY_UNATTESTED',boundary='client.host_observation')
            self.assertEqual(verify_incident(path)['status'],'PASS')
            from zipfile import ZipFile
            with ZipFile(path) as archive:
                names=archive.namelist()
                data=''.join(archive.read(n).decode('utf-8',errors='ignore') for n in names if n.endswith(('.json','.jsonl','.md')))
                self.assertIn('client.host_observation_completed',data)
                self.assertNotIn('198.51.100.7',data)

    def test_only_two_bat_commands(self):
        self.assertEqual({p.name for p in ROOT.glob('*.bat')},{'setup.bat','start.bat'})


if __name__ == '__main__':unittest.main()
