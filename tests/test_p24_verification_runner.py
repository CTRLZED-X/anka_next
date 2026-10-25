"""P24: Isolated release verification is itself adversarially verified."""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from anka_app.verification_runner import discover_shards, verify_isolated, verification_fingerprint, VerificationRejected
from anka_app.cli import ROOT, _command


class TestP24VerificationRunner(unittest.TestCase):
    def make_project(self, root: Path, *, modules: int = 3):
        (root/'tests').mkdir()
        (root/'src').mkdir()
        for n in range(modules):
            (root/'tests'/f'test_case_{n}.py').write_text(
                'import unittest\nclass Unit(unittest.TestCase):\n'
                '    def test_truth(self): self.assertTrue(True)\n', encoding='utf8')

    def test_checkpoint_fingerprint_covers_release_identity_manifest_and_windows_capture_contract(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.make_project(root,modules=1)
            names=('PROJECT_INFO.txt','requirements-windows-capture.txt','RELEASE_MANIFEST.json')
            for name in names:
                target=root/name
                target.write_text('generation-a\n',encoding='utf8')
                before=verification_fingerprint(root)
                target.write_text('generation-b\n',encoding='utf8')
                after=verification_fingerprint(root)
                self.assertNotEqual(before,after,name)

    def test_original_inventory_fully_covered_once(self):
        groups=discover_shards(ROOT/'tests')
        names=[n for group in groups for n in group]
        expected={p.stem for p in (ROOT/'tests').glob('test_*.py')}
        self.assertEqual(set(names),expected)
        self.assertEqual(len(names),len(set(names)))
        self.assertEqual(len(groups),8)

    def test_isolated_real_subprocesses(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.make_project(root)
            result=verify_isolated(root,shards=2,per_shard_timeout=20)
            self.assertEqual(result.test_files_discovered,3)
            self.assertEqual(result.test_files_executed,3)
            self.assertEqual(result.shards_completed,2)
            self.assertEqual(result.tests_passed,3)
            self.assertFalse(result.to_dict()['physical_input_sent'])

    def test_timeout_returns_exact_shard_and_last_started_test(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.make_project(root,modules=1)
            def fake(*args,**kwargs):
                raise subprocess.TimeoutExpired('unittest',kwargs['timeout'],stderr=b'test_last_started ...')
            with self.assertRaises(VerificationRejected) as error:
                verify_isolated(root,run=fake)
            self.assertEqual(error.exception.code,'OFFLINE_TEST_SUITE_TIMEOUT')
            self.assertEqual(error.exception.shard,1)
            self.assertIn('test_last_started',error.exception.output)

    def test_zero_tests_is_not_success(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.make_project(root,modules=1)
            def fake(*args,**kwargs):
                return subprocess.CompletedProcess(args[0],0,'','Ran 0 tests in 0.000s\n\nOK\n')
            with self.assertRaisesRegex(VerificationRejected,'OFFLINE_TEST_SUITE_FAILED'):
                verify_isolated(root,run=fake)

    def test_failed_test_is_not_success(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.make_project(root,modules=1)
            def fake(*args,**kwargs):
                return subprocess.CompletedProcess(args[0],1,'','Ran 1 test in 0.001s\n\nFAILED (failures=1)\n')
            with self.assertRaisesRegex(VerificationRejected,'OFFLINE_TEST_SUITE_FAILED'):
                verify_isolated(root,run=fake)

    def test_unexpected_no_completion_marker_is_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.make_project(root,modules=1)
            def fake(*args,**kwargs):
                return subprocess.CompletedProcess(args[0],0,'','OK\n')
            with self.assertRaisesRegex(VerificationRejected,'OFFLINE_TEST_SUITE_FAILED'):
                verify_isolated(root,run=fake)

    def test_invalid_test_source_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.make_project(root)
            (root/'tests'/'test_case_1.py').write_text('def invalid(\n')
            with self.assertRaisesRegex(VerificationRejected,'VERIFICATION_TEST_SOURCE_INVALID'):
                discover_shards(root/'tests')

    def test_empty_test_module_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.make_project(root)
            (root/'tests'/'test_case_1.py').write_text('print("no tests")\n')
            with self.assertRaisesRegex(VerificationRejected,'VERIFICATION_EMPTY_TEST_MODULE'):
                discover_shards(root/'tests')

    def test_silent_undercollection_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.make_project(root,modules=3)
            def fake(*args,**kwargs):
                return subprocess.CompletedProcess(args[0],0,'','Ran 1 test in 0.001s\n\nOK\n')
            with self.assertRaisesRegex(VerificationRejected,'OFFLINE_TEST_SUITE_FAILED'):
                verify_isolated(root,shards=1,run=fake)

    def test_started_shard_is_recorded_before_subprocess_timeout(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.make_project(root,modules=1)
            started=[]
            def fake(*args,**kwargs):
                raise subprocess.TimeoutExpired('unittest',20,stderr=b'test_last ...')
            with self.assertRaises(VerificationRejected):
                verify_isolated(root,run=fake,per_shard_timeout=20,
                                notify_start=lambda n,total,modules:started.append((n,total,modules)))
            self.assertEqual(started,[(1,1,('test_case_0',))])

    def test_missing_inventory_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with self.assertRaisesRegex(VerificationRejected,'VERIFICATION_TEST_DIRECTORY_MISSING'):
                discover_shards(root/'tests')

    def test_cli_diagnostics_identify_failed_shard(self):
        class Sink:
            def __init__(self):self.events=[]
            def record(self,*args,**kwargs):self.events.append((args,kwargs))
        sink=Sink()
        error=VerificationRejected('OFFLINE_TEST_SUITE_FAILED',shard=3,
            modules=('test_p22_causal_linkage',),output='test_failure_case ... FAIL',completed=13)
        with patch('anka_app.cli._preflight',return_value={}),patch('anka_app.verification_runner.verify_isolated',side_effect=error):
            with self.assertRaisesRegex(RuntimeError,'OFFLINE_TEST_SUITE_FAILED'):
                _command('verify',sink,[])
        failure=[(a,k) for a,k in sink.events if a[0]=='verification.suite_failed']
        self.assertEqual(len(failure),1)
        self.assertEqual(failure[0][1]['payload']['shard'],3)
        self.assertIn('test_failure_case',failure[0][1]['payload']['last_test_output'])


if __name__=='__main__':unittest.main()
