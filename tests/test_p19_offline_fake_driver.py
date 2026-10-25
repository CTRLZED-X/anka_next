"""P19: adversarial, fixture-only execution integration; zero OS input."""
from __future__ import annotations
import ast
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from anka_app.execution_offline import fixture_intent, fixture_evidence
from anka_app.execution_simulation import execution_sim_demo, SCENARIOS
from anka_contracts.execution_flow import OfflineActionIntent
from anka_contracts.execution_simulation import (OfflineWindowObservation,OfflineDriverReceipt,OfflineDispatchReport)
from anka_execution.fake_input import OfflineFakeInputDriver,OfflineWindowFeed,OfflineDriverFailure
from anka_execution.offline_dispatch import OfflineDispatchCoordinator,OfflineDispatchRejected
from anka_execution.ledger import OfflineExecutionLedger,ExecutionLedgerRejected
from anka_execution.settlement import ExecutionTransitionRejected


class P19Case(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(prefix='anka-p19-test-')
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'actions.sqlite3'
        self.ledger=OfflineExecutionLedger(self.path)
        self.intent=fixture_intent('p19-test-a1')
        self.window=OfflineWindowObservation('cra','window-1',1,True,True,True)

    def runtime(self,*,mode='simulated-input',windows=None,ledger=None):
        driver=OfflineFakeInputDriver(mode)
        runner=OfflineDispatchCoordinator(ledger or self.ledger,driver,
             OfflineWindowFeed(*(windows or (self.window,self.window))))
        return runner, driver

    def test_good_dispatch_never_confirms_without_proof(self):
        runtime,driver=self.runtime()
        rep=runtime.run(self.intent)
        self.assertEqual(rep.action_status,'DISPATCH_UNCERTAIN')
        self.assertEqual(rep.reason,'P19_NO_INDEPENDENT_OUTCOME_EVIDENCE')
        self.assertEqual(driver.attempt_count,1)
        self.assertEqual(self.ledger.audit_all()[0].event_count,2)
        self.assertFalse(rep.physical_input_sent)

    def test_separate_fixture_evidence_settles(self):
        runtime,driver=self.runtime()
        rep=runtime.run(self.intent,evidence=fixture_evidence(self.intent,evidence_id='p19-ev-1'))
        self.assertEqual(rep.action_status,'CONFIRMED')
        self.assertEqual(rep.evidence_ids,('p19-ev-1',))
        self.assertEqual(self.ledger.audit_all()[0].event_count,3)
        self.assertFalse(rep.actionable)

    def test_negative_evidence_settles_rejected(self):
        runtime,_=self.runtime()
        ev=fixture_evidence(self.intent,'REJECTED',evidence_id='p19-ev-r')
        self.assertEqual(runtime.run(self.intent,evidence=ev).action_status,'REJECTED')

    def test_inconclusive_remains_uncertain(self):
        runtime,_=self.runtime()
        ev=fixture_evidence(self.intent,'INCONCLUSIVE',evidence_id='p19-ev-inc')
        self.assertEqual(runtime.run(self.intent,evidence=ev).action_status,'DISPATCH_UNCERTAIN')

    def test_preflight_defects_cancel_without_driver(self):
        defects=(
            (replace(self.window,account_id='enu'),'P19_WINDOW_ACCOUNT_MISMATCH'),
            (replace(self.window,client_id='other'),'P19_WINDOW_ACCOUNT_MISMATCH'),
            (replace(self.window,window_generation=2),'P19_WINDOW_GENERATION_CHANGED'),
            (replace(self.window,character_verified=False),'P19_CHARACTER_NOT_VERIFIED'),
            (replace(self.window,foreground_verified=False),'P19_WINDOW_FOCUS_NOT_VERIFIED'),
            (replace(self.window,calibration_verified=False),'P19_CALIBRATION_NOT_VERIFIED'),
        )
        for n,(w,reason) in enumerate(defects):
            with self.subTest(reason=reason,n=n):
                path=Path(self.tmp.name)/f'pre-{n}.sqlite3'
                runtime,drv=self.runtime(windows=(w,w),ledger=OfflineExecutionLedger(path))
                report=runtime.run(self.intent)
                self.assertEqual((report.action_status,report.boundary,report.reason),
                                 ('CANCELLED','PRE_DISPATCH',reason))
                self.assertEqual(drv.attempt_count,0)
                self.assertEqual(OfflineExecutionLedger(path,read_only=True).audit_all()[0].event_count,2)

    def test_window_change_after_boundary_stays_uncertain(self):
        for n,(w,reason) in enumerate((
            (replace(self.window,account_id='enu'),'P19_WINDOW_ACCOUNT_MISMATCH'),
            (replace(self.window,window_generation=2),'P19_WINDOW_GENERATION_CHANGED'),
            (replace(self.window,foreground_verified=False),'P19_WINDOW_FOCUS_NOT_VERIFIED'),
            (replace(self.window,character_verified=False),'P19_CHARACTER_NOT_VERIFIED'),
            (replace(self.window,calibration_verified=False),'P19_CALIBRATION_NOT_VERIFIED'),
        )):
            with self.subTest(reason=reason,n=n):
                path=Path(self.tmp.name)/f'post-{n}.sqlite3'
                runtime,drv=self.runtime(windows=(self.window,w),ledger=OfflineExecutionLedger(path))
                rep=runtime.run(self.intent)
                self.assertEqual((rep.action_status,rep.boundary,rep.reason),
                                  ('DISPATCH_UNCERTAIN','POST_DISPATCH',reason))
                self.assertEqual(drv.attempt_count,0)

    def test_crash_between_prepare_and_send(self):
        runtime,driver=self.runtime()
        with self.assertRaisesRegex(OfflineDriverFailure,'P19_INJECTED_CRASH_AFTER_PREPARE'):
            runtime.run(self.intent,fault_point='after_prepared')
        self.assertEqual(self.ledger.audit_all()[0].status,'PREPARED')
        self.assertEqual(driver.attempt_count,0)

    def test_crash_after_commit_leaves_uncertainty(self):
        runtime,driver=self.runtime()
        with self.assertRaisesRegex(OfflineDriverFailure,'P19_INJECTED_CRASH_AFTER_BOUNDARY'):
            runtime.run(self.intent,fault_point='after_boundary')
        self.assertEqual(OfflineExecutionLedger(self.path).audit_all()[0].status,'DISPATCH_UNCERTAIN')
        self.assertEqual(driver.attempt_count,0)

    def test_crash_after_fake_attempt_leaves_uncertainty(self):
        runtime,driver=self.runtime()
        with self.assertRaisesRegex(OfflineDriverFailure,'P19_INJECTED_CRASH_AFTER_FAKE_ATTEMPT'):
            runtime.run(self.intent,fault_point='after_fake_attempt')
        self.assertEqual(driver.attempt_count,1)
        self.assertEqual(self.ledger.audit_all()[0].status,'DISPATCH_UNCERTAIN')

    def test_driver_no_input_is_not_auto_cancellation(self):
        runtime,driver=self.runtime(mode='no-input')
        report=runtime.run(self.intent,evidence=fixture_evidence(self.intent,evidence_id='p19-ev-1'))
        self.assertEqual(report.reason,'P19_FAKE_NO_INPUT_NOT_PROOF')
        self.assertEqual(self.ledger.audit_all()[0].status,'DISPATCH_UNCERTAIN')
        self.assertEqual(driver.attempt_count,1)

    def test_driver_exception_does_not_clear_uncertainty(self):
        for scenario in ('raise-before','raise-after'):
            with self.subTest(scenario=scenario):
                path=Path(self.tmp.name)/(scenario+'.sqlite3')
                runtime,drv=self.runtime(mode=scenario,ledger=OfflineExecutionLedger(path))
                report=runtime.run(self.intent)
                self.assertEqual(report.action_status,'DISPATCH_UNCERTAIN')
                self.assertIn('P19_FAKE_DRIVER_RAISED_',report.reason)
                self.assertEqual(drv.attempt_count,1)

    def test_wrong_evidence_never_settles(self):
        runtime,_=self.runtime()
        ev=replace(fixture_evidence(self.intent,evidence_id='p19-ev-bad'),account_id='enu')
        with self.assertRaisesRegex(ExecutionLedgerRejected,'P18_OUTCOME_SCOPE_MISMATCH'):
            runtime.run(self.intent,evidence=ev)
        self.assertEqual(self.ledger.audit_all()[0].status,'DISPATCH_UNCERTAIN')

    def test_duplicate_action_rejected_after_crash(self):
        runtime,_=self.runtime()
        runtime.run(self.intent)
        restarted,drv=self.runtime(ledger=OfflineExecutionLedger(self.path))
        with self.assertRaisesRegex(ExecutionLedgerRejected,'P18_DUPLICATE_ACTION_ID'):
            restarted.run(self.intent)
        self.assertEqual(drv.attempt_count,0)

    def test_second_account_global_uncertain_gate(self):
        runtime,_=self.runtime()
        runtime.run(self.intent)
        next_intent=replace(self.intent,action_id='p19-test-b',action_key='new-turn',
                            client_id='window-2',account_id='enu',window_generation=2,actor_id=888)
        next_window=OfflineWindowObservation('enu','window-2',2,True,True,True)
        runner,drv=self.runtime(windows=(next_window,next_window))
        report = runner.run(next_intent)
        self.assertEqual((report.action_status,report.reason),('CANCELLED','P19_GLOBAL_DISPATCH_BUSY'))
        self.assertEqual(drv.attempt_count,0)
        self.assertEqual(sorted(x.status for x in self.ledger.audit_all()),
                         ['CANCELLED','DISPATCH_UNCERTAIN'])

    def test_parallel_attempts_one_wins(self):
        intent_b=replace(self.intent,action_id='p19-test-b',action_key='turn-b',
                         account_id='enu',client_id='window-2',window_generation=2,actor_id=888)
        win_b=OfflineWindowObservation('enu','window-2',2,True,True,True)
        def worker(intent,win):
            runner,_=self.runtime(windows=(win,win),ledger=OfflineExecutionLedger(self.path))
            try:return runner.run(intent).action_status
            except ExecutionLedgerRejected:return 'REJECTED_BY_GATE'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda item:worker(*item),
                                  [(self.intent,self.window),(intent_b,win_b)]))
        self.assertCountEqual(results,['DISPATCH_UNCERTAIN','CANCELLED'])
        self.assertEqual(sum(x.status=='DISPATCH_UNCERTAIN' for x in self.ledger.audit_all()),1)

    def test_missing_second_identity_snapshot_never_dispatches(self):
        # Previously a single snapshot was silently reused for re-attestation.
        runner,driver=self.runtime(windows=(self.window,))
        with self.assertRaisesRegex(OfflineDriverFailure,'P19_WINDOW_REATTESTATION_MISSING'):
            runner.run(self.intent)
        self.assertEqual(driver.attempt_count,0)
        self.assertEqual(self.ledger.audit_all()[0].status,'DISPATCH_UNCERTAIN')

    def test_busy_gate_releases_prepared_but_keeps_original_uncertain(self):
        runner,_=self.runtime()
        runner.run(self.intent)
        other=replace(self.intent,action_id='p19-other',action_key='other',account_id='enu',
                      client_id='window-2',window_generation=2,actor_id=888)
        win=OfflineWindowObservation('enu','window-2',2,True,True,True)
        blocked,_=self.runtime(windows=(win,win))
        report=blocked.run(other)
        self.assertEqual(report.reason,'P19_GLOBAL_DISPATCH_BUSY')
        self.assertEqual(report.action_status,'CANCELLED')
        self.assertEqual(self.ledger.audit(self.intent.action_id).status,'DISPATCH_UNCERTAIN')
        self.assertEqual(self.ledger.audit(other.action_id).status,'CANCELLED')

    def test_no_stale_evidence(self):
        runtime,_=self.runtime()
        ev=replace(fixture_evidence(self.intent,evidence_id='p19-ev-old'),observed_revision=7)
        with self.assertRaisesRegex(ExecutionLedgerRejected,'P18_STALE_OUTCOME_REVISION'):
            runtime.run(self.intent,evidence=ev)
        self.assertEqual(self.ledger.audit_all()[0].status,'DISPATCH_UNCERTAIN')

    def test_prepared_can_cancel_after_synthetic_crash(self):
        runtime,drv=self.runtime()
        with self.assertRaises(OfflineDriverFailure):runtime.run(self.intent,fault_point='after_prepared')
        self.assertEqual(self.ledger.cancel_before_dispatch(self.intent.action_id).status,'CANCELLED')
        self.assertEqual(drv.attempt_count,0)

    def test_driver_forgery_rejected(self):
        class Evil(OfflineFakeInputDriver):pass
        with self.assertRaisesRegex(OfflineDispatchRejected,'P19_FAKE_ONLY_RUNTIME'):
            OfflineDispatchCoordinator(self.ledger,Evil(),OfflineWindowFeed(self.window))
        with self.assertRaisesRegex(OfflineDispatchRejected,'P19_FAKE_ONLY_RUNTIME'):
            OfflineDispatchCoordinator(self.ledger,OfflineFakeInputDriver(),object())

    def test_read_only_ledger_cannot_act(self):
        with self.assertRaisesRegex(OfflineDispatchRejected,'P19_WRITABLE_LEDGER_REQUIRED'):
            OfflineDispatchCoordinator(OfflineExecutionLedger(self.path,read_only=True),
                OfflineFakeInputDriver(),OfflineWindowFeed(self.window))

    def test_fake_driver_cannot_attempt_twice(self):
        driver=OfflineFakeInputDriver()
        driver.attempt(self.intent)
        with self.assertRaisesRegex(OfflineDriverFailure,'P19_FAKE_DRIVER_DUPLICATE_ATTEMPT'):
            driver.attempt(self.intent)

    def test_report_and_window_authority_forgery(self):
        window=self.window
        for updates in ({'physical_input_permitted':True},{'synthetic_only':False}):
            with self.assertRaisesRegex(ValueError,'P19_AUTHORITY_FORGERY'):
                replace(window,**updates)
        rep=OfflineDispatchReport(self.intent.action_id,'CANCELLED','PRE_DISPATCH','P19_CANCELLED',0)
        for updates in ({'actionable':True},{'physical_input_sent':True},{'synthetic_only':False}):
            with self.assertRaisesRegex(ValueError,'P19_AUTHORITY_FORGERY'):
                replace(rep,**updates)
        receipt=OfflineDriverReceipt(self.intent.action_id,'NO_INPUT',0)
        with self.assertRaisesRegex(ValueError,'P19_AUTHORITY_FORGERY'):
            replace(receipt,physical_input_sent=True)

    def test_bad_fixture_values(self):
        for updates in ({'window_generation':True},{'window_generation':0},
                        {'foreground_verified':1},{'account_id':'bad name'}):
            with self.subTest(updates=updates),self.assertRaises(ValueError):
                replace(self.window,**updates)
        with self.assertRaises(ValueError):OfflineDriverReceipt(self.intent.action_id,'SENT',1)
        with self.assertRaises(ValueError):OfflineDispatchReport(self.intent.action_id,'PASS','PRE_DISPATCH','X',0)

    def test_fake_only_dependency_boundary(self):
        root=Path(__file__).resolve().parents[1]/'src'
        for rel in ('anka_execution/fake_input.py','anka_execution/offline_dispatch.py',
                    'anka_contracts/execution_simulation.py'):
            tree=ast.parse((root/rel).read_text(encoding='utf8'))
            imports=[]
            for node in ast.walk(tree):
                if isinstance(node,ast.Import): imports += [a.name for a in node.names]
                if isinstance(node,ast.ImportFrom): imports.append(node.module or '')
            for forbidden in ('ctypes','pyautogui','pynput','win32api','win32gui','anka_client',
                              'anka_capture','anka_protocol','anka_decision','anka_workflow'):
                self.assertFalse(any(p==forbidden or p.startswith(forbidden+'.') for p in imports),rel+' '+forbidden)


