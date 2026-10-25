"""Cross-boundary P8 release checks; no physical-input paths imported."""
from __future__ import annotations
import ast, subprocess,sys, tempfile, unittest
from pathlib import Path
from anka_canonical.journal import SQLiteFixtureJournal, JournalIntegrityError
from anka_live_state.reducer import apply_offline_event
from anka_contracts.state import OfflineStateEvent

ROOT=Path(__file__).resolve().parents[1]

class TestP8Integration(unittest.TestCase):
    def test_live_state_reducer_does_not_import_other_system_internals(self):
        for package in ('anka_live_state','anka_canonical'):
            for file in (ROOT/'src'/package).rglob('*.py'):
                tree=ast.parse(file.read_text(encoding='utf8'))
                for node in ast.walk(tree):
                    if isinstance(node,ast.ImportFrom) and node.module:
                        self.assertFalse(node.module.startswith(('anka_protocol','anka_capture','anka_execution','anka_app','anka_client','anka_coordination','anka_workflow')),f'{file} imported {node.module}')
    def test_cli_demo_status_no_game_input(self):
        env=__import__('os').environ.copy();env['PYTHONPATH']=str(ROOT/'src')
        p=subprocess.run([sys.executable,'-m','anka_app.cli','state-demo'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=25)
        self.assertEqual(p.returncode,0,p.stderr+'\n'+p.stdout)
        self.assertIn('ANKA_STATUS=SYNTHETIC_STATE_ONLY',p.stdout)
        self.assertIn('"physical_input_sent": false',p.stdout)
        self.assertIn('"actionable": false',p.stdout)
    def test_state_audit_cli_missing_db_is_fail_closed(self):
        env=__import__('os').environ.copy();env['PYTHONPATH']=str(ROOT/'src')
        p=subprocess.run([sys.executable,'-m','anka_app.cli','state-audit','missing-p8-fixture.sqlite3'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=25)
        self.assertEqual(p.returncode,40,p.stdout)
        self.assertIn('ANKA_STATUS=BLOCKED',p.stdout)
    def test_start_still_refuses_live(self):
        env=__import__('os').environ.copy();env['PYTHONPATH']=str(ROOT/'src')
        p=subprocess.run([sys.executable,'-m','anka_app.cli','start'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=25)
        self.assertEqual(p.returncode,40,p.stdout)
        self.assertIn('START_WINDOWS_REQUIRED',p.stdout)
    def test_live_draft_not_automatically_promoted(self):
        src=(ROOT/'src/anka_app/state_offline.py').read_text()
        self.assertNotIn('CanonicalDraft',src)
        self.assertNotIn('SemanticResult',src)
        self.assertIn('SYNTHETIC_FIXTURE_ONLY',(ROOT/'src/anka_contracts/state.py').read_text())

if __name__=='__main__':unittest.main()
