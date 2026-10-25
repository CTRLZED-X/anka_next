"""Consumer-level checks: config, CLI guard, and evidence privacy."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from anka_app.configuration import load_user_config,ConfigurationError, CaptureConfiguration
from anka_app.cli import _command
from anka_capture.api import inspect_pcapng
from anka_observability.api import LocalDiagnostics
from tests.capture_fixtures import sample_capture


class TestCaptureIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.path=self.root/'synthetic.pcapng'
        self.path.write_bytes(sample_capture())
        self.obs=LocalDiagnostics(self.root/'runtime')
        self.user={'schema_version':1,'players':[{'name':'CRA','role':'leader'}],
            'mission':{'route_id':'trial','min_monsters':1,'max_monsters':2,'target_wins':1,'max_attempts':2,
                       'stop_on_loss':True,'stop_on_unknown':True}}
    def write_cfg(self):
        path=self.root/'config.json'
        path.write_text(json.dumps(self.user))
        return load_user_config(path)
    def test_config_ports_optional_but_explicit_for_ingestion(self):
        c=self.write_cfg();self.assertEqual(c.capture.server_ports,())
        self.user['capture']={'server_ports':[40400]}
        c=self.write_cfg();self.assertEqual(c.capture.server_ports,(40400,))
    def test_config_refuses_invalid_port_types_and_repeats(self):
        for ports in ([True],[0],[65536],[40400,40400],['40400'],None):
            with self.subTest(ports=ports):
                self.user['capture']={'server_ports':ports}
                with self.assertRaisesRegex(ConfigurationError,'INVALID_CAPTURE_PORTS'):
                    self.write_cfg()
    def test_cli_offline_inspection_uses_json_ports_and_no_input(self):
        self.user['capture']={'server_ports':[40400]};cfg=self.write_cfg()
        with patch('anka_app.cli.load_user_config',return_value=cfg):
            result=_command('capture',self.obs,[str(self.path)])
        self.assertEqual(result['receipt']['selected_segments'],4)
        self.assertEqual(result['receipt']['status'],'OBSERVED_NO_DETECTED_GAPS')
        self.assertFalse(result['receipt']['protocol_decoded'])
        self.assertFalse(result['receipt']['physical_input_sent'])
        self.assertFalse(result['live_ready'])
        self.assertEqual(result['live_status'],'NOT_CERTIFIED')
    def test_missing_config_ports_is_clear_failure(self):
        cfg=self.write_cfg()
        with patch('anka_app.cli.load_user_config',return_value=cfg):
            with self.assertRaisesRegex(RuntimeError,'CAPTURE_PORTS_NOT_CONFIGURED'):
                _command('capture',self.obs,[str(self.path)])
    def test_gpt_bundle_contains_no_packet_payload_or_endpoint(self):
        inspect_pcapng(self.path,server_ports=(40400,),observer=self.obs)
        bundle=self.obs.export_incident('SYNTHETIC_CAPTURE_AUDIT',boundary='capture.pcapng',detail='Synthetic metadata only')
        with zipfile.ZipFile(bundle) as z:
            body=b'\n'.join(z.read(f) for f in z.namelist())
        self.assertNotIn(b'NOT_GAME',body)
        self.assertNotIn(b'192.0.2.',body)
        self.assertNotIn(self.path.name.encode(),body)
    def test_observer_failure_cannot_change_capture_receipt(self):
        class BrokenObserver:
            def record(self,*_a,**_k):raise RuntimeError('observer-broken')
        receipt=inspect_pcapng(self.path,server_ports=(40400,),observer=BrokenObserver())
        self.assertEqual(receipt.selected_segments,4)
        self.assertEqual(receipt.status,'OBSERVED_NO_DETECTED_GAPS')

    def test_no_source_capture_copied_to_runtime(self):
        inspect_pcapng(self.path,server_ports=(40400,),observer=self.obs)
        self.assertEqual(tuple((self.root/'runtime').rglob('*.pcapng')),())
        self.assertEqual(tuple((self.root/'runtime').rglob('*.pcap')),())
