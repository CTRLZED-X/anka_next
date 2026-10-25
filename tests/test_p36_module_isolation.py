"""P36: exhaustive per-test-module process isolation regression."""
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import unittest
from anka_app.verification_runner import verify_isolated, VerificationRejected


class TestP36ModuleIsolation(unittest.TestCase):
    def fixtures(self,root):
        (root/'tests').mkdir();(root/'src').mkdir()
        for n in range(3):
            (root/'tests'/f'test_demo_{n}.py').write_text(
                'import unittest\nclass Truth(unittest.TestCase):\n'
                ' def test_state(self): self.assertTrue(True)\n')

    def test_each_module_has_its_own_subprocess(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixtures(root); seen=[]
            result=verify_isolated(root,shards=2,module_isolation=True,
                                   notify_start=lambda n,total,modules:seen.append(modules))
            self.assertEqual(seen, [('test_demo_0',),('test_demo_2',),('test_demo_1',)])
            self.assertEqual(result.tests_passed,3)
            self.assertEqual(result.shards_completed,3)
            self.assertEqual(result.test_files_executed,3)

    def test_grouped_default_unchanged(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixtures(root)
            result=verify_isolated(root,shards=2)
            self.assertEqual(result.shards_completed,2)
            self.assertEqual(result.tests_passed,3)

    def test_single_module_timeout_identifies_exact_file(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixtures(root)
            def timeout(*args,**kw):
                raise subprocess.TimeoutExpired(args[0],kw['timeout'],stderr=b'test_specific_stuck ...')
            with self.assertRaises(VerificationRejected) as ctx:
                verify_isolated(root,shards=2,module_isolation=True,run=timeout)
            self.assertEqual(ctx.exception.code,'OFFLINE_TEST_SUITE_TIMEOUT')
            self.assertEqual(len(ctx.exception.modules),1)
            self.assertIn('test_specific_stuck',ctx.exception.output)

if __name__=='__main__':unittest.main()
