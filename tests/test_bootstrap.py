import subprocess
import tempfile
from pathlib import Path
import sys
import unittest
from anka_observability.bundle import verify_incident
from anka_app.cli import ROOT

class TestEarlyFailure(unittest.TestCase):
    def test_stdlib_only_dependency_failure_bundle(self):
        with tempfile.TemporaryDirectory() as td:
            p=subprocess.run([sys.executable,str(ROOT/'tools/bootstrap_failure.py'),'DEPENDENCY_INSTALL_FAILED'],
                             cwd=td,capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,0,p.stderr)
            line=next(s for s in p.stdout.splitlines() if s.startswith('ANKA_BOOTSTRAP_BUNDLE='))
            file=Path(line.partition('=')[2])
            self.assertTrue(file.is_file())
            self.assertEqual(verify_incident(file)['status'],'PASS')
