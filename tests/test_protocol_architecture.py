"""Executable import and promotion boundaries for frequent protocol updates."""
from __future__ import annotations
import ast
import json
import subprocess
import sys
import unittest
from pathlib import Path
from anka_app.cli import ROOT


class TestProtocolArchitecture(unittest.TestCase):
    def test_protocol_package_cannot_import_capture_internals_or_gameplay(self):
        folder=ROOT/'src/anka_protocol'
        forbidden=('anka_capture', 'anka_live_state', 'anka_execution', 'anka_decision',
                   'anka_coordination', 'anka_workflow', 'anka_game_kernel', 'anka_canonical', 'anka_app')
        for source in folder.rglob('*.py'):
            parsed=ast.parse(source.read_text(encoding='utf8'))
            for node in ast.walk(parsed):
                targets=[]
                if isinstance(node,ast.Import):targets=[alias.name for alias in node.names]
                elif isinstance(node,ast.ImportFrom):targets=[node.module or '']
                for target in targets:
                    self.assertFalse(any(target==x or target.startswith(x+'.') for x in forbidden),
                         (source.relative_to(ROOT),target))
    def test_reference_data_is_explicitly_uncertified(self):
        obj=json.loads((ROOT/'reference/protocol/manifest.json').read_text(encoding='utf8'))
        self.assertEqual(obj['source_role'],'HISTORICAL_REFERENCE_ONLY')
        self.assertIs(obj['certifies_current_build'],False)
    def test_demo_cli_can_never_claim_live_readiness(self):
        proc=subprocess.run([sys.executable,'-m','anka_app.cli','protocol-demo'],cwd=ROOT,
          capture_output=True,text=True,timeout=25)
        self.assertEqual(proc.returncode,0,proc.stdout+'\n'+proc.stderr)
        report=json.loads(next(x.split('=',1)[1] for x in proc.stdout.splitlines() if x.startswith('ANKA_RESULT=')))
        self.assertFalse(report['live_ready']);self.assertFalse(report['gameplay_capabilities_certified'])
        self.assertEqual(report['canonical_events_emitted'],0)
        self.assertFalse(report['physical_input_sent'])
    def test_protocol_audit_without_build_is_blocked_with_diagnostic(self):
        proc=subprocess.run([sys.executable,'-m','anka_app.cli','protocol-audit'],cwd=ROOT,
          capture_output=True,text=True,timeout=25)
        self.assertEqual(proc.returncode,40)
        self.assertIn('ANKA_FAILURE=PROTOCOL_AUDIT_REQUIRES_PATH_AND_EXACT_BUILD',proc.stdout)
        self.assertIn('ANKA_BUNDLE=',proc.stdout)

if __name__=='__main__':unittest.main()
