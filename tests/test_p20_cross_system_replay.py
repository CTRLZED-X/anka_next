"""P20 cross-system fault injection and minimal operator surface."""
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from anka_app.integrated_offline import run_integrated_fixture, CASES
from anka_app.cli import ROOT
from anka_contracts.execution_flow import OfflineActionIntent
from anka_contracts.coordination_flow import PartyTimelineReport
from anka_execution.fake_input import OfflineFakeInputDriver
from anka_observability.api import LocalDiagnostics


class TestP20CrossSystemReplay(unittest.TestCase):
    def run_case(self, case):
        return run_integrated_fixture(ROOT, scenario=case)

    def test_happy_handoff_is_explicitly_synthetic(self):
        report = self.run_case('handoff')
        self.assertEqual(report['status'], 'SYNTHETIC_REPLAY_PASS')
        self.assertEqual(report['state_audit'], 'PASS')
        self.assertEqual(report['party']['status'], 'TURN_ACTIVE')
        self.assertEqual(report['party']['turn_owner'], 888)
        self.assertEqual(report['ledger_status'], 'CONFIRMED')
        self.assertEqual(report['workflow']['synthetic_wins'], 0)
        self.assertEqual(report['workflow']['status'], 'WAITING_FOR_SYNTHETIC_EVIDENCE')
        self.assertEqual(report['fake_attempts'], 1)
        self.assertEqual(report['decision']['status'], 'RESEARCH_ONLY')
        self.assertFalse(report['decision']['actionable'])
        self.assertFalse(report['authoritative'])
        self.assertFalse(report['actionable'])
        self.assertFalse(report['physical_input_sent'])
        self.assertFalse(report['live_ready'])
        self.assertEqual(report['boundaries'], [
            'canonical.audit', 'live_state.replay', 'coordination.replay',
            'workflow.outcome_accounting', 'integration.source_link_audit',
            'decision.kernel_research',
            'execution.fake_dispatch', 'execution.ledger_audit'])

    def test_blocked_coordination_never_enters_fake_execution(self):
        for case in ('missing-end-confirmation', 'conflicting-owner',
                     'stale-enu-state', 'wrong-fight'):
            with self.subTest(case=case):
                report = self.run_case(case)
                self.assertEqual(report['status'], 'BLOCKED_SYNTHETIC')
                self.assertTrue(report['first_failure'])
                self.assertEqual(report['fake_attempts'], 0)
                self.assertIsNone(report['execution'])
                self.assertNotIn('execution.fake_dispatch', report['boundaries'])
                self.assertFalse(report['physical_input_sent'])

    def test_missing_turn_end_cannot_be_repaired_by_later_enu_start(self):
        report = self.run_case('missing-end-confirmation')
        self.assertEqual(report['first_failure'], 'P17_OVERLAPPING_OR_EARLY_TURN')
        self.assertEqual(report['party']['first_failed_sequence'], 6)
        self.assertEqual(report['party']['status'], 'QUARANTINED')

    def test_false_reconciled_state_does_not_pass_on_party_claim_alone(self):
        self.assertIn('P20_CRA_TURN_STILL_ACTIVE', self.run_case('conflicting-owner')['reasons'])
        self.assertIn('P20_ENU_TURN_NOT_RECONCILED', self.run_case('stale-enu-state')['reasons'])
        self.assertIn('P20_ENU_STATE_SCOPE_MISMATCH', self.run_case('wrong-fight')['reasons'])

    def test_post_dispatch_faults_remain_uncertain_and_do_not_retry(self):
        for case, count, reason in [
            ('focus-lost', 0, 'P19_WINDOW_FOCUS_NOT_VERIFIED'),
            ('missing-outcome', 1, 'P19_NO_INDEPENDENT_OUTCOME_EVIDENCE'),
            ('driver-raises-after', 1, 'P19_FAKE_DRIVER_RAISED_AFTER_POSSIBLE_ATTEMPT')]:
            with self.subTest(case=case):
                report = self.run_case(case)
                self.assertEqual(report['first_failure'], reason)
                self.assertIn('P20_DISPATCH_UNCERTAIN', report['reasons'])
                self.assertEqual(report['ledger_status'], 'DISPATCH_UNCERTAIN')
                self.assertEqual(report['fake_attempts'], count)
                self.assertFalse(report['physical_input_sent'])

    def test_duplicate_action_cannot_reach_driver_twice(self):
        report = self.run_case('duplicate-dispatch')
        self.assertEqual(report['fake_attempts'], 1)
        self.assertIn('execution.duplicate_rejected', report['boundaries'])
        self.assertEqual(report['ledger_status'], 'CONFIRMED')

    def test_unknown_scenario_cannot_become_operator_input(self):
        with self.assertRaisesRegex(ValueError, 'P20_UNKNOWN_SCENARIO'):
            run_integrated_fixture(ROOT, scenario='real')
        self.assertEqual(len(CASES), 12)

    def test_no_external_driver_or_raw_input_port(self):
        import inspect
        sig = inspect.signature(run_integrated_fixture)
        self.assertEqual(list(sig.parameters), ['root', 'scenario', 'observer'])
        self.assertNotIn('driver', sig.parameters)
        self.assertNotIn('live_adapter', sig.parameters)

    def test_observer_records_exact_failure_without_raw_packets(self):
        with tempfile.TemporaryDirectory() as temp:
            observer = LocalDiagnostics(Path(temp))
            result = run_integrated_fixture(ROOT, scenario='focus-lost', observer=observer)
            self.assertEqual(result['first_failure'], 'P19_WINDOW_FOCUS_NOT_VERIFIED')
            observer.finish('BLOCKED')
            events = [json.loads(line) for line in (observer.folder/'events.jsonl').read_text().splitlines()]
            self.assertTrue(any(e['event_name'] == 'integration.p20_replay_completed' for e in events))
            self.assertTrue(any(e['payload'].get('first_failure') == 'P19_WINDOW_FOCUS_NOT_VERIFIED'
                                for e in events))
            self.assertTrue(list((observer.folder/'incidents').glob('*.zip')))

    def test_only_two_operator_bat_launchers(self):
        self.assertEqual({p.name for p in ROOT.glob('*.bat')}, {'setup.bat', 'start.bat'})
        for name in ('setup.bat', 'start.bat'):
            self.assertIn('tools\\windows\\_entry.bat', (ROOT/name).read_text())
        entry = (ROOT/'tools/windows/_entry.bat').read_text()
        self.assertIn('cd /d "%~dp0..\\.."', entry)
        self.assertIn('ANKA_BOOTLOG', entry)

    def test_setup_smoke_does_not_export_expected_fault_as_incident(self):
        from anka_app.cli import _cross_system_smoke
        with tempfile.TemporaryDirectory() as temp:
            observer = LocalDiagnostics(Path(temp))
            result = _cross_system_smoke(observer)
            self.assertEqual(result['status'], 'PASS_SYNTHETIC_ONLY')
            self.assertFalse(list(observer.folder.glob('*.zip')))
            self.assertFalse(result['physical_input_sent'])

    def test_smoke_fails_closed_on_regression(self):
        from anka_app.cli import _cross_system_smoke
        with tempfile.TemporaryDirectory() as temp:
            observer = LocalDiagnostics(Path(temp))
            with patch('anka_app.integrated_offline.run_integrated_fixture',
                       return_value={'status': 'SYNTHETIC_REPLAY_PASS',
                                     'fake_attempts': 1, 'physical_input_sent': True}):
                with self.assertRaisesRegex(RuntimeError, 'P20_INTEGRATION_SMOKE_FAILED'):
                    _cross_system_smoke(observer)

    def test_developer_tests_still_exist_without_bat_wrappers(self):
        self.assertTrue((ROOT/'tests/test_p19_offline_fake_driver.py').exists())
        self.assertTrue((ROOT/'src/anka_app/cli.py').exists())
        self.assertTrue((ROOT/'src/anka_app/integrated_offline.py').exists())


if __name__ == '__main__':
    unittest.main()