class P19ScenarioTests(unittest.TestCase):
    def test_all_demo_scenarios_are_offline(self):
        for case in SCENARIOS:
            with self.subTest(case=case):
                data=execution_sim_demo(scenario=case)
                self.assertEqual(data['operation'],'execution-sim-demo')
                self.assertTrue(data['synthetic_only'])
                self.assertFalse(data['physical_input_sent'])
                self.assertFalse(data['live_ready'])
                self.assertGreaterEqual(len(data['actions']),1)
                self.assertLessEqual(data['driver_invocations'],1)

    def test_replay_after_crash_scenarios(self):
        for case,expected in [('crash-after-prepare','PREPARED'),
                              ('crash-after-boundary','DISPATCH_UNCERTAIN'),
                              ('crash-after-fake-attempt','DISPATCH_UNCERTAIN')]:
            with self.subTest(case=case):
                data=execution_sim_demo(scenario=case)
                self.assertEqual(data['actions'][0]['status'],expected)
                self.assertTrue(data['observed_error'].startswith('P19_INJECTED_CRASH'))

    def test_wrong_evidence_does_not_confirm(self):
        data=execution_sim_demo(scenario='wrong-evidence')
        self.assertEqual(data['actions'][0]['status'],'DISPATCH_UNCERTAIN')
        self.assertEqual(data['observed_error'],'P18_OUTCOME_SCOPE_MISMATCH')

    def test_invalid_scenario(self):
        with self.assertRaisesRegex(ValueError,'P19_DEMO_SCENARIO_INVALID'):
            execution_sim_demo(scenario='not-real')

    def test_confirmed_fixture_never_live_ready(self):
        data=execution_sim_demo(scenario='confirmed-fixture')
        self.assertEqual(data['actions'][0]['status'],'CONFIRMED')
        self.assertEqual(data['status'],'RESEARCH_ONLY')
        self.assertFalse(data['live_ready'])

    def test_fake_failures_are_not_live_send(self):
        for case in ('focus-lost','generation-changed','driver-raises-after','no-input'):
            with self.subTest(case=case):
                data=execution_sim_demo(scenario=case)
                self.assertEqual(data['status'],'BLOCKED_UNCERTAIN')
                self.assertFalse(data['physical_input_sent'])

    def test_second_account_does_not_dispatch(self):
        data=execution_sim_demo(scenario='second-account-contention')
        self.assertEqual(data['observed_error'],'P19_GLOBAL_DISPATCH_BUSY')
        self.assertEqual(len(data['actions']),2)
        self.assertEqual(data['driver_invocations'],1)

    def test_cli_no_physical_execution(self):
        import subprocess,sys,os
        root=Path(__file__).resolve().parents[1]
        env={**os.environ,'PYTHONPATH':str(root/'src')}
        done=subprocess.run([sys.executable,'-m','anka_app.cli','execution-sim-demo','focus-lost'],
                            cwd=root,env=env,text=True,capture_output=True,timeout=25)
        self.assertEqual(done.returncode,0,done.stdout[-1200:]+done.stderr[-1200:])
        self.assertIn('ANKA_STATUS=BLOCKED_UNCERTAIN',done.stdout)
        self.assertIn('"physical_input_sent": false',done.stdout)
        self.assertIn('P19_WINDOW_FOCUS_NOT_VERIFIED',done.stdout)

    def test_focus_failure_reason_survives_sanitized_incident(self):
        import subprocess,sys,os,zipfile
        root=Path(__file__).resolve().parents[1]
        env={**os.environ,'PYTHONPATH':str(root/'src')}
        done=subprocess.run([sys.executable,'-m','anka_app.cli','execution-sim-demo','focus-lost'],
                            cwd=root,env=env,text=True,capture_output=True,timeout=25)
        self.assertEqual(done.returncode,0)
        data=json.loads(next(x[len('ANKA_RESULT='):] for x in done.stdout.splitlines() if x.startswith('ANKA_RESULT=')))
        with zipfile.ZipFile(data['incident_bundle']) as archive:
            timeline=archive.read('timeline.jsonl').decode('utf8')
            self.assertIn('P19_WINDOW_FOCUS_NOT_VERIFIED',timeline)
            self.assertIn('execution.dispatch_or_settlement',timeline)
            self.assertNotIn('Unimplemented P3-P13',archive.read('evidence_matrix.json').decode('utf8'))

    def test_diagnostic_bundle_integrity(self):
        import subprocess,sys,os,re
        root=Path(__file__).resolve().parents[1]
        env={**os.environ,'PYTHONPATH':str(root/'src')}
        done=subprocess.run([sys.executable,'-m','anka_app.cli','execution-sim-demo','no-confirmation'],
                            cwd=root,env=env,text=True,capture_output=True,timeout=25)
        self.assertEqual(done.returncode,0)
        result=json.loads(next(line[len('ANKA_RESULT='):] for line in done.stdout.splitlines()
                               if line.startswith('ANKA_RESULT=')))
        from anka_observability.bundle import verify_incident
        self.assertTrue(Path(result['incident_bundle']).exists())
        self.assertIn('PASS',str(verify_incident(Path(result['incident_bundle']))))
        self.assertFalse(result['physical_input_sent'])


if __name__=='__main__':unittest.main()
