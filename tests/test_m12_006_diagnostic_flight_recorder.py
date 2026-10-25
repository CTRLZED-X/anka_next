from __future__ import annotations
import json,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from anka_contracts.diagnostics import DiagnosticEvent
from anka_observability.api import LocalDiagnostics
from anka_observability.bundle import verify_incident
from anka_observability.forensics import READY_TRACE


class TestM12006DiagnosticFlightRecorder(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_run_storage_failure_keeps_bounded_memory_evidence(self):
        real=Path.mkdir
        def fail_runs(path,*a,**k):
            if path.name=='run-diskless':raise OSError('simulated')
            return real(path,*a,**k)
        with patch('pathlib.Path.mkdir',new=fail_runs):
            obs=LocalDiagnostics(self.root,run_id='run-diskless',invocation_id='inv-diskless')
        self.assertFalse(obs.available)
        self.assertEqual(obs.record('bootstrap.command_failed',severity='ERROR',owner_system='anka_app',boundary='bootstrap.command',failure_code='X'),'UNAVAILABLE')
        frozen=obs.freeze()
        self.assertEqual(len(frozen.recent),1)
        self.assertEqual(frozen.recent[0]['failure_code'],'X')
        path=obs.export_incident('DISKLESS_TEST',boundary='bootstrap.command')
        self.addCleanup(path.unlink,missing_ok=True)
        self.assertEqual(verify_incident(path)['status'],'PASS')

    def test_cli_persistent_observer_failure_is_partial_not_control_authority(self):
        import contextlib,io
        import anka_app.cli as cli
        obs=LocalDiagnostics(self.root,run_id='run-cli-diskless',invocation_id='inv-cli-diskless')
        obs.available=False
        obs.note_error('RUN_STORAGE_UNAVAILABLE:SIMULATED')
        output=io.StringIO()
        with patch.object(cli,'LocalDiagnostics',return_value=obs), \
             patch.object(cli,'_command',return_value={'status':'PASS_TEST'}) as command, \
             patch.object(cli,'emergency_marker',return_value=self.root/'emergency.json'):
            with contextlib.redirect_stdout(output):
                code=cli.main(['check'])
        self.assertEqual(code,0)
        command.assert_called_once()
        text=output.getvalue()
        self.assertIn('ANKA_OBSERVABILITY=PARTIAL',text)
        self.assertIn('ANKA_STATUS=PASS_TEST',text)
        frozen=obs.freeze()
        storage=[row for row in frozen.recent if row.get('event_name')=='observability.storage_unavailable']
        self.assertEqual(len(storage),1)
        self.assertFalse(storage[0]['payload']['authority_granted'])

    def test_anomaly_signature_dedup_index_is_bounded(self):
        obs=LocalDiagnostics(self.root,run_id='run-pin-dedup',invocation_id='inv-pin-dedup',max_pinned=2,pin_window=1)
        self.addCleanup(obs.finish,'CLOSED')
        for i in range(100):
            obs.record('execution.guard_failed',severity='SAFETY',owner_system='anka_execution',
                       boundary='execution.pre_input_authorization',failure_code=f'FAULT_{i}',
                       fight_epoch=i+1)
        self.assertLessEqual(len(obs._pinned_trigger_keys),obs._pinned_trigger_key_order.maxlen)
        self.assertLessEqual(len(obs.pinned),2)

    def test_priority_evidence_survives_recent_ring_overwrite(self):
        obs=LocalDiagnostics(self.root,run_id='run-flight',invocation_id='inv-flight',max_recent=16,max_priority=16)
        self.addCleanup(obs.finish,'CLOSED')
        obs.record('execution.outcome_missing',severity='SAFETY',owner_system='anka_execution',boundary='execution.outcome',failure_code='SERVER_PROOF_MISSING',action_id='action-early',physical_input_state='MAY_HAVE_SENT')
        for i in range(80):
            obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog',payload={'i':i})
        self.assertGreater(obs.recent_overwrites,0)
        self.assertNotIn('action-early',{e.get('action_id') for e in obs.recent})
        self.assertIn('action-early',{e.get('action_id') for e in obs.priority})
        path=obs.export_incident('SERVER_PROOF_MISSING',boundary='execution.outcome')
        with ZipFile(path) as z:
            rows=[json.loads(x) for x in z.read('logs/relevant_timeline.jsonl').decode().splitlines() if x]
            run=json.loads(z.read('run_manifest.json'))
        self.assertIn('action-early',{e.get('action_id') for e in rows})
        self.assertGreater(run['flight_recorder']['recent_overwrites'],0)
        self.assertEqual(run['evidence_completeness'],'PARTIAL')

    def test_export_releases_live_recorder_lock_before_zip_io(self):
        obs=LocalDiagnostics(self.root,run_id='run-export',invocation_id='inv-export')
        obs.record('bootstrap.command_started',owner_system='anka_app',boundary='bootstrap.command')
        entered=threading.Event();release=threading.Event()
        from anka_observability import bundle
        real=bundle._write_zip
        def blocked(path,artifacts,manifest):
            entered.set();release.wait(2);return real(path,artifacts,manifest)
        holder={}
        with patch('anka_observability.bundle._write_zip',side_effect=blocked):
            t=threading.Thread(target=lambda:holder.setdefault('p',obs.export_incident('EXPORT_LOCK_TEST',boundary='bootstrap.command')))
            t.start();self.assertTrue(entered.wait(1))
            start=time.monotonic();result=obs.record('execution.guard_failed',severity='SAFETY',owner_system='anka_execution',boundary='execution.pre_input_authorization',failure_code='FOCUS_CHANGED')
            elapsed=time.monotonic()-start
            release.set();t.join(2)
        self.assertLess(elapsed,0.2)
        self.assertIn(result,('RECORDED','DROPPED','UNAVAILABLE'))
        self.assertFalse(t.is_alive())

    def test_caller_supplied_matching_run_ids_are_not_dropped(self):
        obs=LocalDiagnostics(self.root,run_id='run-corr',invocation_id='inv-corr')
        self.addCleanup(obs.finish,'CLOSED')
        result=obs.record('workflow.phase_changed',owner_system='anka_workflow',boundary='workflow.phase',run_id='run-corr',invocation_id='inv-corr',trace_id='trace-1')
        self.assertEqual(result,'RECORDED')
        self.assertEqual(obs.recent[-1]['trace_id'],'trace-1')
        self.assertEqual(obs.record('workflow.phase_changed',owner_system='anka_workflow',boundary='workflow.phase',run_id='run-other'),'DROPPED')

    def test_analyzer_crash_still_exports_verifier_clean_emergency_bundle(self):
        obs=LocalDiagnostics(self.root,run_id='run-emergency',invocation_id='inv-emergency')
        obs.record('ready.requested',owner_system='anka_workflow',boundary='workflow.ready_request',account_id='acct-cra')
        with patch('anka_observability.bundle._build_artifacts',side_effect=RuntimeError('secret analyzer text')):
            path=obs.export_incident('READY_STALLED',boundary='protocol.ready_observation',trace_spec=READY_TRACE,control_state='BLOCKED')
        self.addCleanup(path.unlink,missing_ok=True)
        self.assertEqual(verify_incident(path)['status'],'PASS')
        with ZipFile(path) as z:
            blob=b'\n'.join(z.read(n) for n in z.namelist()).decode('utf8','ignore')
            manifest=json.loads(z.read('manifest.json'))
        self.assertTrue(manifest['advanced_analysis_failed'])
        self.assertNotIn('secret analyzer text',blob)
        self.assertIn('READY_STALLED',blob)

    def test_timeline_is_real_jsonl(self):
        obs=LocalDiagnostics(self.root,run_id='run-jsonl',invocation_id='inv-jsonl')
        for i in range(3):obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog',payload={'i':i})
        path=obs.export_incident('JSONL_TEST',boundary='workflow.watchdog')
        with ZipFile(path) as z:
            text=z.read('timeline.jsonl').decode()
        rows=[json.loads(line) for line in text.splitlines() if line]
        self.assertEqual(len(rows),3)

if __name__=='__main__':unittest.main()

class TestM12006CausalCorrelation(unittest.TestCase):
    def test_batch_trace_cannot_borrow_commit_from_different_batch(self):
        from anka_contracts.diagnostics import BoundaryExpectation,OperationTraceSpec
        from anka_observability.forensics import FirstDivergenceAnalyzer
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        obs=LocalDiagnostics(Path(tmp.name),run_id='run-batch',invocation_id='inv-batch')
        self.addCleanup(obs.finish,'CLOSED')
        spec=OperationTraceSpec('BATCH',(
            BoundaryExpectation('protocol.batch_decoded','protocol.decode','anka_protocol','protocol'),
            BoundaryExpectation('canonical.batch_admitted','canonical.admission','anka_canonical','canonical'),
            BoundaryExpectation('canonical.commit_acknowledged','canonical.commit','anka_canonical','canonical'),
        ),('payload.batch_span_id',))
        obs.record('protocol.batch_decoded',owner_system='anka_protocol',boundary='protocol.decode',payload={'batch_span_id':'batch-a'})
        obs.record('canonical.batch_admitted',owner_system='anka_canonical',boundary='canonical.admission',payload={'batch_span_id':'batch-a'})
        obs.record('canonical.commit_acknowledged',owner_system='anka_canonical',boundary='canonical.commit',payload={'batch_span_id':'batch-b'})
        result=FirstDivergenceAnalyzer().analyze(spec,obs.recent)
        self.assertEqual(result.finding.first_divergent_boundary,'canonical.commit')
        self.assertEqual(result.boundary_graph[2]['correlation']['payload.batch_span_id'],'batch-a')

class TestM12006PartyReadyReconstruction(unittest.TestCase):
    def test_real_q9_ready_chain_is_proved_per_account_then_shared(self):
        from anka_app.zero_input_integration import ZeroInputQ9Scenario,CRA,ENU
        from anka_observability.forensics import PartyReadyAnalyzer
        with tempfile.TemporaryDirectory() as td:
            s=ZeroInputQ9Scenario(Path(td))
            try:
                s.happy_path()
                self.assertEqual(s.observer.dropped,0)
                result=PartyReadyAnalyzer().analyze(s.observer.recent,(CRA[0],ENU[0]),control_state='FIGHT_ACTIVE')
                self.assertIsNone(result.finding)
                self.assertEqual({g['account_id'] for g in result.account_graphs},{CRA[0],ENU[0]})
                self.assertTrue(all(all(e['status']=='OBSERVED' for e in g['edges']) for g in result.account_graphs))
                self.assertTrue(all(e['status']=='OBSERVED' for e in result.shared_graph))
            finally:s.close()

    def test_cra_ack_cannot_complete_enu_ready_path(self):
        from anka_app.zero_input_integration import ZeroInputQ9Scenario,CRA,ENU
        from anka_observability.forensics import PartyReadyAnalyzer
        with tempfile.TemporaryDirectory() as td:
            s=ZeroInputQ9Scenario(Path(td))
            try:
                s.happy_path()
                rows=tuple(e for e in s.observer.recent if not (e['account_id']==ENU[0] and e['event_name']=='protocol.ready_observed'))
                result=PartyReadyAnalyzer().analyze(rows,(CRA[0],ENU[0]),control_state='BLOCKED')
                self.assertIsNotNone(result.finding)
                self.assertEqual(result.finding.first_divergent_boundary,'protocol.ready_observation')
                self.assertEqual(result.finding.suspected_owner,'anka_protocol')
                enu=next(g for g in result.account_graphs if g['account_id']==ENU[0])
                self.assertEqual(enu['edges'][-1]['status'],'MISSING')
            finally:s.close()

    def test_protocol_and_canonical_ready_must_share_batch_span(self):
        from anka_app.zero_input_integration import ZeroInputQ9Scenario,CRA,ENU
        from anka_observability.forensics import PartyReadyAnalyzer
        with tempfile.TemporaryDirectory() as td:
            s=ZeroInputQ9Scenario(Path(td))
            try:
                s.happy_path();rows=[]
                for e in s.observer.recent:
                    row=dict(e)
                    if row['account_id']==ENU[0] and row['event_name']=='canonical.ready_committed':
                        row['payload']=dict(row['payload']);row['payload']['batch_span_id']='batch-other'
                    rows.append(row)
                result=PartyReadyAnalyzer().analyze(tuple(rows),(CRA[0],ENU[0]),control_state='BLOCKED')
                self.assertEqual(result.finding.first_divergent_boundary,'canonical.ready_commit')
            finally:s.close()

class TestM12006ReadyFightEpochIsolation(unittest.TestCase):
    def test_latest_incomplete_fight_cannot_be_hidden_by_prior_complete_ready_chain(self):
        from anka_observability.forensics import PartyReadyAnalyzer
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        obs=LocalDiagnostics(Path(tmp.name),run_id='run-ready-epochs',invocation_id='inv-ready-epochs')
        self.addCleanup(obs.finish,'CLOSED')

        def per_account(account,action,fight,batch):
            obs.record('ready.requested',owner_system='anka_workflow',boundary='workflow.ready_request',account_id=account,fight_epoch=fight,action_id=action)
            obs.record('execution.admitted',owner_system='anka_execution',boundary='execution.pre_input_authorization',account_id=account,fight_epoch=fight,action_id=action)
            obs.record('execution.input_sent',owner_system='anka_execution',boundary='execution.external_boundary',account_id=account,fight_epoch=fight,action_id=action)
            obs.record('protocol.ready_observed',owner_system='anka_protocol',boundary='protocol.ready_observation',account_id=account,fight_epoch=fight,payload={'batch_span_id':batch})
            obs.record('canonical.ready_committed',owner_system='anka_canonical',boundary='canonical.ready_commit',account_id=account,fight_epoch=fight,payload={'batch_span_id':batch})

        # Fight 1 was fully healthy for both accounts.
        per_account('acct-cra','action-ready-cra-1',1,'batch-cra-1')
        per_account('acct-enu','action-ready-enu-1',1,'batch-enu-1')
        obs.record('coordination.ready_barrier_satisfied',owner_system='anka_coordination',boundary='coordination.ready_barrier',fight_epoch=1,payload={'required_accounts':['acct-cra','acct-enu']})
        obs.record('coordination.turn_owner_proved',owner_system='anka_coordination',boundary='coordination.first_turn',account_id='acct-cra',fight_epoch=1)
        obs.record('decision.frame_created',owner_system='anka_decision',boundary='decision.frame',account_id='acct-cra',fight_epoch=1)

        # Fight 2 started READY but ENU never produced server/Canonical proof.
        per_account('acct-cra','action-ready-cra-2',2,'batch-cra-2')
        obs.record('ready.requested',owner_system='anka_workflow',boundary='workflow.ready_request',account_id='acct-enu',fight_epoch=2,action_id='action-ready-enu-2')
        obs.record('execution.admitted',owner_system='anka_execution',boundary='execution.pre_input_authorization',account_id='acct-enu',fight_epoch=2,action_id='action-ready-enu-2')
        obs.record('execution.input_sent',owner_system='anka_execution',boundary='execution.external_boundary',account_id='acct-enu',fight_epoch=2,action_id='action-ready-enu-2')

        result=PartyReadyAnalyzer().analyze(obs.recent,('acct-cra','acct-enu'),control_state='BLOCKED')
        self.assertIsNotNone(result.finding)
        self.assertEqual(result.finding.first_divergent_boundary,'protocol.ready_observation')
        enu=next(g for g in result.account_graphs if g['account_id']=='acct-enu')
        self.assertEqual(enu['fight_epoch'],2)
        self.assertEqual(enu['edges'][-1]['status'],'MISSING')
        self.assertTrue(all(g['fight_epoch']==2 for g in result.account_graphs))

class TestM12006ReadyRetryIsolation(unittest.TestCase):
    def test_latest_same_fight_ready_retry_cannot_borrow_prior_attempt_ack(self):
        from anka_observability.forensics import PartyReadyAnalyzer
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-ready-retry',invocation_id='inv-ready-retry')
            # CRA's first attempt had a full acknowledgement.
            obs.record('ready.requested',owner_system='anka_workflow',boundary='workflow.ready_request',account_id='acct-cra',fight_epoch=3,action_id='action-cra-old')
            obs.record('execution.admitted',owner_system='anka_execution',boundary='execution.pre_input_authorization',account_id='acct-cra',fight_epoch=3,action_id='action-cra-old')
            obs.record('execution.input_sent',owner_system='anka_execution',boundary='execution.external_boundary',account_id='acct-cra',fight_epoch=3,action_id='action-cra-old')
            obs.record('protocol.ready_observed',owner_system='anka_protocol',boundary='protocol.ready_observation',account_id='acct-cra',fight_epoch=3,payload={'batch_span_id':'batch-cra-old'})
            obs.record('canonical.ready_committed',owner_system='anka_canonical',boundary='canonical.ready_commit',account_id='acct-cra',fight_epoch=3,payload={'batch_span_id':'batch-cra-old'})
            # CRA retries later in the same fight, but this new attempt never gets
            # server/Canonical acknowledgement. The analyzer must not reuse old proof.
            obs.record('ready.requested',owner_system='anka_workflow',boundary='workflow.ready_request',account_id='acct-cra',fight_epoch=3,action_id='action-cra-new')
            obs.record('execution.admitted',owner_system='anka_execution',boundary='execution.pre_input_authorization',account_id='acct-cra',fight_epoch=3,action_id='action-cra-new')
            obs.record('execution.input_sent',owner_system='anka_execution',boundary='execution.external_boundary',account_id='acct-cra',fight_epoch=3,action_id='action-cra-new')
            # ENU's latest attempt is complete.
            obs.record('ready.requested',owner_system='anka_workflow',boundary='workflow.ready_request',account_id='acct-enu',fight_epoch=3,action_id='action-enu-new')
            obs.record('execution.admitted',owner_system='anka_execution',boundary='execution.pre_input_authorization',account_id='acct-enu',fight_epoch=3,action_id='action-enu-new')
            obs.record('execution.input_sent',owner_system='anka_execution',boundary='execution.external_boundary',account_id='acct-enu',fight_epoch=3,action_id='action-enu-new')
            obs.record('protocol.ready_observed',owner_system='anka_protocol',boundary='protocol.ready_observation',account_id='acct-enu',fight_epoch=3,payload={'batch_span_id':'batch-enu-new'})
            obs.record('canonical.ready_committed',owner_system='anka_canonical',boundary='canonical.ready_commit',account_id='acct-enu',fight_epoch=3,payload={'batch_span_id':'batch-enu-new'})
            # Misleading shared evidence must not hide CRA's latest missing ack.
            obs.record('coordination.ready_barrier_satisfied',owner_system='anka_coordination',boundary='coordination.ready_barrier',fight_epoch=3,payload={'required_accounts':['acct-cra','acct-enu']})
            obs.record('coordination.turn_owner_proved',owner_system='anka_coordination',boundary='coordination.first_turn',account_id='acct-cra',fight_epoch=3)
            obs.record('decision.frame_created',owner_system='anka_decision',boundary='decision.frame',account_id='acct-cra',fight_epoch=3)
            result=PartyReadyAnalyzer().analyze(obs.recent,('acct-cra','acct-enu'),control_state='BLOCKED')
            self.assertIsNotNone(result.finding)
            self.assertEqual(result.finding.first_divergent_boundary,'protocol.ready_observation')
            cra=next(g for g in result.account_graphs if g['account_id']=='acct-cra')
            self.assertEqual(cra['edges'][0]['action_id'],'action-cra-new')
            self.assertEqual(cra['edges'][-1]['status'],'MISSING')
            obs.finish('BLOCKED')

class TestM12006ActionLifecycleForensics(unittest.TestCase):
    def test_bundle_contains_per_action_send_and_settlement_history(self):
        from anka_app.zero_input_integration import ZeroInputQ9Scenario
        with tempfile.TemporaryDirectory() as td:
            s=ZeroInputQ9Scenario(Path(td))
            try:
                s.happy_path()
                path=s.observer.export_incident('Q9_FORENSIC_AUDIT',boundary='integration.q9')
                self.assertEqual(verify_incident(path)['status'],'PASS')
                with ZipFile(path) as z:
                    report=json.loads(z.read('analysis/action_lifecycles.json'))
                    timeline={json.loads(x)['event_id'] for x in z.read('logs/relevant_timeline.jsonl').decode().splitlines() if x}
                self.assertGreaterEqual(len(report['actions']),10)
                self.assertTrue(all(row['state']=='SETTLED' for row in report['actions']))
                self.assertTrue(all(row['settlement_status']=='SETTLED_SUCCESS' for row in report['actions']))
                self.assertTrue(all(isinstance(row['settlement_evidence_id'],str) and row['settlement_evidence_id'] for row in report['actions']))
                self.assertTrue(all(row['dispatch_outcome_status'] in ('PENDING','SETTLED_SUCCESS') for row in report['actions']))
                self.assertTrue(all(set(row['event_ids']).issubset(timeline) for row in report['actions']))
                self.assertTrue(all(row['decision_event_id'] in timeline for row in report['actions']))
                self.assertTrue(all(isinstance(row['trace_id'],str) and row['trace_id'].startswith('trace-') for row in report['actions']))
                self.assertTrue(all(row['nearby_semantic_context_is_causal_proof'] is False for row in report['actions']))
                with ZipFile(path) as z:
                    read_first=z.read('GPT_READ_FIRST.md').decode()
                self.assertIn('Physical input state:** NOT_SENT',read_first)
            finally:s.close()

class TestM12006ActionLifecycleBundleIntegrity(unittest.TestCase):
    @staticmethod
    def _rewrite_artifact(path:Path,name:str,mutator):
        from hashlib import sha256
        from zipfile import ZIP_DEFLATED
        with ZipFile(path) as z:
            files={n:z.read(n) for n in z.namelist()}
        payload=json.loads(files[name])
        mutator(payload)
        files[name]=(json.dumps(payload,sort_keys=True,ensure_ascii=True,indent=2)+'\n').encode('utf8')
        manifest=json.loads(files['manifest.json'])
        manifest['files'][name]={'sha256':sha256(files[name]).hexdigest(),'bytes':len(files[name])}
        files['manifest.json']=(json.dumps(manifest,sort_keys=True,ensure_ascii=True,indent=2)+'\n').encode('utf8')
        with ZipFile(path,'w',ZIP_DEFLATED) as z:
            for n,b in files.items():z.writestr(n,b)

    def _scenario_bundle(self,root:Path)->Path:
        from anka_app.zero_input_integration import ZeroInputQ9Scenario
        s=ZeroInputQ9Scenario(root)
        self.addCleanup(s.close)
        s.happy_path()
        return s.observer.export_incident('Q9_FORENSIC_AUDIT',boundary='integration.q9')

    def test_verifier_rejects_action_lifecycle_reference_not_shipped_in_timeline(self):
        with tempfile.TemporaryDirectory() as td:
            path=self._scenario_bundle(Path(td))
            self._rewrite_artifact(path,'analysis/action_lifecycles.json',
                lambda report: report['actions'][0]['event_ids'].append('evt-not-shipped'))
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('ACTION_LIFECYCLE_EVIDENCE_REF_MISSING',result['errors'])

    def test_action_lifecycle_positive_contradictions_are_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-action-contradiction',invocation_id='inv-action-contradiction')
            action='action-contradictory';attempt='attempt-one'
            obs.record('execution.admitted',owner_system='anka_execution',boundary='execution.pre_input_authorization',action_id=action)
            obs.record('execution.send_started',severity='SAFETY',owner_system='anka_execution',boundary='execution.external_boundary',action_id=action,attempt_id=attempt,physical_input_state='SEND_STARTED')
            obs.record('execution.input_sent',owner_system='anka_execution',boundary='execution.external_boundary',action_id=action,attempt_id=attempt,physical_input_state='SENT')
            obs.record('execution.outcome_settled',severity='SETTLEMENT',owner_system='anka_execution',boundary='execution.outcome_settlement',action_id=action,attempt_id=attempt,payload={'status':'SETTLED_SUCCESS'})
            obs.record('execution.outcome_terminal_unresolved',severity='SAFETY',owner_system='anka_execution',boundary='execution.outcome_settlement',action_id=action,attempt_id=attempt,failure_code='LATE_UNRESOLVED',physical_input_state='MAY_HAVE_SENT')
            path=obs.export_incident('ACTION_EVIDENCE_CONFLICT',boundary='execution.outcome_settlement')
            result=verify_incident(path);self.assertEqual(result['status'],'PASS',result['errors'])
            with ZipFile(path) as z:report=json.loads(z.read('analysis/action_lifecycles.json'))
            row=next(x for x in report['actions'] if x['action_id']==action)
            self.assertEqual(row['state'],'CONTRADICTORY_EVIDENCE')
            self.assertIn('CONFLICTING_TERMINAL_OUTCOMES',row['hard_conflicts'])
            self.assertEqual(report['contradictory_action_count'],1)
            obs.finish('BLOCKED')

    def test_verifier_rejects_rehashed_action_lifecycle_state_not_derived_from_timeline(self):
        with tempfile.TemporaryDirectory() as td:
            path=self._scenario_bundle(Path(td))
            self._rewrite_artifact(path,'analysis/action_lifecycles.json',
                lambda report: report['actions'][0].__setitem__('state','SETTLED_SUCCESS_FAKE'))
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('ACTION_LIFECYCLES_DERIVATION_MISMATCH',result['errors'])

    def test_verifier_rejects_context_promoted_to_causal_proof(self):
        with tempfile.TemporaryDirectory() as td:
            path=self._scenario_bundle(Path(td))
            self._rewrite_artifact(path,'analysis/action_lifecycles.json',
                lambda report: report['actions'][0].__setitem__('nearby_semantic_context_is_causal_proof',True))
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('ACTION_LIFECYCLE_CONTEXT_CAUSALITY_INVALID',result['errors'])

class TestM12006BoundaryGraphBundleIntegrity(unittest.TestCase):
    def test_verifier_rejects_boundary_graph_reference_not_shipped(self):
        from anka_contracts.diagnostics import BoundaryExpectation,OperationTraceSpec
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-graph-ref',invocation_id='inv-graph-ref')
            obs.record('workflow.action_requested',owner_system='anka_workflow',boundary='workflow.action_authorization',action_id='action-graph-ref')
            spec=OperationTraceSpec('GRAPH_REF',(BoundaryExpectation('workflow.action_requested','workflow.action_authorization','anka_workflow','workflow'),))
            path=obs.export_incident('GRAPH_TEST',boundary='workflow.action_authorization',trace_spec=spec)
            TestM12006ActionLifecycleBundleIntegrity._rewrite_artifact(
                path,'analysis/boundary_graph.json',lambda graph: graph['edges'][0].__setitem__('event_id','evt-not-shipped'))
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('BOUNDARY_GRAPH_EVIDENCE_REF_MISSING',result['errors'])

    def test_verifier_rejects_case_insensitive_zip_name_collision(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-case-collision',invocation_id='inv-case-collision')
            path=obs.export_incident('CASE_TEST',boundary='test.case')
            with ZipFile(path,'a') as z:z.writestr('Diagnosis.JSON',b'{}')
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('CASE_INSENSITIVE_ZIP_COLLISION',result['errors'])

class TestM12006AsyncJournalIsolation(unittest.TestCase):
    def test_slow_persistent_writer_cannot_block_runtime_record_call(self):
        from threading import Event
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-async-slow',invocation_id='inv-async-slow',journal_queue_capacity=8)
            release=Event();entered=Event();real=obs._write_journal_task
            def slow(path,encoded):
                entered.set();release.wait(1.0);real(path,encoded)
            obs._write_journal_task=slow
            start=time.monotonic()
            self.assertEqual(obs.record('execution.input_sent',owner_system='anka_execution',boundary='execution.external_boundary',severity='SETTLEMENT',action_id='action-async-slow',physical_input_state='SENT'),'RECORDED')
            elapsed=time.monotonic()-start
            self.assertTrue(entered.wait(0.5))
            self.assertLess(elapsed,0.10)
            # A second producer must also remain non-blocking while disk I/O is stalled.
            start=time.monotonic();result=obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog');elapsed2=time.monotonic()-start
            self.assertLess(elapsed2,0.10);self.assertIn(result,('RECORDED','DROPPED'))
            release.set();self.assertTrue(obs.flush_journals());obs.finish('CLOSED')

    def test_general_queue_saturation_does_not_erase_priority_memory_evidence(self):
        from threading import Event
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-async-full',invocation_id='inv-async-full',journal_queue_capacity=1,max_recent=8,max_priority=8)
            release=Event();entered=Event();real=obs._write_journal_task
            def slow(path,encoded):
                entered.set();release.wait(1.0);real(path,encoded)
            obs._write_journal_task=slow
            obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog',payload={'i':0})
            self.assertTrue(entered.wait(0.5))
            # Fill the one-slot ordinary queue behind the blocked writer.
            obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog',payload={'i':1})
            result=obs.record('execution.outcome_missing',severity='SAFETY',owner_system='anka_execution',boundary='execution.outcome',failure_code='SERVER_PROOF_MISSING',action_id='action-priority-queue',physical_input_state='MAY_HAVE_SENT')
            self.assertEqual(result,'DROPPED')
            self.assertGreaterEqual(obs.journal_queue_drops,1)
            self.assertIn('action-priority-queue',{e.get('action_id') for e in obs.priority})
            release.set();self.assertTrue(obs.flush_journals());
            path=obs.export_incident('SERVER_PROOF_MISSING',boundary='execution.outcome')
            self.assertEqual(verify_incident(path)['status'],'PASS')
            with ZipFile(path) as z:
                run=json.loads(z.read('run_manifest.json'))
                rows=[json.loads(x) for x in z.read('logs/relevant_timeline.jsonl').decode().splitlines() if x]
            self.assertGreaterEqual(run['flight_recorder']['journal_queue_drops'],1)
            self.assertEqual(run['evidence_completeness'],'PARTIAL')
            self.assertIn('action-priority-queue',{e.get('action_id') for e in rows})
            obs.finish('BLOCKED')

class TestM12006AsyncJournalSabotage(unittest.TestCase):
    def test_writer_thread_start_failure_is_observability_degradation_not_runtime_exception(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-writer-start-fail',invocation_id='inv-writer-start-fail')
            with patch('anka_observability.api.Thread.start',side_effect=RuntimeError('thread unavailable')):
                result=obs.record('execution.outcome_missing',severity='SAFETY',owner_system='anka_execution',boundary='execution.outcome',failure_code='SERVER_PROOF_MISSING',action_id='action-thread-start-fail',physical_input_state='MAY_HAVE_SENT')
            self.assertEqual(result,'UNAVAILABLE')
            self.assertFalse(obs.available)
            self.assertIn('action-thread-start-fail',{e.get('action_id') for e in obs.priority})
            self.assertTrue(any(x.startswith('JOURNAL_WRITER_START_FAILED:') for x in obs.errors))
            start=time.monotonic();self.assertFalse(obs.flush_journals(timeout_seconds=0.2));self.assertLess(time.monotonic()-start,0.10)
            path=obs.export_incident('SERVER_PROOF_MISSING',boundary='execution.outcome')
            self.assertEqual(verify_incident(path)['status'],'PASS')
            with ZipFile(path) as z:run=json.loads(z.read('run_manifest.json'))
            self.assertEqual(run['evidence_completeness'],'PARTIAL')
            self.assertFalse(run['flight_recorder']['persistent_storage_available'])
            obs.finish('BLOCKED')

    def test_unexpected_background_writer_exception_is_contained_and_memory_survives(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-writer-crash',invocation_id='inv-writer-crash')
            def broken(*_args,**_kwargs):raise RuntimeError('unexpected writer defect')
            obs._write_journal_task=broken
            result=obs.record('protocol.transaction_rejected',severity='SAFETY',owner_system='anka_protocol',boundary='protocol.transaction',failure_code='PROTOCOL_TRANSACTION_POISONED')
            self.assertEqual(result,'RECORDED')  # accepted into memory/queue before asynchronous failure
            deadline=time.monotonic()+1.0
            while obs.available and time.monotonic()<deadline:time.sleep(0.01)
            self.assertFalse(obs.available)
            self.assertTrue(any(x.startswith('JOURNAL_WORKER_FAILED:') for x in obs.errors))
            self.assertEqual(obs.recent[-1]['failure_code'],'PROTOCOL_TRANSACTION_POISONED')
            start=time.monotonic();obs.finish('BLOCKED');self.assertLess(time.monotonic()-start,0.25)

class TestM12006GPTForensicIndex(unittest.TestCase):
    def test_bundle_surfaces_recovery_and_historical_similarity_without_claiming_root_cause(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-gpt-index',invocation_id='inv-gpt-index')
            self.addCleanup(obs.finish,'CLOSED')
            obs.record('ready.requested',owner_system='anka_workflow',boundary='workflow.ready_request',account_id='acct-cra',fight_epoch=3,action_id='action-ready-index')
            obs.record('coordination.turn_owner_wait',owner_system='anka_coordination',boundary='coordination.first_turn',severity='ERROR',failure_code='TURN_OWNER_UNPROVEN',fight_epoch=3)
            obs.record('workflow.recovery_attempted',owner_system='anka_workflow',boundary='workflow.recovery',severity='WARNING',failure_code='READY_FIRST_TURN_TIMEOUT',fight_epoch=3,payload={'status':'FAILED','reason':'NO_TURN_OWNER'})
            path=obs.export_incident('READY_FIRST_TURN_TIMEOUT',boundary='coordination.first_turn',control_state='BLOCKED')
            self.assertEqual(verify_incident(path)['status'],'PASS')
            with ZipFile(path) as z:
                history=json.loads(z.read('analysis/historical_matches.json'))
                recovery=json.loads(z.read('analysis/recovery_history.json'))
                text=z.read('GPT_READ_FIRST.md').decode()
            match=next(x for x in history['matches'] if x['case_id']=='READY_NO_FIRST_TURN')
            self.assertEqual(match['classification'],'SIMILARITY_ONLY');self.assertFalse(match['root_cause_reused'])
            self.assertEqual(recovery['count'],1);self.assertEqual(recovery['attempts'][0]['failure_code'],'READY_FIRST_TURN_TIMEOUT')
            self.assertIn('Historical similarity hints (not root-cause proof)',text)
            self.assertIn('Recorded recovery/watchdog attempts:** 1',text)

    def test_healthy_ready_trace_does_not_match_ready_stall_history(self):
        from anka_observability.forensics import historical_similarity_report
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-healthy-history',invocation_id='inv-healthy-history')
            self.addCleanup(obs.finish,'CLOSED')
            obs.record('ready.requested',owner_system='anka_workflow',boundary='workflow.ready_request',account_id='acct-cra',fight_epoch=1)
            obs.record('coordination.turn_owner_proved',owner_system='anka_coordination',boundary='coordination.first_turn',account_id='acct-cra',fight_epoch=1)
            report=historical_similarity_report(obs.recent,code='Q9_FORENSIC_AUDIT',boundary='integration.q9')
            self.assertNotIn('READY_NO_FIRST_TURN',{x['case_id'] for x in report['matches']})
            obs.finish('CLOSED')

    def test_verifier_rejects_recovery_or_proven_fact_reference_not_in_timeline(self):
        from hashlib import sha256
        from zipfile import ZIP_DEFLATED
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-index-integrity',invocation_id='inv-index-integrity')
            self.addCleanup(obs.finish,'CLOSED')
            obs.record('workflow.recovery_attempted',owner_system='anka_workflow',boundary='workflow.recovery',severity='WARNING',failure_code='RECOVERY_FAILED')
            path=obs.export_incident('RECOVERY_FAILED',boundary='workflow.recovery')
            with ZipFile(path) as z:files={n:z.read(n) for n in z.namelist()}
            recovery=json.loads(files['analysis/recovery_history.json']);recovery['attempts'][0]['event_id']='evt-not-shipped'
            files['analysis/recovery_history.json']=(json.dumps(recovery,sort_keys=True,ensure_ascii=True,indent=2)+'\n').encode()
            manifest=json.loads(files['manifest.json']);blob=files['analysis/recovery_history.json']
            manifest['files']['analysis/recovery_history.json']={'sha256':sha256(blob).hexdigest(),'bytes':len(blob)}
            files['manifest.json']=(json.dumps(manifest,sort_keys=True,ensure_ascii=True,indent=2)+'\n').encode()
            with ZipFile(path,'w',ZIP_DEFLATED) as z:
                for n,b in files.items():z.writestr(n,b)
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL');self.assertIn('RECOVERY_HISTORY_EVIDENCE_REF_MISSING',result['errors'])

class TestM12006CorrelationIntegrity(unittest.TestCase):
    def test_newest_ready_without_epoch_cannot_fall_back_to_older_complete_fight(self):
        from anka_observability.forensics import PartyReadyAnalyzer
        events=[]
        def add(seq,name,owner,boundary,account=None,epoch=2,action=None,payload=None):
            from anka_contracts.diagnostics import DiagnosticEvent
            events.append(DiagnosticEvent(1,f'evt-rdy-{seq}',name,'INFO','2026-10-24T00:00:00.000Z',seq,seq,
                'inv-ready-epoch','run-ready-epoch',account_id=account,fight_epoch=epoch,action_id=action,
                owner_system=owner,boundary=boundary,payload=payload or {}))
        seq=1
        for account in ('acct-cra','acct-enu'):
            action='action-old-'+account
            add(seq,'ready.requested','anka_workflow','workflow.ready_request',account,2,action);seq+=1
            add(seq,'execution.admitted','anka_execution','execution.pre_input_authorization',account,2,action);seq+=1
            add(seq,'execution.input_sent','anka_execution','execution.external_boundary',account,2,action);seq+=1
            add(seq,'protocol.ready_observed','anka_protocol','protocol.ready_observation',account,2,None,{'batch_span_id':'batch-'+account});seq+=1
            add(seq,'canonical.ready_committed','anka_canonical','canonical.ready_commit',account,2,None,{'batch_span_id':'batch-'+account});seq+=1
        add(seq,'coordination.ready_barrier_satisfied','anka_coordination','coordination.ready_barrier',None,2,None,{'required_accounts':['acct-cra','acct-enu']});seq+=1
        add(seq,'coordination.turn_owner_proved','anka_coordination','coordination.first_turn','acct-cra',2);seq+=1
        add(seq,'decision.frame_created','anka_decision','decision.frame','acct-cra',2);seq+=1
        # New fight request is newer but malformed: no fight epoch.  The analyzer
        # must diagnose it instead of reporting fight 2 as the current success.
        add(seq,'ready.requested','anka_workflow','workflow.ready_request','acct-cra',None,'action-new-cra')
        result=PartyReadyAnalyzer().analyze(events,('acct-cra','acct-enu'),control_state='BLOCKED')
        self.assertIsNotNone(result.finding)
        self.assertEqual(result.finding.first_divergent_boundary,'workflow.ready_request')
        self.assertIn('ready.requested.fight_epoch',result.finding.missing_evidence)

    def test_external_emit_cannot_duplicate_or_rewind_producer_order(self):
        import tempfile
        from pathlib import Path
        from anka_contracts.diagnostics import DiagnosticEvent
        from anka_observability.api import LocalDiagnostics
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-external-order',invocation_id='inv-external-order')
            self.addCleanup(obs.finish,'CLOSED')
            first=DiagnosticEvent(1,'evt-external-1','debug.external','INFO','2026-10-24T00:00:00.000Z',1,10,
                                  'inv-external-order','run-external-order',owner_system='anka_observability')
            self.assertEqual(obs.emit(first),'RECORDED')
            stale=DiagnosticEvent(1,'evt-external-2','debug.external','INFO','2026-10-24T00:00:00.001Z',2,9,
                                  'inv-external-order','run-external-order',owner_system='anka_observability')
            self.assertEqual(obs.emit(stale),'DROPPED')
            duplicate=DiagnosticEvent(1,'evt-external-1','debug.external','INFO','2026-10-24T00:00:00.002Z',3,11,
                                      'inv-external-order','run-external-order',owner_system='anka_observability')
            self.assertEqual(obs.emit(duplicate),'DROPPED')
            self.assertIn('EXTERNAL_EVENT_SEQUENCE_STALE',obs.errors)
            self.assertIn('EXTERNAL_EVENT_ID_DUPLICATE',obs.errors)
            # Async persistence has an explicit owner lifecycle; close it before
            # the temporary run root is removed.
            obs.finish('CLOSED')


class TestM12006ReadFirstTruthfulness(unittest.TestCase):
    def test_untraced_bundle_does_not_claim_export_boundary_is_first_divergence(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-untraced',invocation_id='inv-untraced')
            obs.record('workflow.phase_changed',owner_system='anka_workflow',boundary='workflow.phase')
            path=obs.export_incident('MANUAL_DIAGNOSTIC_EXPORT',boundary='operator.debug',control_state='UNKNOWN')
            self.assertEqual(verify_incident(path)['status'],'PASS')
            with ZipFile(path) as z:text=z.read('GPT_READ_FIRST.md').decode()
            self.assertIn('First divergence:** NOT_ESTABLISHED',text)
            self.assertIn('Observed/export boundary:** operator.debug',text)
            self.assertIn('Supporting evidence IDs:** none uniquely identified',text)
            obs.finish('CLOSED')


class TestM12006RequiredBundleArtifacts(unittest.TestCase):
    def test_verifier_rejects_manifest_consistent_bundle_missing_gpt_artifact(self):
        from hashlib import sha256
        from zipfile import ZIP_DEFLATED
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-required-artifact',invocation_id='inv-required-artifact')
            obs.record('workflow.phase_changed',owner_system='anka_workflow',boundary='workflow.phase')
            path=obs.export_incident('REQUIRED_ARTIFACT_TEST',boundary='workflow.phase')
            obs.finish('CLOSED')
            with ZipFile(path) as z:files={n:z.read(n) for n in z.namelist()}
            files.pop('GPT_READ_FIRST.md')
            manifest=json.loads(files['manifest.json']);manifest['files'].pop('GPT_READ_FIRST.md')
            files['manifest.json']=(json.dumps(manifest,sort_keys=True,ensure_ascii=True,indent=2)+'\n').encode()
            with ZipFile(path,'w',ZIP_DEFLATED) as z:
                for name,data in files.items():z.writestr(name,data)
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('MISSING_REQUIRED_ARTIFACT:GPT_READ_FIRST.md',result['errors'])

class TestM12006GPTSummaryIntegrity(unittest.TestCase):
    def test_verifier_rejects_machine_summary_false_cause_certainty(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-gpt-causes',invocation_id='inv-gpt-causes')
            obs.record('ready.requested',owner_system='anka_workflow',boundary='workflow.ready_request')
            obs.record('execution.guard_failed',severity='ERROR',owner_system='anka_execution',boundary='execution.other',failure_code='FOCUS_CHANGED')
            obs.record('client.attestation_stale',severity='ERROR',owner_system='anka_client',boundary='client.identity',failure_code='WINDOW_GENERATION_STALE')
            path=obs.export_incident('READY_AMBIGUOUS',boundary='execution.pre_input_authorization',trace_spec=READY_TRACE,control_state='BLOCKED')
            obs.finish('BLOCKED')
            TestM12006ActionLifecycleBundleIntegrity._rewrite_artifact(
                path,'analysis/gpt_summary.json',lambda payload: payload.__setitem__('cause_status','SINGLE_SUPPORTED'))
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertTrue({'GPT_SUMMARY_CAUSE_STATUS_MISMATCH','GPT_SUMMARY_CAUSE_MISMATCH'} & set(result['errors']))

    def test_verifier_rejects_machine_summary_false_physical_state(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-gpt-summary',invocation_id='inv-gpt-summary')
            obs.record('execution.input_sent',owner_system='anka_execution',boundary='execution.external_boundary',
                       physical_input_state='SENT',action_id='action-gpt-summary')
            path=obs.export_incident('GPT_SUMMARY_TEST',boundary='execution.external_boundary')
            obs.finish('CLOSED')
            TestM12006ActionLifecycleBundleIntegrity._rewrite_artifact(
                path,'analysis/gpt_summary.json',lambda payload: payload.__setitem__('physical_input_state','NOT_SENT'))
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('GPT_SUMMARY_PHYSICAL_STATE_MISMATCH',result['errors'])

    def test_verifier_rejects_machine_summary_that_hides_recorder_loss(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-gpt-loss-truth',invocation_id='inv-gpt-loss-truth',max_recent=2,max_priority=8)
            obs.record('ready.requested',owner_system='anka_workflow',boundary='workflow.ready_request',account_id='acct-cra')
            for i in range(8):
                obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog',payload={'i':i})
            path=obs.export_incident('GPT_LOSS_TRUTH_TEST',boundary='workflow.ready_request',trace_spec=READY_TRACE)
            obs.finish('CLOSED')
            TestM12006ActionLifecycleBundleIntegrity._rewrite_artifact(
                path,'analysis/gpt_summary.json',lambda payload: payload.update({
                    'absence_is_conclusive':True,
                    'first_divergence_scope':'COMPLETE_RECORDER_EVIDENCE',
                }))
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('GPT_SUMMARY_CONCLUSIVENESS_MISMATCH',result['errors'])
            self.assertIn('GPT_SUMMARY_DIVERGENCE_SCOPE_MISMATCH',result['errors'])

    def test_verifier_rejects_machine_summary_that_hides_crash_tail_uncertainty(self):
        from anka_observability.recovery import recover_unclean_run
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-gpt-crash-tail',invocation_id='inv-gpt-crash-tail')
            obs.record('execution.input_may_have_sent',severity='SAFETY',owner_system='anka_execution',
                       boundary='execution.external_boundary',action_id='action-gpt-crash-tail',
                       physical_input_state='MAY_HAVE_SENT',failure_code='ACK_UNKNOWN')
            self.assertTrue(obs.flush_journals())
            path=recover_unclean_run(obs.folder)
            self.assertIsNotNone(path)
            TestM12006ActionLifecycleBundleIntegrity._rewrite_artifact(
                path,'analysis/gpt_summary.json',lambda payload: payload.__setitem__('source_tail_uncertain',False))
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('GPT_SUMMARY_SOURCE_TAIL_MISMATCH',result['errors'])

class TestM12006AsyncJournalFinalization(unittest.TestCase):
    def test_freeze_counts_writer_task_already_removed_from_queue(self):
        from threading import Event
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-inflight-pending',invocation_id='inv-inflight-pending',journal_queue_capacity=4)
            release=Event();entered=Event();real=obs._write_journal_task
            def slow(path,encoded):
                entered.set();release.wait(1.0);real(path,encoded)
            obs._write_journal_task=slow
            obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog')
            self.assertTrue(entered.wait(0.5))
            # Queue.qsize() is already zero because the writer owns the task, but
            # the frozen incident health must still report one unpersisted event.
            self.assertEqual(obs._journal_queue.qsize(),0)
            frozen=obs.freeze()
            self.assertEqual(frozen.journal_pending,1)
            release.set();self.assertTrue(obs.flush_journals());obs.finish('CLOSED')

    def test_final_run_state_write_is_bounded_when_filesystem_stalls(self):
        from threading import Event
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-final-state-stall',invocation_id='inv-final-state-stall')
            real=Path.write_text;release=Event();entered=Event()
            def slow_write(path,data,*args,**kwargs):
                if path.name.startswith('.run_state.final-'):
                    entered.set();release.wait(1.0)
                return real(path,data,*args,**kwargs)
            start=time.monotonic()
            with patch('pathlib.Path.write_text',new=slow_write):
                obs.finish('BLOCKED')
            elapsed=time.monotonic()-start
            self.assertTrue(entered.is_set())
            self.assertLess(elapsed,0.55)
            self.assertFalse(obs.available)
            self.assertIn('RUN_STATE_WRITE_TIMEOUT',obs.errors)
            release.set()
            writer=getattr(obs,'_final_state_writer',None)
            if writer is not None:writer.join(timeout=1.0)
            self.assertEqual(json.loads((obs.folder/'run_state.json').read_text())['state'],'RUNNING')
            self.assertFalse(any(p.name.startswith('.run_state.final-') for p in obs.folder.iterdir()))

class TestM12006IncidentStreamCrossChecks(unittest.TestCase):
    @staticmethod
    def _rewrite_bytes(path:Path,name:str,data:bytes):
        from hashlib import sha256
        from zipfile import ZIP_DEFLATED
        with ZipFile(path) as z:files={n:z.read(n) for n in z.namelist()}
        files[name]=data
        manifest=json.loads(files['manifest.json'])
        manifest['files'][name]={'sha256':sha256(data).hexdigest(),'bytes':len(data)}
        files['manifest.json']=(json.dumps(manifest,sort_keys=True,ensure_ascii=True,indent=2)+'\n').encode()
        with ZipFile(path,'w',ZIP_DEFLATED) as z:
            for n,b in files.items():z.writestr(n,b)

    def _bundle(self,td:str)->Path:
        obs=LocalDiagnostics(Path(td),run_id='run-stream-cross',invocation_id='inv-stream-cross')
        obs.record('execution.outcome_missing',severity='SAFETY',owner_system='anka_execution',boundary='execution.outcome',failure_code='MISSING',action_id='action-stream',physical_input_state='MAY_HAVE_SENT')
        obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog')
        return obs.export_incident('STREAM_TEST',boundary='execution.outcome')

    def test_verifier_rejects_primary_timeline_alias_disagreement(self):
        with tempfile.TemporaryDirectory() as td:
            path=self._bundle(td)
            with ZipFile(path) as z:data=z.read('timeline.jsonl')+b'\n'
            self._rewrite_bytes(path,'timeline.jsonl',data)
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('TIMELINE_ALIAS_MISMATCH',result['errors'])

    def test_verifier_rejects_priority_event_absent_from_primary_timeline(self):
        with tempfile.TemporaryDirectory() as td:
            path=self._bundle(td)
            with ZipFile(path) as z:
                rows=[json.loads(line) for line in z.read('logs/priority_timeline.jsonl').decode().splitlines() if line]
            self.assertTrue(rows)
            rows[0]['event_id']='evt-priority-not-primary'
            data=b''.join((json.dumps(row,sort_keys=True,separators=(',',':'))+'\n').encode() for row in rows)
            self._rewrite_bytes(path,'logs/priority_timeline.jsonl',data)
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('PRIORITY_TIMELINE_EVENT_NOT_IN_PRIMARY',result['errors'])

    def test_run_manifest_event_counts_must_match_shipped_timeline(self):
        with tempfile.TemporaryDirectory() as td:
            path=self._bundle(td)
            TestM12006ActionLifecycleBundleIntegrity._rewrite_artifact(
                path,'run_manifest.json',lambda run: run.__setitem__('bounded_recent_event_count',999))
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('RUN_MANIFEST_EVENT_COUNT_MISMATCH',result['errors'])

class TestM12006ConcurrentProducerIntegrity(unittest.TestCase):
    def test_many_producers_preserve_unique_monotonic_sequence_and_verifier_clean_bundle(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-concurrent',invocation_id='inv-concurrent',
                                 max_recent=1024,max_priority=512,journal_queue_capacity=4096,
                                 max_journal_bytes=8*1024*1024,max_priority_journal_bytes=2*1024*1024)
            errors=[]
            def producer(worker:int):
                try:
                    for i in range(120):
                        severity='SAFETY' if i%40==0 else 'INFO'
                        obs.record('workflow.concurrent_probe',severity=severity,owner_system='anka_workflow',
                                   boundary='workflow.concurrent_probe',account_id='acct-cra' if worker%2==0 else 'acct-enu',
                                   payload={'worker':worker,'i':i})
                except BaseException as exc:
                    errors.append(type(exc).__name__)
            threads=[threading.Thread(target=producer,args=(i,)) for i in range(8)]
            for t in threads:t.start()
            for t in threads:t.join(2)
            self.assertFalse(errors)
            self.assertTrue(all(not t.is_alive() for t in threads))
            self.assertEqual(obs.dropped,0)
            frozen=obs.freeze();seqs=[e['producer_seq'] for e in frozen.recent]
            self.assertEqual(len(seqs),960)
            self.assertEqual(len(seqs),len(set(seqs)))
            self.assertEqual(seqs,sorted(seqs))
            self.assertTrue(obs.flush_journals(timeout_seconds=3.0))
            path=obs.export_incident('CONCURRENT_PRODUCER_TEST',boundary='workflow.concurrent_probe')
            self.assertEqual(verify_incident(path)['status'],'PASS')
            obs.finish('CLOSED')

class TestM12006IncidentContextPinning(unittest.TestCase):
    def test_pre_failure_context_survives_long_post_failure_noise(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-pin-context',invocation_id='inv-pin-context',
                                 max_recent=16,max_priority=8,max_pinned=32,pin_window=8,
                                 journal_queue_capacity=4096,max_journal_bytes=8*1024*1024)
            for i in range(10):
                obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog',payload={'marker':'before','i':i})
            obs.record('execution.outcome_missing',severity='SAFETY',owner_system='anka_execution',
                       boundary='execution.outcome',failure_code='SERVER_PROOF_MISSING',
                       action_id='action-pin-context',physical_input_state='MAY_HAVE_SENT')
            pinned_ids={e['event_id'] for e in obs.pinned}
            self.assertTrue(pinned_ids)
            self.assertTrue(any(e.get('payload',{}).get('marker')=='before' for e in obs.pinned))
            for i in range(700):
                obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog',payload={'marker':'after','i':i})
            self.assertFalse(any(e.get('payload',{}).get('marker')=='before' for e in obs.recent))
            path=obs.export_incident('SERVER_PROOF_MISSING',boundary='execution.outcome')
            self.assertEqual(verify_incident(path)['status'],'PASS')
            with ZipFile(path) as z:
                rows=[json.loads(line) for line in z.read('logs/relevant_timeline.jsonl').decode().splitlines() if line]
                flight=json.loads(z.read('metadata/flight_recorder.json'))
            self.assertTrue(any(e.get('payload',{}).get('marker')=='before' for e in rows))
            self.assertGreater(flight['pinned_events_included'],0)
            obs.finish('BLOCKED')

    def test_repeated_same_anomaly_signature_does_not_repin_and_exhaust_reserve(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-pin-dedup',invocation_id='inv-pin-dedup',
                                 max_recent=16,max_priority=16,max_pinned=16,pin_window=8)
            for i in range(5):obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog',payload={'i':i})
            for i in range(20):
                obs.record('execution.rejected',severity='WARNING',owner_system='anka_execution',
                           boundary='execution.pre_input_authorization',failure_code='FOCUS_CHANGED',account_id='acct-cra',fight_epoch=1,
                           action_id=f'action-pin-{i}',payload={'i':i})
            # One signature pins one context window; repeated occurrences remain
            # visible through priority/recent lanes without consuming all pins.
            self.assertLessEqual(len(obs.pinned),8)
            self.assertEqual(obs.pinned_context_omissions,0)
            obs.finish('BLOCKED')

class TestM12006PhysicalInputRiskAggregation(unittest.TestCase):
    def test_later_not_sent_cannot_hide_earlier_may_have_sent(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-risk-summary',invocation_id='inv-risk-summary')
            obs.record('execution.input_may_have_sent',severity='SAFETY',owner_system='anka_execution',
                       boundary='execution.external_boundary',action_id='action-risk-1',attempt_id='attempt-risk-1',
                       physical_input_state='MAY_HAVE_SENT',failure_code='DRIVER_ACK_LOST')
            obs.record('execution.input_not_sent',severity='WARNING',owner_system='anka_execution',
                       boundary='execution.external_boundary',action_id='action-risk-2',attempt_id='attempt-risk-2',
                       physical_input_state='NOT_SENT',failure_code='FOCUS_CHANGED')
            path=obs.export_incident('DRIVER_ACK_LOST',boundary='execution.external_boundary',control_state='BLOCKED')
            self.assertEqual(verify_incident(path)['status'],'PASS')
            with ZipFile(path) as z:
                run=json.loads(z.read('run_manifest.json'))
                gpt=json.loads(z.read('analysis/gpt_summary.json'))
                text=z.read('GPT_READ_FIRST.md').decode()
            self.assertEqual(run['physical_input_state'],'MAY_HAVE_SENT')
            self.assertEqual(gpt['physical_input_state'],'MAY_HAVE_SENT')
            self.assertIn('Physical input state:** MAY_HAVE_SENT',text)
            obs.finish('BLOCKED')

    def test_verifier_rejects_downgraded_run_level_input_risk(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-risk-verify',invocation_id='inv-risk-verify')
            obs.record('execution.input_may_have_sent',severity='SAFETY',owner_system='anka_execution',
                       boundary='execution.external_boundary',action_id='action-risk-v',attempt_id='attempt-risk-v',
                       physical_input_state='MAY_HAVE_SENT',failure_code='ACK_UNKNOWN')
            path=obs.export_incident('ACK_UNKNOWN',boundary='execution.external_boundary',control_state='BLOCKED')
            TestM12006ActionLifecycleBundleIntegrity._rewrite_artifact(
                path,'run_manifest.json',lambda run: run.__setitem__('physical_input_state','NOT_SENT'))
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('RUN_MANIFEST_PHYSICAL_STATE_MISMATCH',result['errors'])
            obs.finish('BLOCKED')

class TestM12006PinnedExternalEventIdentity(unittest.TestCase):
    def test_external_duplicate_event_id_is_rejected_when_original_survives_only_in_pinned_context(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-pin-id',invocation_id='inv-pin-id',
                                 max_recent=2,max_priority=2,max_pinned=16,pin_window=2)
            obs.record('workflow.before_fault',owner_system='anka_workflow',boundary='workflow.watchdog')
            original_id=obs.recent[-1]['event_id']
            obs.record('execution.outcome_missing',severity='SAFETY',owner_system='anka_execution',
                       boundary='execution.outcome',failure_code='SERVER_PROOF_MISSING',
                       action_id='action-pin-id',physical_input_state='MAY_HAVE_SENT')
            # Evict the ordinary event from recent/priority while preserving the
            # pre-failure copy in the pinned incident-context reserve.
            for i in range(8):
                obs.record('workflow.after_fault',owner_system='anka_workflow',boundary='workflow.watchdog',payload={'i':i})
            self.assertFalse(any(e.get('event_id')==original_id for e in obs.recent))
            self.assertFalse(any(e.get('event_id')==original_id for e in obs.priority))
            self.assertTrue(any(e.get('event_id')==original_id for e in obs.pinned))
            external=DiagnosticEvent(
                schema_version=1,event_id=original_id,producer_seq=obs._seq+1,
                occurred_utc='2026-10-24T03:00:00Z',monotonic_ns=1,
                event_name='workflow.external_duplicate',severity='INFO',owner_system='anka_workflow',
                boundary='workflow.watchdog',invocation_id=obs.invocation_id,run_id=obs.run_id,
            )
            self.assertEqual(obs.emit(external),'DROPPED')
            self.assertIn('EXTERNAL_EVENT_ID_DUPLICATE',obs.errors)
            obs.finish('BLOCKED')

class TestM12006RedundantMetadataConsistency(unittest.TestCase):
    def _bundle(self, root:Path) -> tuple[LocalDiagnostics,Path]:
        obs=LocalDiagnostics(root,run_id='run-metadata-consistency',invocation_id='inv-metadata-consistency')
        obs.record('protocol.batch_decoded',owner_system='anka_protocol',boundary='protocol.transaction',
                   evidence_class='OBSERVED_EXTERNAL',payload={'batch_span_id':'batch-meta'})
        path=obs.export_incident('METADATA_CONSISTENCY_TEST',boundary='protocol.transaction')
        self.assertEqual(verify_incident(path)['status'],'PASS')
        return obs,path

    def test_verifier_rejects_flight_metadata_disagreement(self):
        with tempfile.TemporaryDirectory() as td:
            obs,path=self._bundle(Path(td))
            TestM12006ActionLifecycleBundleIntegrity._rewrite_artifact(
                path,'metadata/flight_recorder.json',
                lambda obj: obj.__setitem__('timeline_events_included',999))
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('FLIGHT_METADATA_MISMATCH',result['errors'])
            obs.finish('BLOCKED')

    def test_verifier_rejects_capture_protocol_status_disagreement(self):
        with tempfile.TemporaryDirectory() as td:
            obs,path=self._bundle(Path(td))
            TestM12006ActionLifecycleBundleIntegrity._rewrite_artifact(
                path,'metadata/capture_protocol_summary.json',
                lambda obj: obj.__setitem__('status','MISSING' if obj.get('status')!='MISSING' else 'PRESENT'))
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('CAPTURE_PROTOCOL_STATUS_MISMATCH',result['errors'])
            obs.finish('BLOCKED')

class TestM12006SecondaryTimelineCompleteness(unittest.TestCase):
    @staticmethod
    def _rewrite_bytes(path:Path,name:str,data:bytes,*,mutate_run=None,mutate_flight=None):
        from hashlib import sha256
        from zipfile import ZIP_DEFLATED
        with ZipFile(path) as z:
            files={n:z.read(n) for n in z.namelist()}
        files[name]=data
        if mutate_run is not None:
            run=json.loads(files['run_manifest.json']);mutate_run(run)
            files['run_manifest.json']=(json.dumps(run,sort_keys=True,ensure_ascii=True,indent=2)+'\n').encode('utf8')
        if mutate_flight is not None:
            flight=json.loads(files['metadata/flight_recorder.json']);mutate_flight(flight)
            files['metadata/flight_recorder.json']=(json.dumps(flight,sort_keys=True,ensure_ascii=True,indent=2)+'\n').encode('utf8')
        manifest=json.loads(files['manifest.json'])
        for changed in (name,'run_manifest.json','metadata/flight_recorder.json'):
            if changed in files:
                manifest['files'][changed]={'sha256':sha256(files[changed]).hexdigest(),'bytes':len(files[changed])}
        files['manifest.json']=(json.dumps(manifest,sort_keys=True,ensure_ascii=True,indent=2)+'\n').encode('utf8')
        with ZipFile(path,'w',ZIP_DEFLATED) as z:
            for n,b in files.items():z.writestr(n,b)

    def _bundle(self,root:Path)->tuple[LocalDiagnostics,Path]:
        obs=LocalDiagnostics(root,run_id='run-secondary-index',invocation_id='inv-secondary-index')
        obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog')
        obs.record('execution.outcome_missing',severity='SAFETY',owner_system='anka_execution',
                   boundary='execution.outcome',failure_code='SERVER_PROOF_MISSING',
                   action_id='action-secondary-index',physical_input_state='MAY_HAVE_SENT')
        path=obs.export_incident('SERVER_PROOF_MISSING',boundary='execution.outcome')
        self.assertEqual(verify_incident(path)['status'],'PASS')
        return obs,path

    def test_verifier_rejects_missing_error_index_row_even_when_manifest_is_rehashed(self):
        with tempfile.TemporaryDirectory() as td:
            obs,path=self._bundle(Path(td))
            self._rewrite_bytes(path,'logs/relevant_errors.jsonl',b'')
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('ERROR_TIMELINE_INCOMPLETE',result['errors'])
            obs.finish('BLOCKED')

    def test_verifier_rejects_missing_required_priority_row_even_when_counts_are_rewritten(self):
        with tempfile.TemporaryDirectory() as td:
            obs,path=self._bundle(Path(td))
            with ZipFile(path) as z:
                priority=[json.loads(line) for line in z.read('logs/priority_timeline.jsonl').decode().splitlines() if line]
            target='action-secondary-index'
            kept=[row for row in priority if row.get('action_id')!=target]
            blob=b''.join((json.dumps(row,sort_keys=True,ensure_ascii=True,separators=(',',':'))+'\n').encode('utf8') for row in kept)
            self._rewrite_bytes(
                path,'logs/priority_timeline.jsonl',blob,
                mutate_run=lambda run: run['flight_recorder'].__setitem__('priority_events_included',len(kept)),
                mutate_flight=lambda flight: flight.__setitem__('priority_events_included',len(kept)),
            )
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('PRIORITY_TIMELINE_INCOMPLETE',result['errors'])
            obs.finish('BLOCKED')

class TestM12006IncidentManifestTruth(unittest.TestCase):
    def test_outer_manifest_completeness_tracks_flight_recorder_loss(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-manifest-loss',invocation_id='inv-manifest-loss',max_recent=2,max_priority=4)
            for i in range(8):
                obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog',payload={'i':i})
            path=obs.export_incident('MANIFEST_LOSS_TEST',boundary='workflow.watchdog')
            self.assertEqual(verify_incident(path)['status'],'PASS')
            with ZipFile(path) as z:
                outer=json.loads(z.read('manifest.json'));run=json.loads(z.read('run_manifest.json'))
            self.assertEqual(run['evidence_completeness'],'PARTIAL')
            self.assertEqual(outer['completeness'],'PARTIAL')
            obs.finish('BLOCKED')

    def test_verifier_rejects_outer_manifest_completeness_lie(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-manifest-lie',invocation_id='inv-manifest-lie',max_recent=2,max_priority=4)
            for i in range(8):obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog',payload={'i':i})
            path=obs.export_incident('MANIFEST_LIE_TEST',boundary='workflow.watchdog')
            with ZipFile(path) as z:files={n:z.read(n) for n in z.namelist()}
            manifest=json.loads(files['manifest.json']);manifest['completeness']='PRESENT'
            files['manifest.json']=(json.dumps(manifest,sort_keys=True,ensure_ascii=True,indent=2)+'\n').encode('utf8')
            from zipfile import ZIP_DEFLATED
            with ZipFile(path,'w',ZIP_DEFLATED) as z:
                for n,b in files.items():z.writestr(n,b)
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('MANIFEST_COMPLETENESS_MISMATCH',result['errors'])
            obs.finish('BLOCKED')

    def test_primary_zip_runtime_failure_uses_fallback_instead_of_escaping(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-primary-runtime-fail',invocation_id='inv-primary-runtime-fail')
            obs.record('execution.outcome_missing',severity='SAFETY',owner_system='anka_execution',boundary='execution.outcome',failure_code='ACK_UNKNOWN',action_id='action-primary-runtime-fail',physical_input_state='MAY_HAVE_SENT')
            from anka_observability import bundle
            real=bundle._write_zip;calls={'n':0}
            def fail_once(path,artifacts,manifest):
                calls['n']+=1
                if calls['n']==1:raise RuntimeError('zip-layer-failure')
                return real(path,artifacts,manifest)
            with patch('anka_observability.bundle._write_zip',side_effect=fail_once):
                path=obs.export_incident('ACK_UNKNOWN',boundary='execution.outcome',control_state='BLOCKED')
            self.assertGreaterEqual(calls['n'],2)
            self.assertEqual(verify_incident(path)['status'],'PASS')
            with ZipFile(path) as z:manifest=json.loads(z.read('manifest.json'))
            self.assertTrue(manifest['primary_export_failed'])
            obs.finish('BLOCKED')

class TestM12006PartyReadyBundleDerivation(unittest.TestCase):
    def test_diverged_party_ready_bundle_recomputes_semantically_despite_fresh_finding_id(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-ready-semantic',invocation_id='inv-ready-semantic')
            try:
                for account in ('acct-cra','acct-enu'):
                    action='action-'+account
                    obs.record('ready.requested',owner_system='anka_workflow',boundary='workflow.ready_request',account_id=account,fight_epoch=1,action_id=action)
                    obs.record('execution.admitted',owner_system='anka_execution',boundary='execution.pre_input_authorization',account_id=account,fight_epoch=1,action_id=action)
                    obs.record('execution.input_sent',owner_system='anka_execution',boundary='execution.external_boundary',account_id=account,fight_epoch=1,action_id=action)
                obs.record('protocol.ready_observed',owner_system='anka_protocol',boundary='protocol.ready_observation',account_id='acct-cra',fight_epoch=1,payload={'batch_span_id':'batch-cra'})
                obs.record('canonical.ready_committed',owner_system='anka_canonical',boundary='canonical.ready_commit',account_id='acct-cra',fight_epoch=1,payload={'batch_span_id':'batch-cra'})
                path=obs.export_incident('READY_STALL',boundary='protocol.ready_observation',trace_spec=READY_TRACE)
                result=verify_incident(path)
                self.assertEqual(result['status'],'PASS',result['errors'])
            finally:
                obs.finish('BLOCKED')

class TestM12006ForensicCertaintyUnderEvidenceLoss(unittest.TestCase):
    def test_missing_edge_with_complete_recorder_can_be_identified(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-complete-divergence',invocation_id='inv-complete-divergence')
            obs.record('ready.requested',owner_system='anka_workflow',boundary='workflow.ready_request',account_id='acct-cra')
            path=obs.export_incident('READY_PATH_TEST',boundary='workflow.ready_request',trace_spec=READY_TRACE)
            self.assertEqual(verify_incident(path)['status'],'PASS')
            with ZipFile(path) as z:gpt=json.loads(z.read('analysis/gpt_summary.json'))
            self.assertEqual(gpt['finding_status'],'DIVERGENCE_IDENTIFIED')
            self.assertTrue(gpt['absence_is_conclusive'])
            self.assertEqual(gpt['first_divergence_scope'],'COMPLETE_RECORDER_EVIDENCE')
            obs.finish('BLOCKED')

    def test_missing_edge_with_known_recorder_loss_is_only_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-partial-divergence',invocation_id='inv-partial-divergence',max_recent=2,max_priority=8)
            obs.record('ready.requested',owner_system='anka_workflow',boundary='workflow.ready_request',account_id='acct-cra')
            for i in range(8):
                obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog',payload={'i':i})
            self.assertGreater(obs.recent_overwrites,0)
            path=obs.export_incident('READY_PATH_TEST',boundary='workflow.ready_request',trace_spec=READY_TRACE)
            result=verify_incident(path);self.assertEqual(result['status'],'PASS',result['errors'])
            with ZipFile(path) as z:
                gpt=json.loads(z.read('analysis/gpt_summary.json'));readme=z.read('GPT_READ_FIRST.md').decode()
            self.assertEqual(gpt['finding_status'],'DIVERGENCE_CANDIDATE')
            self.assertFalse(gpt['absence_is_conclusive'])
            self.assertEqual(gpt['first_divergence_scope'],'INCLUDED_EVIDENCE_ONLY')
            self.assertIn('DIVERGENCE_CANDIDATE',readme)
            obs.finish('BLOCKED')

class TestM12006UncleanRunRecovery(unittest.TestCase):
    def test_unclean_durable_journal_becomes_partial_verifier_clean_incident(self):
        from anka_observability.recovery import recover_unclean_run
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            obs=LocalDiagnostics(root,run_id='run-crash-recovery',invocation_id='inv-crash-recovery')
            obs.record('execution.input_may_have_sent',severity='SAFETY',owner_system='anka_execution',
                       boundary='execution.external_boundary',failure_code='ACK_UNKNOWN',
                       action_id='action-before-crash',physical_input_state='MAY_HAVE_SENT')
            self.assertTrue(obs.flush_journals())
            # Simulate an external process kill: intentionally do not call finish().
            path=recover_unclean_run(obs.folder)
            self.assertIsNotNone(path)
            self.assertEqual(verify_incident(path)['status'],'PASS')
            with ZipFile(path) as z:
                run=json.loads(z.read('run_manifest.json'))
                outer=json.loads(z.read('manifest.json'))
                gpt=json.loads(z.read('analysis/gpt_summary.json'))
                read_first=z.read('GPT_READ_FIRST.md').decode()
                rows=[json.loads(line) for line in z.read('timeline.jsonl').decode().splitlines() if line]
            self.assertTrue(run['flight_recorder']['source_tail_uncertain'])
            self.assertTrue(gpt['source_tail_uncertain'])
            self.assertFalse(gpt['absence_is_conclusive'])
            self.assertEqual(gpt['first_divergence_scope'],'INCLUDED_EVIDENCE_ONLY')
            self.assertIn('Crash-tail warning',read_first)
            self.assertEqual(run['evidence_completeness'],'PARTIAL')
            self.assertEqual(outer['completeness'],'PARTIAL')
            self.assertIn('action-before-crash',{row.get('action_id') for row in rows})
            self.assertIsNone(recover_unclean_run(obs.folder))

    def test_unclean_recovery_quarantines_monotonic_regression_and_stays_verifier_clean(self):
        from anka_observability.recovery import recover_unclean_run
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            obs=LocalDiagnostics(root,run_id='run-crash-order',invocation_id='inv-crash-order')
            obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog',payload={'i':1})
            obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog',payload={'i':2})
            self.assertTrue(obs.flush_journals())
            journal=obs.folder/'events.jsonl'
            rows=[json.loads(line) for line in journal.read_text().splitlines() if line]
            rows[1]['monotonic_ns']=max(0,rows[0]['monotonic_ns']-1)
            journal.write_text('\n'.join(json.dumps(row,sort_keys=True,separators=(',',':')) for row in rows)+'\n')
            path=recover_unclean_run(obs.folder)
            self.assertIsNotNone(path)
            result=verify_incident(path)
            self.assertEqual(result['status'],'PASS',result['errors'])
            with ZipFile(path) as z:
                run=json.loads(z.read('run_manifest.json'))
                timeline=[json.loads(line) for line in z.read('timeline.jsonl').decode().splitlines() if line]
            self.assertEqual(len(timeline),1)
            self.assertIn('RECOVERY_MONOTONIC_REGRESSION_SKIPPED',run['observer_errors'])
            self.assertEqual(run['evidence_completeness'],'PARTIAL')
            self.assertTrue((obs.folder/'unclean_recovery.json').exists())

    def test_unclean_recovery_never_marks_failed_self_verification_as_handled(self):
        from anka_observability.recovery import recover_unclean_run
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            obs=LocalDiagnostics(root,run_id='run-crash-selfcheck',invocation_id='inv-crash-selfcheck')
            obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog')
            self.assertTrue(obs.flush_journals())
            with patch('anka_observability.recovery.verify_incident',return_value={'status':'FAIL','errors':['SIMULATED']}):
                self.assertIsNone(recover_unclean_run(obs.folder))
            self.assertFalse((obs.folder/'unclean_recovery.json').exists())
            incidents=list((obs.folder/'incidents').glob('*.zip'))
            self.assertEqual(incidents,[])

    def test_unclean_recovery_rejects_symlinked_journal_instead_of_reading_external_content(self):
        from anka_observability.recovery import recover_unclean_run
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            obs=LocalDiagnostics(root,run_id='run-crash-symlink',invocation_id='inv-crash-symlink')
            obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog')
            self.assertTrue(obs.flush_journals())
            journal=obs.folder/'events.jsonl';external=root/'outside.jsonl'
            external.write_bytes(journal.read_bytes())
            journal.unlink()
            try:journal.symlink_to(external)
            except (OSError,NotImplementedError):self.skipTest('symlink unavailable')
            path=recover_unclean_run(obs.folder)
            self.assertIsNotNone(path)
            result=verify_incident(path);self.assertEqual(result['status'],'PASS',result['errors'])
            with ZipFile(path) as z:
                run=json.loads(z.read('run_manifest.json'))
                rows=[line for line in z.read('timeline.jsonl').decode().splitlines() if line]
            self.assertEqual(rows,[])
            self.assertIn('RECOVERY_JOURNAL_SYMLINK_REJECTED',run['observer_errors'])

    def test_running_state_records_invocation_identity_for_crash_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-state-identity',invocation_id='inv-state-identity')
            state=json.loads((obs.folder/'run_state.json').read_text())
            self.assertEqual(state['run_id'],'run-state-identity')
            self.assertEqual(state['invocation_id'],'inv-state-identity')
            self.assertEqual(state['state'],'RUNNING')
            obs.finish('CLOSED')

    def test_exact_incident_trigger_survives_saturated_causal_skeleton(self):
        td=tempfile.TemporaryDirectory();self.addCleanup(td.cleanup)
        obs=LocalDiagnostics(Path(td.name),run_id='run-trigger-reserve',invocation_id='inv-trigger-reserve',
                             max_recent=1800,max_priority=1800,max_pinned=256)
        self.addCleanup(obs.finish,'BLOCKED')
        for i in range(1500):
            obs.record('execution.admitted',severity='SETTLEMENT',owner_system='anka_execution',
                       boundary='execution.pre_input_authorization',action_id=f'action-flood-{i:04d}',
                       attempt_id=f'attempt-flood-{i:04d}',physical_input_state='NOT_SENT')
        obs.record('execution.outcome_missing',severity='SAFETY',owner_system='anka_execution',
                   boundary='execution.outcome',failure_code='FINAL_FAILURE',
                   action_id='action-final',attempt_id='attempt-final',physical_input_state='MAY_HAVE_SENT')
        path=obs.export_incident('FINAL_FAILURE',boundary='execution.outcome')
        result=verify_incident(path)
        self.assertEqual(result['status'],'PASS',result['errors'])
        with ZipFile(path) as z:
            rows=[json.loads(line) for line in z.read('timeline.jsonl').decode().splitlines() if line]
            run=json.loads(z.read('run_manifest.json'))
        failures=[row for row in rows if row.get('failure_code')=='FINAL_FAILURE']
        self.assertEqual(len(failures),1)
        self.assertEqual(failures[0]['action_id'],'action-final')
        flight=run['flight_recorder']
        self.assertEqual(flight['incident_trigger_events_included'],1)
        self.assertEqual(flight['incident_trigger_event_ids'],[failures[0]['event_id']])
        self.assertGreater(flight['causal_skeleton_events_omitted_for_size'],0)

class TestM12006LongRunForensicSchema(unittest.TestCase):
    def test_more_than_forty_action_lifecycles_remain_structurally_valid(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-many-actions',invocation_id='inv-many-actions',
                                 max_recent=512,max_priority=256,max_pinned=128)
            for i in range(45):
                action=f'action-long-{i:02d}'
                attempt=f'attempt-long-{i:02d}'
                obs.record('execution.admitted',owner_system='anka_execution',boundary='execution.pre_input_authorization',
                           action_id=action,attempt_id=attempt,physical_input_state='NOT_SENT')
                obs.record('execution.input_sent',owner_system='anka_execution',boundary='execution.external_boundary',
                           action_id=action,attempt_id=attempt,physical_input_state='SENT')
                obs.record('execution.outcome_settled',severity='SETTLEMENT',owner_system='anka_execution',boundary='execution.outcome',
                           action_id=action,attempt_id=attempt,physical_input_state='SENT')
            path=obs.export_incident('LONG_RUN_FORENSIC_TEST',boundary='execution.outcome')
            result=verify_incident(path)
            self.assertEqual(result['status'],'PASS',result['errors'])
            with ZipFile(path) as z:
                report=json.loads(z.read('analysis/action_lifecycles.json'))
            self.assertEqual(report['total_action_count'],45)
            self.assertEqual(len(report['actions']),32)
            self.assertEqual(report['actions_omitted'],13)
            self.assertTrue(all(isinstance(row,dict) for row in report['actions']))
            obs.finish('CLOSED')

    def test_early_unresolved_action_is_retained_ahead_of_later_successes(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-risk-retention',invocation_id='inv-risk-retention',
                                 max_recent=512,max_priority=256,max_pinned=128)
            risky='action-risk-00';attempt='attempt-risk-00'
            obs.record('execution.admitted',owner_system='anka_execution',boundary='execution.pre_input_authorization',
                       action_id=risky,attempt_id=attempt,physical_input_state='NOT_SENT')
            obs.record('execution.input_may_have_sent',severity='SAFETY',owner_system='anka_execution',boundary='execution.external_boundary',
                       action_id=risky,attempt_id=attempt,physical_input_state='MAY_HAVE_SENT',failure_code='ACK_UNKNOWN')
            for i in range(45):
                action=f'action-ok-{i:02d}';attempt=f'attempt-ok-{i:02d}'
                obs.record('execution.admitted',owner_system='anka_execution',boundary='execution.pre_input_authorization',
                           action_id=action,attempt_id=attempt,physical_input_state='NOT_SENT')
                obs.record('execution.input_sent',owner_system='anka_execution',boundary='execution.external_boundary',
                           action_id=action,attempt_id=attempt,physical_input_state='SENT')
                obs.record('execution.outcome_settled',severity='SETTLEMENT',owner_system='anka_execution',boundary='execution.outcome',
                           action_id=action,attempt_id=attempt,physical_input_state='SENT')
            path=obs.export_incident('LONG_RUN_RISK_RETENTION',boundary='execution.outcome')
            result=verify_incident(path);self.assertEqual(result['status'],'PASS',result['errors'])
            with ZipFile(path) as z:report=json.loads(z.read('analysis/action_lifecycles.json'))
            by_id={row['action_id']:row for row in report['actions']}
            self.assertIn(risky,by_id)
            self.assertEqual(by_id[risky]['state'],'MAY_HAVE_SENT_UNRESOLVED')
            self.assertEqual(report['selection_policy'],'RISK_FIRST_THEN_RECENT')
            self.assertEqual(report['priority_action_count'],1)
            self.assertEqual(report['priority_actions_omitted'],0)
            self.assertEqual(len(report['actions']),32)
            obs.finish('BLOCKED')

class TestM12006UnsettledActionContextWindow(unittest.TestCase):
    def test_unsettled_action_keeps_later_semantic_context_until_next_same_account_action(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-context-window',invocation_id='inv-context-window')
            a1='action-context-a';a2='action-context-b'
            obs.record('workflow.action_requested',owner_system='anka_workflow',boundary='workflow.action_authorization',
                       account_id='acct-cra',fight_epoch=5,turn_epoch=7,action_id=a1,
                       payload={'scope':'TURN','kind':'CAST','plan_id':'plan-a'})
            obs.record('execution.admitted',owner_system='anka_execution',boundary='execution.pre_input_authorization',
                       account_id='acct-cra',fight_epoch=5,turn_epoch=7,action_id=a1,physical_input_state='NOT_SENT')
            obs.record('execution.input_sent',owner_system='anka_execution',boundary='execution.external_boundary',
                       account_id='acct-cra',fight_epoch=5,turn_epoch=7,action_id=a1,physical_input_state='SENT')
            first=obs.record('protocol.state_observed',owner_system='anka_protocol',boundary='protocol.semantic_observation',
                       account_id='acct-cra',fight_epoch=5,turn_epoch=7,evidence_class='OBSERVED_EXTERNAL')
            self.assertIn(first,('RECORDED','DROPPED'))
            obs.record('canonical.state_committed',owner_system='anka_canonical',boundary='canonical.commit',
                       account_id='acct-cra',fight_epoch=5,turn_epoch=7,evidence_class='AUTHORITY_COMMITTED')
            obs.record('workflow.action_requested',owner_system='anka_workflow',boundary='workflow.action_authorization',
                       account_id='acct-cra',fight_epoch=5,turn_epoch=7,action_id=a2,
                       payload={'scope':'TURN','kind':'END_TURN','plan_id':'plan-b'})
            obs.record('protocol.after_next_action',owner_system='anka_protocol',boundary='protocol.semantic_observation',
                       account_id='acct-cra',fight_epoch=5,turn_epoch=7,evidence_class='OBSERVED_EXTERNAL')
            path=obs.export_incident('UNSETTLED_CONTEXT_WINDOW',boundary='execution.outcome')
            result=verify_incident(path);self.assertEqual(result['status'],'PASS',result['errors'])
            with ZipFile(path) as z:report=json.loads(z.read('analysis/action_lifecycles.json'))
            row=next(x for x in report['actions'] if x['action_id']==a1)
            names={x['event_name'] for x in row['nearby_semantic_context']}
            self.assertIn('protocol.state_observed',names)
            self.assertIn('canonical.state_committed',names)
            self.assertNotIn('protocol.after_next_action',names)
            self.assertEqual(row['semantic_context_window_end'],'NEXT_SAME_ACCOUNT_ACTION')
            self.assertFalse(row['nearby_semantic_context_is_causal_proof'])
            obs.finish('BLOCKED')

class TestM12006SanitizationCompleteness(unittest.TestCase):
    def test_payload_truncation_is_counted_and_marks_bundle_partial(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-truncated-payload',invocation_id='inv-truncated-payload')
            obs.record('decision.large_diagnostic_context',owner_system='anka_decision',boundary='decision.frame',
                       payload={'candidates':list(range(60))})
            self.assertEqual(obs.sanitization_truncations,1)
            path=obs.export_incident('TRUNCATED_DIAGNOSTIC_CONTEXT',boundary='decision.frame')
            result=verify_incident(path)
            self.assertEqual(result['status'],'PASS',result['errors'])
            with ZipFile(path) as z:
                run=json.loads(z.read('run_manifest.json'))
                rows=[json.loads(line) for line in z.read('timeline.jsonl').decode().splitlines() if line]
            self.assertEqual(run['flight_recorder']['sanitization_truncations'],1)
            self.assertEqual(run['evidence_completeness'],'PARTIAL')
            self.assertEqual(rows[0]['payload']['__diagnostic_truncation__']['candidates'],20)
            obs.finish('CLOSED')

class TestM12006RecoveredTruncationTruth(unittest.TestCase):
    def test_unclean_recovery_preserves_payload_truncation_as_partial_evidence(self):
        from anka_observability.recovery import recover_unclean_run
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            obs=LocalDiagnostics(root,run_id='run-crash-truncated',invocation_id='inv-crash-truncated')
            obs.record('decision.large_context',owner_system='anka_decision',boundary='decision.frame',payload={'rows':list(range(60))})
            self.assertTrue(obs.flush_journals())
            path=recover_unclean_run(obs.folder)
            self.assertIsNotNone(path)
            result=verify_incident(path)
            self.assertEqual(result['status'],'PASS',result['errors'])
            with ZipFile(path) as z:
                run=json.loads(z.read('run_manifest.json'))
            self.assertGreaterEqual(run['flight_recorder']['sanitization_truncations'],1)
            self.assertEqual(run['evidence_completeness'],'PARTIAL')
            # Simulated crash: avoid finish(), but ensure its daemon has already
            # drained before TemporaryDirectory teardown.
            self.assertTrue(obs.flush_journals())

class TestM12006ExternalDiagnosticAdmission(unittest.TestCase):
    def test_malformed_external_timestamp_is_rejected_before_bundle_poisoning(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-external-contract',invocation_id='inv-external-contract')
            bad=DiagnosticEvent(1,'evt-external-bad-time','debug.external','INFO','not-a-time',1,1,
                                obs.invocation_id,obs.run_id,owner_system='anka_observability')
            self.assertEqual(obs.emit(bad),'DROPPED')
            self.assertIn('EXTERNAL_EVENT_TIMESTAMP_INVALID',obs.errors)
            obs.record('observability.contract_rejection',owner_system='anka_observability',boundary='observability.event_admission')
            path=obs.export_incident('EXTERNAL_EVENT_REJECTED',boundary='observability.event_admission')
            self.assertEqual(verify_incident(path)['status'],'PASS')
            obs.finish('BLOCKED')

    def test_malformed_external_event_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-external-id',invocation_id='inv-external-id')
            bad=DiagnosticEvent(1,'bad-id','debug.external','INFO','2026-10-24T00:00:00Z',1,1,
                                obs.invocation_id,obs.run_id,owner_system='anka_observability')
            self.assertEqual(obs.emit(bad),'DROPPED')
            self.assertIn('EXTERNAL_EVENT_ID_INVALID',obs.errors)
            obs.finish('BLOCKED')

    def test_recorder_identity_namespace_is_validated_at_creation(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError,'INVALID_DIAGNOSTIC_RUN_ID'):
                LocalDiagnostics(Path(td),run_id='bad-run',invocation_id='inv-good')
            with self.assertRaisesRegex(ValueError,'INVALID_DIAGNOSTIC_INVOCATION_ID'):
                LocalDiagnostics(Path(td),run_id='run-good',invocation_id='bad-inv')

class TestM12006TimelineOrderingIntegrity(unittest.TestCase):
    def test_foreign_monotonic_regression_is_rejected_at_admission(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-mono-admission',invocation_id='inv-mono-admission')
            obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog')
            bad=DiagnosticEvent(1,'evt-mono-regression','debug.external','INFO','2026-10-24T00:00:00Z',1,obs._seq+1,
                                obs.invocation_id,obs.run_id,owner_system='anka_observability')
            self.assertEqual(obs.emit(bad),'DROPPED')
            self.assertIn('EVENT_MONOTONIC_REGRESSION',obs.errors)
            path=obs.export_incident('MONOTONIC_REJECTION_TEST',boundary='observability.event_admission')
            self.assertEqual(verify_incident(path)['status'],'PASS')
            obs.finish('BLOCKED')

    def test_verifier_rejects_rehashed_primary_timeline_reordering(self):
        from hashlib import sha256
        from zipfile import ZIP_DEFLATED
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-order-tamper',invocation_id='inv-order-tamper')
            obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog',payload={'i':1})
            obs.record('workflow.heartbeat',owner_system='anka_workflow',boundary='workflow.watchdog',payload={'i':2})
            path=obs.export_incident('TIMELINE_ORDER_TEST',boundary='workflow.watchdog')
            with ZipFile(path) as z:files={n:z.read(n) for n in z.namelist()}
            lines=[line for line in files['timeline.jsonl'].splitlines(keepends=True) if line.strip()]
            self.assertGreaterEqual(len(lines),2)
            tampered=b''.join(reversed(lines))
            files['timeline.jsonl']=tampered;files['logs/relevant_timeline.jsonl']=tampered
            manifest=json.loads(files['manifest.json'])
            for name in ('timeline.jsonl','logs/relevant_timeline.jsonl'):
                manifest['files'][name]={'sha256':sha256(files[name]).hexdigest(),'bytes':len(files[name])}
            files['manifest.json']=(json.dumps(manifest,sort_keys=True,ensure_ascii=True,indent=2)+'\n').encode('utf8')
            with ZipFile(path,'w',ZIP_DEFLATED) as z:
                for n,b in files.items():z.writestr(n,b)
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('TIMELINE_ORDER_INVALID',result['errors'])
            obs.finish('BLOCKED')

class TestM12006RecoveryScanFairness(unittest.TestCase):
    def test_recent_clean_runs_do_not_starve_older_unclean_recovery(self):
        import os
        from anka_observability.recovery import recover_unclean_runs
        with tempfile.TemporaryDirectory() as td:
            runtime=Path(td)
            old=LocalDiagnostics(runtime,run_id='run-old-unclean',invocation_id='inv-old-unclean')
            old.record('execution.input_may_have_sent',severity='SAFETY',owner_system='anka_execution',
                       boundary='execution.external_boundary',failure_code='ACK_UNKNOWN',
                       action_id='action-old-unclean',physical_input_state='MAY_HAVE_SENT')
            self.assertTrue(old.flush_journals())
            base=time.time()+100
            for i in range(4):
                folder=runtime/'runs'/f'run-clean-{i}'
                folder.mkdir()
                (folder/'run_state.json').write_text(json.dumps({'run_id':folder.name,'invocation_id':f'inv-clean-{i}','state':'CLOSED'})+'\n')
                os.utime(folder,(base+i,base+i))
            os.utime(old.folder,(base-100,base-100))
            recovered=recover_unclean_runs(runtime,current_run_id='run-current',max_runs=1)
            self.assertEqual(len(recovered),1)
            self.assertEqual(recovered[0].parent.parent.name,'run-old-unclean')
            self.assertEqual(verify_incident(recovered[0])['status'],'PASS')

    def test_final_run_state_preserves_invocation_identity(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-final-identity',invocation_id='inv-final-identity')
            obs.finish('CLOSED')
            state=json.loads((obs.folder/'run_state.json').read_text())
            self.assertEqual(state['run_id'],'run-final-identity')
            self.assertEqual(state['invocation_id'],'inv-final-identity')
            self.assertEqual(state['state'],'CLOSED')

class TestM12006FullLifecycleForensicIndexes(unittest.TestCase):
    def test_q9_bundle_indexes_complete_workflow_cycle_and_end_turn_handoff(self):
        from anka_app.zero_input_integration import ZeroInputQ9Scenario
        with tempfile.TemporaryDirectory() as td:
            s=ZeroInputQ9Scenario(Path(td))
            try:
                s.happy_path()
                path=s.observer.export_incident('Q9_FULL_CHAIN_FORENSIC',boundary='integration.q9')
                result=verify_incident(path)
                self.assertEqual(result['status'],'PASS',result['errors'])
                with ZipFile(path) as z:
                    lifecycle=json.loads(z.read('analysis/workflow_lifecycle.json'))
                    handoff=json.loads(z.read('analysis/turn_handoff.json'))
                    gpt=json.loads(z.read('analysis/gpt_summary.json'))
                    readme=z.read('GPT_READ_FIRST.md').decode()
                self.assertEqual(lifecycle['status'],'COMPLETE_CYCLE')
                self.assertEqual(lifecycle['current_phase'],'COMPLETED')
                self.assertEqual(handoff['status'],'COMPLETE')
                self.assertEqual(handoff['next_owner_account_id'],'acct-enu')
                self.assertEqual(gpt['workflow_lifecycle_status'],'COMPLETE_CYCLE')
                self.assertEqual(gpt['turn_handoff_status'],'COMPLETE')
                self.assertIn('Workflow lifecycle index:',readme)
                self.assertIn('End Turn handoff index:',readme)
            finally:s.close()

    def test_end_turn_sent_without_next_owner_is_reported_without_false_root_cause(self):
        from anka_observability.forensics import turn_handoff_report
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-endturn-gap',invocation_id='inv-endturn-gap')
            aid='action-endturn-gap'
            obs.record('workflow.action_requested',owner_system='anka_workflow',boundary='workflow.action_authorization',
                       account_id='acct-cra',fight_epoch=7,turn_epoch=12,action_id=aid,payload={'scope':'TURN','kind':'END_TURN'})
            obs.record('execution.admitted',owner_system='anka_execution',boundary='execution.pre_input_authorization',
                       account_id='acct-cra',fight_epoch=7,turn_epoch=12,action_id=aid,physical_input_state='NOT_SENT')
            obs.record('execution.input_sent',owner_system='anka_execution',boundary='execution.external_boundary',
                       account_id='acct-cra',fight_epoch=7,turn_epoch=12,action_id=aid,physical_input_state='SENT')
            obs.record('execution.outcome_settled',severity='SETTLEMENT',owner_system='anka_execution',boundary='execution.outcome_settlement',
                       account_id='acct-cra',fight_epoch=7,turn_epoch=12,action_id=aid,physical_input_state='SENT')
            report=turn_handoff_report(obs.recent)
            self.assertEqual(report['status'],'SETTLED_NEXT_OWNER_MISSING')
            self.assertIsNone(report['next_owner_event_id'])
            obs.finish('BLOCKED')


class TestM12006RecorderFacadeNeverControlsRuntime(unittest.TestCase):
    def test_pathological_payload_mapping_cannot_escape_record(self):
        class ExplodingMapping(dict):
            def items(self):
                raise RuntimeError('diagnostic-only failure')
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-record-total',invocation_id='inv-record-total')
            result=obs.record('debug.pathological_payload',payload=ExplodingMapping({'safe':1}))
            self.assertEqual(result,'UNAVAILABLE')
            self.assertEqual(obs.dropped,1)
            self.assertIn('OBSERVER_RECORD_FAILED:RUNTIMEERROR',obs.errors)
            # A later ordinary event is still accepted; the observer failure did
            # not poison gameplay/startup callers or the recorder lifecycle.
            self.assertIn(obs.record('debug.after_payload_failure'),('RECORDED','DROPPED','UNAVAILABLE'))
            obs.finish('CLOSED')


class TestM12006SnapshotExportTruth(unittest.TestCase):
    def test_snapshot_omission_is_explicit_partial_and_not_advertised_as_shipped(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-snapshot-bound',invocation_id='inv-snapshot-bound')
            near_limit={f'k{i}':'x'*1012 for i in range(32)}
            self.assertEqual(obs.register_snapshot('near_limit_snapshot',near_limit),'RECORDED')
            path=obs.export_incident('SNAPSHOT_BOUND_TEST',boundary='observability.snapshot')
            result=verify_incident(path);self.assertEqual(result['status'],'PASS',result['errors'])
            with ZipFile(path) as z:
                index=json.loads(z.read('analysis/snapshot_index.json'))
                gpt=json.loads(z.read('analysis/gpt_summary.json'))
                run=json.loads(z.read('run_manifest.json'))
                names=set(z.namelist())
            self.assertNotIn('near_limit_snapshot',index['snapshots'])
            self.assertNotIn('snapshots/near_limit_snapshot.json',names)
            self.assertEqual(index['omitted'],[{'name':'near_limit_snapshot','reason':'SERIALIZED_SIZE_LIMIT'}])
            self.assertEqual(gpt['snapshot_names'],[])
            self.assertEqual(gpt['snapshot_omissions'],index['omitted'])
            self.assertEqual(run['evidence_completeness'],'PARTIAL')
            self.assertEqual(run['flight_recorder']['snapshot_export_omissions'],1)
            obs.finish('BLOCKED')

    def test_verifier_rejects_rehashed_snapshot_index_that_claims_unshipped_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-snapshot-index',invocation_id='inv-snapshot-index')
            self.assertEqual(obs.register_snapshot('host_observation',{'status':'OK'}),'RECORDED')
            path=obs.export_incident('SNAPSHOT_INDEX_TEST',boundary='observability.snapshot')
            TestM12006ActionLifecycleBundleIntegrity._rewrite_artifact(
                path,'analysis/snapshot_index.json',lambda payload: payload['snapshots'].append('phantom_snapshot'))
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('SNAPSHOT_INDEX_SHIPPED_MISMATCH',result['errors'])
            obs.finish('CLOSED')


class TestM12006DiagnosisAliasIntegrity(unittest.TestCase):
    def test_verifier_rejects_rehashed_root_diagnosis_disagreement(self):
        with tempfile.TemporaryDirectory() as td:
            obs=LocalDiagnostics(Path(td),run_id='run-diag-alias',invocation_id='inv-diag-alias')
            obs.record('execution.outcome_missing',severity='SAFETY',owner_system='anka_execution',
                       boundary='execution.outcome',failure_code='OUTCOME_MISSING',action_id='action-diag-alias',
                       physical_input_state='MAY_HAVE_SENT')
            path=obs.export_incident('OUTCOME_MISSING',boundary='execution.outcome')
            TestM12006ActionLifecycleBundleIntegrity._rewrite_artifact(
                path,'diagnosis.json',lambda payload: payload.__setitem__('confidence','HIGH'))
            result=verify_incident(path)
            self.assertEqual(result['status'],'FAIL')
            self.assertIn('DIAGNOSIS_ALIAS_MISMATCH',result['errors'])
            obs.finish('BLOCKED')
