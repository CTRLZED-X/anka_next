"""P21 invariant tests: coupling changes and fictional live readiness fail closed."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anka_app.architecture_guard import SYSTEM_IMPORTS, audit_source_boundaries
from anka_app.readiness import assess_live_readiness
from anka_app.cli import ROOT, _architecture_check, _readiness_check, _command
from anka_observability.api import LocalDiagnostics


class TestP21Architecture(unittest.TestCase):
    def test_full_project_current_boundaries(self):
        result = audit_source_boundaries(ROOT / 'src')
        self.assertEqual(result.status, 'PASS', result.violations)
        self.assertEqual(result.packages, len(SYSTEM_IMPORTS))
        self.assertGreater(result.modules, 180)

    def test_kernel_does_not_depend_on_app(self):
        self.assertEqual(SYSTEM_IMPORTS['anka_game_kernel'], frozenset())
        self.assertEqual(SYSTEM_IMPORTS['anka_contracts'], frozenset())
        self.assertEqual(SYSTEM_IMPORTS['anka_execution'], {'anka_contracts'})
        self.assertNotIn('anka_execution', SYSTEM_IMPORTS['anka_decision'])
        self.assertNotIn('anka_decision', SYSTEM_IMPORTS['anka_execution'])

    def _copy_policy_layout(self, folder: Path):
        src = folder / 'src'
        for package in SYSTEM_IMPORTS:
            (src / package).mkdir(parents=True)
            (src / package / '__init__.py').write_text('', encoding='utf-8')
        return src

    def test_static_forbidden_dependency(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._copy_policy_layout(Path(d))
            (src / 'anka_protocol' / 'unsafe.py').write_text('from anka_execution.ledger import OfflineExecutionLedger\n')
            report = audit_source_boundaries(src)
            self.assertEqual(report.status, 'FAIL')
            self.assertTrue(any('anka_protocol->anka_execution' in x for x in report.violations))

    def test_multiline_and_nested_imports_detected(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._copy_policy_layout(Path(d))
            (src / 'anka_client' / 'unsafe.py').write_text('def f():\n    import anka_decision\n')
            self.assertTrue(any('ARCH_FORBIDDEN_IMPORT' in x for x in audit_source_boundaries(src).violations))

    def test_constant_dynamic_imports_detected(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._copy_policy_layout(Path(d))
            (src / 'anka_protocol' / 'unsafe.py').write_text('''import importlib
x = importlib.import_module('anka_execution.ledger')
y = __import__('anka_client.discovery')
''')
            failures = audit_source_boundaries(src).violations
            self.assertEqual(len([f for f in failures if f.startswith('ARCH_FORBIDDEN_IMPORT')]), 2)

    def test_unknown_new_package_needs_policy_review(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._copy_policy_layout(Path(d))
            (src / 'anka_newservice').mkdir()
            (src / 'anka_newservice' / '__init__.py').write_text('')
            self.assertIn('ARCH_UNREVIEWED_PACKAGE:anka_newservice', audit_source_boundaries(src).violations)

    def test_missing_package_is_not_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._copy_policy_layout(Path(d))
            (src / 'anka_execution' / '__init__.py').unlink()
            (src / 'anka_execution').rmdir()
            self.assertIn('ARCH_PACKAGE_MISSING:anka_execution', audit_source_boundaries(src).violations)

    def test_invalid_python_never_counts_as_compliant(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._copy_policy_layout(Path(d))
            (src / 'anka_protocol' / 'broken.py').write_text('def invalid(\n')
            self.assertTrue(any('ARCH_SOURCE_UNREADABLE:' in f for f in audit_source_boundaries(src).violations))

    def test_relative_import_escape_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._copy_policy_layout(Path(d))
            (src / 'anka_protocol' / 'escape.py').write_text('from ..anka_execution import ledger\n')
            self.assertTrue(any('ARCH_RELATIVE_ESCAPE' in f for f in audit_source_boundaries(src).violations))

    def test_allowed_kernel_import_from_decision(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._copy_policy_layout(Path(d))
            (src / 'anka_decision' / 'correct.py').write_text('from anka_game_kernel.api.kernel import GameKernel\n')
            self.assertEqual(audit_source_boundaries(src).status, 'PASS')


class TestP21LiveReadiness(unittest.TestCase):
    def test_research_cannot_be_promoted_by_flags(self):
        report = assess_live_readiness().to_dict()
        self.assertEqual(report['status'], 'LIVE_BLOCKED')
        self.assertFalse(report['physical_input_enabled'])
        self.assertFalse(report['live_ready'])
        self.assertFalse(report['current_build_certified'])
        self.assertGreaterEqual(len(report['blockers']), 7)

    def test_no_dangerous_configurable_enabler(self):
        import inspect
        self.assertEqual(len(inspect.signature(assess_live_readiness).parameters), 0)

    def test_two_operator_commands_remain(self):
        self.assertEqual({p.name for p in ROOT.glob('*.bat')}, {'setup.bat', 'start.bat'})

    def test_setup_records_architecture_and_readiness_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            observer = LocalDiagnostics(Path(d))
            report = _command('setup', observer, [])
            self.assertEqual(report['architecture']['status'], 'PASS')
            self.assertFalse(report['readiness']['live_ready'])
            self.assertEqual(report['integration_smoke']['status'], 'PASS_SYNTHETIC_ONLY')
            observer.finish('CLOSED')
            events = [json.loads(x) for x in (observer.folder / 'events.jsonl').read_text().splitlines()]
            names = {x['event_name'] for x in events}
            self.assertIn('architecture.boundaries_checked', names)
            self.assertIn('readiness.live_capabilities_blocked', names)

    def test_complete_historical_regression_matrix_is_checked_offline(self):
        from anka_app.cli import _cross_system_smoke
        with tempfile.TemporaryDirectory() as d:
            observer = LocalDiagnostics(Path(d))
            report = _cross_system_smoke(observer, full=True)
            self.assertEqual(report['scenarios_checked'], 12)
            self.assertEqual(report['blocked_faults_verified'], 10)
            self.assertFalse(report['physical_input_sent'])
            observer.finish('CLOSED')

    def test_start_records_blockers_before_live_refusal(self):
        with tempfile.TemporaryDirectory() as d:
            observer = LocalDiagnostics(Path(d))
            with self.assertRaisesRegex(RuntimeError, 'START_WINDOWS_REQUIRED'):
                _command('start', observer, [])
            observer.finish('BLOCKED')
            events = [json.loads(x) for x in (observer.folder / 'events.jsonl').read_text().splitlines()]
            readiness = [x for x in events if x['event_name'] == 'readiness.live_capabilities_blocked']
            self.assertEqual(len(readiness), 1)
            self.assertIn('CURRENT_CLIENT_SEMANTIC_ADAPTER_UNCERTIFIED', readiness[0]['payload']['blockers'])

    def test_guard_failure_prevents_setup_success(self):
        with tempfile.TemporaryDirectory() as d:
            observer = LocalDiagnostics(Path(d))
            with patch('anka_app.architecture_guard.audit_source_boundaries') as audit:
                from anka_app.architecture_guard import ArchitectureAudit
                audit.return_value = ArchitectureAudit(13, 1, ('ARCH_FORBIDDEN_IMPORT:fake',))
                with self.assertRaisesRegex(RuntimeError, 'ARCHITECTURE_BOUNDARY_VIOLATION'):
                    _architecture_check(observer)
            observer.finish('BLOCKED')
            events = [json.loads(x) for x in (observer.folder / 'events.jsonl').read_text().splitlines()]
            self.assertTrue(any(x.get('failure_code') == 'ARCHITECTURE_BOUNDARY_VIOLATION' for x in events))

    def test_blocked_readiness_is_not_a_safety_permission(self):
        with tempfile.TemporaryDirectory() as d:
            observer = LocalDiagnostics(Path(d))
            report = _readiness_check(observer)
            self.assertFalse(report['physical_input_enabled'])
            self.assertIn('REAL_CRA_ENU_END_TO_END_ACCEPTANCE_NOT_COMPLETED', report['blockers'])
            observer.finish('CLOSED')


if __name__ == '__main__':
    unittest.main()
