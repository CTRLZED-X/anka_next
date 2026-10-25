import ast
import json
from pathlib import Path
import subprocess
import sys
import unittest
from anka_app.cli import ROOT,_manifest_check

class TestFoundation(unittest.TestCase):
    def test_reused_kernel_available_without_legacy_platform(self):
        import anka_game_kernel
        self.assertTrue(hasattr(anka_game_kernel,'GameKernel'))
        self.assertTrue((ROOT/'src/anka_game_kernel/data/spell_mechanics/verified_spells.json').exists())
        self.assertEqual(_manifest_check()['integrity'],'PASS')
    def test_all_proposed_packages_are_separate(self):
        for name in ('capture','protocol','canonical','live_state','decision','execution','coordination','workflow','client','observability'):
            self.assertTrue((ROOT/'src'/f'anka_{name}'/'__init__.py').is_file())
    def test_kernel_not_dependent_on_app(self):
        for f in (ROOT/'src/anka_game_kernel').rglob('*.py'):
            tree=ast.parse(f.read_text())
            imports=[getattr(x,'module','') or '' for x in ast.walk(tree) if isinstance(x,ast.ImportFrom)]
            self.assertFalse(any(s.startswith(('anka_app','anka_observability','anka_execution')) for s in imports),f.name)
    def test_start_safely_blocked_and_exported(self):
        proc=subprocess.run([sys.executable,'-m','anka_app.cli','start'],cwd=ROOT,capture_output=True,text=True,timeout=25)
        self.assertEqual(proc.returncode,40)
        self.assertIn('ANKA_FAILURE=START_WINDOWS_REQUIRED',proc.stdout)
        lines=dict(line.split('=',1) for line in proc.stdout.splitlines() if '=' in line)
        self.assertTrue(Path(lines['ANKA_BUNDLE']).exists())
    def test_synthetic_replay_never_physically_sends(self):
        proc=subprocess.run([sys.executable,'-m','anka_app.cli','replay'],cwd=ROOT,capture_output=True,text=True,timeout=25)
        self.assertEqual(proc.returncode,0)
        self.assertIn('"physical_input_sent": false',proc.stdout)
    def test_no_real_input_drivers_in_foundation(self):
        # Inspect executable syntax rather than raw source text: architecture and
        # diagnostic code is allowed to *name* forbidden APIs when auditing them,
        # but it must never import or invoke those APIs outside anka_execution.
        risky_modules={'pyautogui','win32api','win32gui','pynput'}
        risky_calls={'SendInput','SetCursorPos','mouse_event','keybd_event'}
        for dirname in ('anka_app','anka_observability','anka_contracts'):
            for path in (ROOT/'src'/dirname).rglob('*.py'):
                tree=ast.parse(path.read_text(),filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node,ast.Import):
                        for item in node.names:
                            self.assertNotIn(item.name.split('.')[0],risky_modules,path.name)
                    elif isinstance(node,ast.ImportFrom):
                        self.assertNotIn((node.module or '').split('.')[0],risky_modules,path.name)
                    elif isinstance(node,ast.Call):
                        name=node.func.id if isinstance(node.func,ast.Name) else node.func.attr if isinstance(node.func,ast.Attribute) else None
                        self.assertNotIn(name,risky_calls,path.name)
                    elif isinstance(node,ast.Attribute) and node.attr=='windll' and isinstance(node.value,ast.Name) and node.value.id=='ctypes':
                        self.fail(f'ctypes.windll executable access in {path.name}')
