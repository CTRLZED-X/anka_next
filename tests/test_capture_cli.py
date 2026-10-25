import json
import subprocess
import sys
import unittest
from anka_app.cli import ROOT

class TestCaptureCli(unittest.TestCase):
    def test_demo_cli_is_read_only(self):
        p=subprocess.run([sys.executable,'-m','anka_app.cli','capture-demo'],cwd=ROOT,
            capture_output=True,text=True,timeout=25)
        self.assertEqual(p.returncode,0,p.stdout+'\n'+p.stderr)
        self.assertIn('ANKA_STATUS=SYNTHETIC_CAPTURE_ONLY',p.stdout)
        record=next(line.split('=',1)[1] for line in p.stdout.splitlines() if line.startswith('ANKA_RESULT='))
        result=json.loads(record)
        self.assertEqual(result['receipt']['packet_records'],4)
        self.assertFalse(result['receipt']['protocol_decoded'])
        self.assertFalse(result['receipt']['account_binding_verified'])
        self.assertFalse(result['receipt']['live_capture_equivalent'])
        self.assertFalse(result['physical_input_sent'])
    def test_real_capture_command_requires_operator_port_setting(self):
        p=subprocess.run([sys.executable,'-m','anka_app.cli','capture','examples/SYNTHETIC_CAPTURE_P4.pcapng'],
                         cwd=ROOT,capture_output=True,text=True,timeout=25)
        self.assertEqual(p.returncode,40)
        self.assertIn('ANKA_FAILURE=CAPTURE_PORTS_NOT_CONFIGURED',p.stdout)
        self.assertIn('ANKA_BUNDLE=',p.stdout)
