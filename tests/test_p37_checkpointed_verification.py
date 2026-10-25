"""P37: no prior PASS survives changed test inputs; unfinished runs remain partial."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from anka_app.verification_runner import (
    VerificationRejected, verification_fingerprint, verify_isolated)


class TestP37CheckpointedVerification(unittest.TestCase):
    @staticmethod
    def project(root: Path, count: int = 3):
        (root/'src').mkdir()
        (root/'tests').mkdir()
        for i in range(count):
            (root/'tests'/f'test_mod_{i}.py').write_text(
                'import unittest\nclass TestTrue(unittest.TestCase):\n'
                '    def test_ok(self): self.assertTrue(True)\n', encoding='utf8')
        (root/'config').mkdir()
        (root/'config'/'user.json').write_text('{"schema_version": 1}',encoding='utf8')
        (root/'src'/'baseline.py').write_text('X = 1\n',encoding='utf8')

    def test_complete_checkpoint_and_reuse_without_rerun(self):
        with TemporaryDirectory() as d:
            root=Path(d);self.project(root)
            check=root/'runtime'/'checkpoint.json'
            good=verify_isolated(root,shards=2,module_isolation=True,checkpoint_path=check)
            self.assertEqual((good.tests_passed,good.resumed_modules),(3,0))
            self.assertEqual(len(json.loads(check.read_text())['completed']),3)
            def must_not_run(*args,**kwargs):
                raise AssertionError('checkpointed module incorrectly rerun')
            cached=verify_isolated(root,shards=2,module_isolation=True,
                                   checkpoint_path=check,run=must_not_run)
            self.assertEqual((cached.tests_passed,cached.resumed_modules),(3,3))
            self.assertEqual(cached.status,'PASS')
            self.assertEqual(good.input_fingerprint,cached.input_fingerprint)

    def test_interrupted_execution_remembers_only_completed_modules(self):
        with TemporaryDirectory() as d:
            root=Path(d);self.project(root);check=root/'runtime'/'checkpoint.json'
            call=[0]
            def interrupt_second(*args,**kwargs):
                call[0]+=1
                if call[0]==2:
                    raise subprocess.TimeoutExpired(args[0],kwargs['timeout'],stderr=b'next-module-stuck')
                return subprocess.run(*args,**kwargs)
            with self.assertRaises(VerificationRejected) as c:
                verify_isolated(root,shards=2,module_isolation=True,
                                checkpoint_path=check,run=interrupt_second)
            self.assertEqual(c.exception.code,'OFFLINE_TEST_SUITE_TIMEOUT')
            self.assertEqual(c.exception.completed,1)
            self.assertEqual(len(json.loads(check.read_text())['completed']),1)
            result=verify_isolated(root,shards=2,module_isolation=True,checkpoint_path=check)
            self.assertEqual((result.tests_passed,result.resumed_modules),(3,1))

    def test_changed_source_invalidates_all_cached_passes(self):
        with TemporaryDirectory() as d:
            root=Path(d);self.project(root);check=root/'runtime'/'checkpoint.json'
            verify_isolated(root,shards=2,module_isolation=True,checkpoint_path=check)
            (root/'src'/'baseline.py').write_text('X = 2\n',encoding='utf8')
            count=[0]
            def count_calls(*args,**kwargs):
                count[0]+=1
                return subprocess.run(*args,**kwargs)
            result=verify_isolated(root,shards=2,module_isolation=True,
                                   checkpoint_path=check,run=count_calls)
            self.assertEqual(count[0],3)
            self.assertEqual(result.resumed_modules,0)

    def test_changed_configuration_or_fixture_invalidates(self):
        with TemporaryDirectory() as d:
            root=Path(d);self.project(root);check=root/'runtime'/'checkpoint.json'
            verify_isolated(root,shards=2,module_isolation=True,checkpoint_path=check)
            (root/'config'/'user.json').write_text('{"schema_version": 2}',encoding='utf8')
            result=verify_isolated(root,shards=2,module_isolation=True,checkpoint_path=check)
            self.assertEqual(result.resumed_modules,0)
            (root/'examples').mkdir()
            (root/'examples'/'fixture.txt').write_text('added evidence')
            result=verify_isolated(root,shards=2,module_isolation=True,checkpoint_path=check)
            self.assertEqual(result.resumed_modules,0)

    def test_corrupt_checkpoint_is_failure_not_success(self):
        with TemporaryDirectory() as d:
            root=Path(d);self.project(root);check=root/'runtime'/'checkpoint.json'
            check.parent.mkdir();check.write_text('{bad json')
            with self.assertRaisesRegex(VerificationRejected,'VERIFICATION_CHECKPOINT_UNREADABLE'):
                verify_isolated(root,shards=2,module_isolation=True,checkpoint_path=check)

    def test_fake_unknown_and_bad_count_must_not_skip(self):
        with TemporaryDirectory() as d:
            root=Path(d);self.project(root);check=root/'runtime'/'checkpoint.json'
            fp=verification_fingerprint(root)
            check.parent.mkdir()
            for completed in ({'test_not_present':1},{'test_mod_0':0},{'test_mod_0':True},
                              {'test_mod_0':2}):
                check.write_text(json.dumps({'schema_version':1,'input_fingerprint':fp,
                                            'completed':completed}))
                with self.assertRaises(VerificationRejected):
                    verify_isolated(root,shards=2,module_isolation=True,checkpoint_path=check)

    def test_checkpoint_rejects_group_mode(self):
        with TemporaryDirectory() as d:
            root=Path(d);self.project(root)
            with self.assertRaisesRegex(VerificationRejected,'VERIFICATION_CHECKPOINT_REQUIRES_MODULE_ISOLATION'):
                verify_isolated(root,checkpoint_path=root/'runtime'/'checkpoint.json')

    def test_changed_test_file_invalidates_previous_pass(self):
        with TemporaryDirectory() as d:
            root=Path(d);self.project(root);check=root/'runtime'/'checkpoint.json'
            verify_isolated(root,shards=2,module_isolation=True,checkpoint_path=check)
            (root/'tests'/'test_mod_0.py').write_text(
                'import unittest\nclass TestBroken(unittest.TestCase):\n'
                '    def test_broken(self): self.fail("new regression")\n')
            with self.assertRaisesRegex(VerificationRejected,'OFFLINE_TEST_SUITE_FAILED'):
                verify_isolated(root,shards=2,module_isolation=True,checkpoint_path=check)
            self.assertNotEqual(json.loads(check.read_text())['input_fingerprint'],verification_fingerprint(root))


if __name__=='__main__': unittest.main()

class TestP37BoundedExecution(unittest.TestCase):
    def test_batch_status_never_falsely_passes(self):
        with TemporaryDirectory() as d:
            root=Path(d);TestP37CheckpointedVerification.project(root,4)
            state=root/'runtime/state.json'
            partial=verify_isolated(root,shards=2,module_isolation=True,
                                    checkpoint_path=state,max_new_modules=2)
            self.assertEqual(partial.status,'INCOMPLETE')
            self.assertEqual((partial.test_files_executed,partial.test_files_discovered),(2,4))
            final=verify_isolated(root,shards=2,module_isolation=True,
                                  checkpoint_path=state,max_new_modules=2)
            self.assertEqual(final.status,'PASS')
            self.assertEqual(final.resumed_modules,2)
            self.assertEqual(final.tests_passed,4)

    def test_invalid_batches_fail_closed(self):
        with TemporaryDirectory() as d:
            root=Path(d);TestP37CheckpointedVerification.project(root,2)
            with self.assertRaisesRegex(VerificationRejected,'VERIFICATION_BATCH_REQUIRES_CHECKPOINT'):
                verify_isolated(root,module_isolation=True,max_new_modules=1)
            with self.assertRaisesRegex(VerificationRejected,'VERIFICATION_BATCH_LIMIT_INVALID'):
                verify_isolated(root,module_isolation=True,max_new_modules=0,checkpoint_path=root/'runtime/cp.json')

    @unittest.skipIf(__import__('os').name=='nt', 'POSIX process-group cleanup fault injection')
    def test_orphaned_stdout_holder_cannot_extend_successful_parent_lifetime(self):
        from anka_app.verification_runner import run_bounded_tree
        import os,sys,time
        with TemporaryDirectory() as d:
            started=time.monotonic()
            # Parent quits immediately; child inherits stdout/stderr. Pipe-based
            # capture used to wait for the orphan's EOF despite the verified
            # parent already succeeding. The bounded runner must return success
            # and clean the dedicated process group instead.
            script=('import subprocess,sys\n'
                    'subprocess.Popen([sys.executable,"-c","import time;time.sleep(15)"])\n')
            result=run_bounded_tree([sys.executable,'-c',script],cwd=d,env=os.environ.copy(),
                                    text=True,capture_output=True,timeout=1)
            self.assertEqual(result.returncode,0)
            self.assertLess(time.monotonic()-started,6)

    @unittest.skipIf(__import__('os').name=='nt', 'POSIX process-group timeout fault injection')
    def test_running_parent_and_descendant_are_killed_on_timeout(self):
        from anka_app.verification_runner import run_bounded_tree
        import os,sys,time
        with TemporaryDirectory() as d:
            started=time.monotonic()
            script=('import subprocess,sys,time\n'
                    'subprocess.Popen([sys.executable,"-c","import time;time.sleep(15)"])\n'
                    'time.sleep(15)\n')
            with self.assertRaises(subprocess.TimeoutExpired):
                run_bounded_tree([sys.executable,'-c',script],cwd=d,env=os.environ.copy(),
                                 text=True,capture_output=True,timeout=1)
            self.assertLess(time.monotonic()-started,6)
