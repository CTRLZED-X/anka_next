import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from anka_observability.api import LocalDiagnostics
from anka_observability.bundle import verify_incident
from anka_observability.forensics import READY_TRACE, action_lifecycle_report
from anka_observability.redaction import has_unredacted_sensitive_data


class TestAgent07EvidenceLossCertainty(unittest.TestCase):
    @staticmethod
    def _partial_ready_incident(root: Path):
        obs = LocalDiagnostics(
            root,
            run_id='run-agent07-loss',
            invocation_id='inv-agent07-loss',
            max_recent=32,
            max_priority=16,
            max_journal_bytes=1,
        )
        obs.record(
            'ready.requested',
            owner_system='anka_workflow',
            boundary='workflow.ready_request',
            account_id='acct-cra',
        )
        obs.record(
            'execution.admitted',
            owner_system='anka_execution',
            boundary='execution.pre_input_authorization',
            account_id='acct-cra',
            physical_input_state='NOT_SENT',
        )
        obs.record(
            'execution.input_sent',
            owner_system='anka_execution',
            boundary='execution.external_boundary',
            account_id='acct-cra',
            physical_input_state='SENT',
        )
        obs.record(
            'protocol.ready_missing',
            severity='ERROR',
            owner_system='anka_protocol',
            boundary='protocol.ready_observation',
            account_id='acct-cra',
            failure_code='READY_SERVER_EVIDENCE_MISSING',
            physical_input_state='SENT',
        )
        path = obs.export_incident(
            'READY_SERVER_EVIDENCE_MISSING',
            boundary='protocol.ready_observation',
            trace_spec=READY_TRACE,
            control_state='BLOCKED',
        )
        return obs, path

    @staticmethod
    def _rewrite_json_artifacts(path: Path, mutations: dict[str, object]) -> None:
        with ZipFile(path) as z:
            files = {name: z.read(name) for name in z.namelist()}
        manifest = json.loads(files['manifest.json'])
        for name, mutate in mutations.items():
            payload = json.loads(files[name])
            mutate(payload)
            blob = (json.dumps(payload, sort_keys=True, ensure_ascii=True, indent=2) + '\n').encode('utf8')
            files[name] = blob
            manifest['files'][name] = {'sha256': sha256(blob).hexdigest(), 'bytes': len(blob)}
        files['manifest.json'] = (json.dumps(manifest, sort_keys=True, ensure_ascii=True, indent=2) + '\n').encode('utf8')
        with ZipFile(path, 'w', ZIP_DEFLATED) as z:
            for name, blob in files.items():
                z.writestr(name, blob)

    def test_known_recorder_loss_downgrades_retained_high_confidence(self):
        with tempfile.TemporaryDirectory() as td:
            obs, path = self._partial_ready_incident(Path(td))
            try:
                self.assertGreater(obs.dropped, 0)
                result = verify_incident(path)
                self.assertEqual(result['status'], 'PASS', result['errors'])
                with ZipFile(path) as z:
                    gpt = json.loads(z.read('analysis/gpt_summary.json'))
                    diagnosis = json.loads(z.read('analysis/diagnosis.json'))
                self.assertEqual(gpt['finding_status'], 'DIVERGENCE_CANDIDATE')
                self.assertEqual(gpt['retained_evidence_confidence'], 'HIGH')
                self.assertEqual(gpt['confidence'], 'MEDIUM')
                self.assertEqual(diagnosis['retained_evidence_confidence'], 'HIGH')
                self.assertEqual(diagnosis['confidence'], 'MEDIUM')
                self.assertFalse(gpt['absence_is_conclusive'])
                self.assertEqual(gpt['first_divergence_scope'], 'INCLUDED_EVIDENCE_ONLY')
                self.assertEqual(gpt['cause_scope'], 'INCLUDED_EVIDENCE_ONLY')
                self.assertTrue(gpt['candidate_causes_may_be_incomplete'])
            finally:
                obs.finish('BLOCKED')

    def test_rehashed_bundle_cannot_claim_complete_cause_scope_after_loss(self):
        with tempfile.TemporaryDirectory() as td:
            obs, path = self._partial_ready_incident(Path(td))
            try:
                self._rewrite_json_artifacts(
                    path,
                    {
                        'analysis/gpt_summary.json': lambda payload: payload.update({
                            'cause_scope':'COMPLETE_RECORDER_EVIDENCE',
                            'candidate_causes_may_be_incomplete':False,
                        }),
                    },
                )
                result = verify_incident(path)
                self.assertEqual(result['status'], 'FAIL')
                self.assertIn('GPT_SUMMARY_CAUSE_SCOPE_MISMATCH', result['errors'])
                self.assertIn('GPT_SUMMARY_CAUSE_COMPLETENESS_MISMATCH', result['errors'])
            finally:
                obs.finish('BLOCKED')

    def test_rehashed_bundle_cannot_restore_high_confidence_after_loss(self):
        with tempfile.TemporaryDirectory() as td:
            obs, path = self._partial_ready_incident(Path(td))
            try:
                self._rewrite_json_artifacts(
                    path,
                    {
                        'analysis/gpt_summary.json': lambda payload: payload.__setitem__('confidence', 'HIGH'),
                        'analysis/diagnosis.json': lambda payload: payload.__setitem__('confidence', 'HIGH'),
                        'diagnosis.json': lambda payload: payload.__setitem__('confidence', 'HIGH'),
                    },
                )
                result = verify_incident(path)
                self.assertEqual(result['status'], 'FAIL')
                self.assertIn('GPT_SUMMARY_LOSS_CONFIDENCE_MISMATCH', result['errors'])
                self.assertIn('GPT_SUMMARY_LOSS_CONFIDENCE_NOT_DOWNGRADED', result['errors'])
            finally:
                obs.finish('BLOCKED')


class TestAgent07PreActionCausalIndex(unittest.TestCase):
    def test_decision_wait_is_indexed_without_action_id(self):
        with tempfile.TemporaryDirectory() as td:
            obs = LocalDiagnostics(Path(td), run_id='run-agent07-decision-wait', invocation_id='inv-agent07-decision-wait')
            try:
                obs.record(
                    'decision.plan_result',
                    owner_system='anka_decision',
                    boundary='decision.plan',
                    account_id='acct-cra',
                    fight_epoch=4,
                    turn_epoch=9,
                    payload={
                        'frame_id':'frame-agent07-wait',
                        'disposition':'WAIT',
                        'reason':'DECISION_BUDGET_EXHAUSTED',
                        'required_evidence':['planner_budget'],
                    },
                )
                report = action_lifecycle_report(obs.recent)
                self.assertEqual(report['actions'], [])
                self.assertEqual(report['total_pre_action_outcome_count'], 1)
                row = report['pre_action_outcomes'][0]
                self.assertEqual(row['state'], 'DECISION_WAIT')
                self.assertEqual(row['reason'], 'DECISION_BUDGET_EXHAUSTED')
                self.assertEqual(row['required_evidence'], ['planner_budget'])
                self.assertIsNone(row['action_id'])
            finally:
                obs.finish('BLOCKED')

    def test_authorization_blocker_is_correlated_before_action_id_and_surfaced_for_gpt(self):
        with tempfile.TemporaryDirectory() as td:
            obs = LocalDiagnostics(Path(td), run_id='run-agent07-auth-block', invocation_id='inv-agent07-auth-block')
            try:
                obs.record(
                    'decision.plan_result',
                    owner_system='anka_decision',
                    boundary='decision.plan',
                    account_id='acct-cra',
                    fight_epoch=5,
                    turn_epoch=11,
                    payload={
                        'frame_id':'frame-agent07-auth',
                        'disposition':'PLAN',
                        'reason':'PLAN_READY',
                        'plan_id':'plan-agent07-auth',
                        'kind':'CAST',
                    },
                )
                obs.record(
                    'workflow.action_authorization_blocked',
                    severity='WARNING',
                    owner_system='anka_workflow',
                    boundary='workflow.action_authorization',
                    failure_code='COORDINATION_TURN_OWNER_UNPROVEN',
                    account_id='acct-cra',
                    fight_epoch=5,
                    turn_epoch=11,
                    payload={
                        'scope':'TURN',
                        'kind':'CAST',
                        'plan_id':'plan-agent07-auth',
                        'reason':'COORDINATION_TURN_OWNER_UNPROVEN',
                    },
                )
                path = obs.export_incident('NOTHING_HAPPENED', boundary='workflow.action_authorization')
                result = verify_incident(path)
                self.assertEqual(result['status'], 'PASS', result['errors'])
                with ZipFile(path) as z:
                    lifecycles = json.loads(z.read('analysis/action_lifecycles.json'))
                    gpt = json.loads(z.read('analysis/gpt_summary.json'))
                self.assertEqual(lifecycles['actions'], [])
                self.assertEqual(lifecycles['pre_action_outcomes'][-1]['state'], 'AUTHORIZATION_BLOCKED')
                self.assertEqual(lifecycles['pre_action_outcomes'][-1]['plan_id'], 'plan-agent07-auth')
                self.assertIsNone(lifecycles['pre_action_outcomes'][-1]['action_id'])
                self.assertEqual(gpt['latest_included_pre_action_outcome'], lifecycles['pre_action_outcomes'][-1])
                self.assertEqual(gpt['pre_action_outcomes_omitted'], lifecycles['pre_action_outcomes_omitted'])

                TestAgent07EvidenceLossCertainty._rewrite_json_artifacts(
                    path,
                    {'analysis/gpt_summary.json': lambda payload: payload.__setitem__('latest_included_pre_action_outcome', None)},
                )
                tampered = verify_incident(path)
                self.assertEqual(tampered['status'], 'FAIL')
                self.assertIn('GPT_SUMMARY_PRE_ACTION_MISMATCH', tampered['errors'])
            finally:
                obs.finish('BLOCKED')


class TestAgent07ExecutionStageProjection(unittest.TestCase):
    def test_client_admission_rejection_is_explicit_not_sent_stage(self):
        with tempfile.TemporaryDirectory() as td:
            obs = LocalDiagnostics(Path(td), run_id='run-agent07-client-reject', invocation_id='inv-agent07-client-reject')
            try:
                action_id='action-agent07-client-reject'
                trace_id='trace-agent07-client-reject'
                obs.record(
                    'decision.plan_result',
                    owner_system='anka_decision',
                    boundary='decision.plan',
                    account_id='acct-cra',
                    fight_epoch=6,
                    turn_epoch=13,
                    payload={
                        'frame_id':'frame-agent07-client-reject',
                        'disposition':'PLAN',
                        'reason':'PLAN_READY',
                        'plan_id':'plan-agent07-client-reject',
                        'kind':'CAST',
                    },
                )
                obs.record(
                    'workflow.action_requested',
                    owner_system='anka_workflow',
                    boundary='workflow.action_authorization',
                    account_id='acct-cra',
                    fight_epoch=6,
                    turn_epoch=13,
                    trace_id=trace_id,
                    action_id=action_id,
                    payload={'scope':'TURN','kind':'CAST','plan_id':'plan-agent07-client-reject'},
                )
                obs.record(
                    'execution.rejected',
                    severity='WARNING',
                    owner_system='anka_execution',
                    boundary='execution.pre_input_authorization',
                    failure_code='CLIENT_ATTESTATION_UNAVAILABLE',
                    account_id='acct-cra',
                    fight_epoch=6,
                    turn_epoch=13,
                    trace_id=trace_id,
                    action_id=action_id,
                    payload={'scope':'TURN','kind':'CAST'},
                )
                obs.record(
                    'workflow.action_dispatch_result',
                    severity='INFO',
                    owner_system='anka_workflow',
                    boundary='workflow.execution_dispatch',
                    account_id='acct-cra',
                    fight_epoch=6,
                    turn_epoch=13,
                    trace_id=trace_id,
                    action_id=action_id,
                    payload={
                        'scope':'TURN',
                        'kind':'CAST',
                        'outcome_status':'REJECTED_NOT_SENT',
                        'outcome_reason':'CLIENT_ATTESTATION_UNAVAILABLE',
                    },
                )
                path = obs.export_incident('CLIENT_ACTION_REJECTED', boundary='execution.pre_input_authorization')
                result = verify_incident(path)
                self.assertEqual(result['status'], 'PASS', result['errors'])
                with ZipFile(path) as z:
                    lifecycles = json.loads(z.read('analysis/action_lifecycles.json'))
                    facts = json.loads(z.read('analysis/proven_facts.json'))
                    gpt = json.loads(z.read('analysis/gpt_summary.json'))
                row = next(item for item in lifecycles['actions'] if item['action_id']==action_id)
                self.assertEqual(row['state'], 'NOT_SENT')
                self.assertEqual(row['not_sent_stage'], 'ADMISSION')
                self.assertEqual(row['not_sent_event_name'], 'execution.rejected')
                self.assertEqual(row['not_sent_boundary'], 'execution.pre_input_authorization')
                self.assertEqual(row['not_sent_failure_code'], 'CLIENT_ATTESTATION_UNAVAILABLE')
                self.assertEqual(gpt['latest_included_action_lifecycle'], row)
                self.assertEqual(gpt['action_lifecycles_omitted'], lifecycles['actions_omitted'])
                self.assertEqual(facts['unresolved_actions'], [])

                TestAgent07EvidenceLossCertainty._rewrite_json_artifacts(
                    path,
                    {'analysis/gpt_summary.json': lambda payload: payload.__setitem__('latest_included_action_lifecycle', None)},
                )
                tampered = verify_incident(path)
                self.assertEqual(tampered['status'], 'FAIL')
                self.assertIn('GPT_SUMMARY_ACTION_LIFECYCLE_MISMATCH', tampered['errors'])
            finally:
                obs.finish('BLOCKED')


class TestAgent07ContradictoryExecutionEvidence(unittest.TestCase):
    def test_rejected_before_send_then_sent_is_explicit_contradiction(self):
        with tempfile.TemporaryDirectory() as td:
            obs = LocalDiagnostics(Path(td), run_id='run-agent07-reject-send-conflict', invocation_id='inv-agent07-reject-send-conflict')
            try:
                action_id='action-agent07-reject-send-conflict'
                attempt_id='attempt-agent07-reject-send-conflict'
                obs.record(
                    'workflow.action_requested',
                    owner_system='anka_workflow',
                    boundary='workflow.action_authorization',
                    account_id='acct-cra',
                    fight_epoch=7,
                    turn_epoch=14,
                    trace_id='trace-agent07-reject-send-conflict',
                    action_id=action_id,
                    payload={'scope':'TURN','kind':'CAST','plan_id':'plan-agent07-reject-send-conflict'},
                )
                obs.record(
                    'execution.rejected',
                    severity='WARNING',
                    owner_system='anka_execution',
                    boundary='execution.pre_input_authorization',
                    failure_code='CLIENT_ATTESTATION_UNAVAILABLE',
                    account_id='acct-cra',
                    fight_epoch=7,
                    turn_epoch=14,
                    trace_id='trace-agent07-reject-send-conflict',
                    action_id=action_id,
                    physical_input_state='NOT_SENT',
                )
                obs.record(
                    'execution.send_started',
                    severity='SAFETY',
                    owner_system='anka_execution',
                    boundary='execution.external_boundary',
                    account_id='acct-cra',
                    fight_epoch=7,
                    turn_epoch=14,
                    trace_id='trace-agent07-reject-send-conflict',
                    action_id=action_id,
                    attempt_id=attempt_id,
                    physical_input_state='SEND_STARTED',
                )
                obs.record(
                    'execution.input_sent',
                    owner_system='anka_execution',
                    boundary='execution.external_boundary',
                    account_id='acct-cra',
                    fight_epoch=7,
                    turn_epoch=14,
                    trace_id='trace-agent07-reject-send-conflict',
                    action_id=action_id,
                    attempt_id=attempt_id,
                    physical_input_state='SENT',
                )
                report = action_lifecycle_report(obs.recent)
                row = next(item for item in report['actions'] if item['action_id']==action_id)
                self.assertEqual(row['state'], 'CONTRADICTORY_EVIDENCE')
                self.assertIn('PRE_SEND_TERMINAL_WITH_SEND', row['hard_conflicts'])
                self.assertEqual(report['contradictory_action_count'], 1)
            finally:
                obs.finish('BLOCKED')


class TestAgent07IncidentPrivacyVerification(unittest.TestCase):
    @staticmethod
    def _rewrite_json_artifact(path: Path, name: str, mutate) -> None:
        with ZipFile(path) as z:
            files = {entry: z.read(entry) for entry in z.namelist()}
        payload = json.loads(files[name])
        mutate(payload)
        blob = (json.dumps(payload, sort_keys=True, ensure_ascii=True, indent=2) + '\n').encode('utf8')
        files[name] = blob
        manifest = json.loads(files['manifest.json'])
        manifest['files'][name] = {'sha256': sha256(blob).hexdigest(), 'bytes': len(blob)}
        files['manifest.json'] = (json.dumps(manifest, sort_keys=True, ensure_ascii=True, indent=2) + '\n').encode('utf8')
        with ZipFile(path, 'w', ZIP_DEFLATED) as z:
            for entry, data in files.items():
                z.writestr(entry, data)

    def test_rehashed_bundle_with_unredacted_sensitive_key_fails_verification(self):
        with tempfile.TemporaryDirectory() as td:
            obs = LocalDiagnostics(Path(td), run_id='run-agent07-privacy', invocation_id='inv-agent07-privacy')
            try:
                obs.record('workflow.heartbeat', owner_system='anka_workflow', boundary='workflow.watchdog')
                path = obs.export_incident('PRIVACY_REHASH_TEST', boundary='observability.bundle')
                self.assertEqual(verify_incident(path)['status'], 'PASS')
                self._rewrite_json_artifact(
                    path,
                    'analysis/gpt_summary.json',
                    lambda payload: payload.__setitem__('access_token', 'agent07-super-secret'),
                )
                result = verify_incident(path)
                self.assertEqual(result['status'], 'FAIL')
                self.assertTrue(
                    any(code.startswith('UNREDACTED_SENSITIVE_DATA:analysis/gpt_summary.json') for code in result['errors']),
                    result['errors'],
                )
            finally:
                obs.finish('BLOCKED')

    def test_manifest_with_unredacted_sensitive_field_fails_verification(self):
        with tempfile.TemporaryDirectory() as td:
            obs = LocalDiagnostics(Path(td), run_id='run-agent07-manifest-privacy', invocation_id='inv-agent07-manifest-privacy')
            try:
                obs.record('workflow.heartbeat', owner_system='anka_workflow', boundary='workflow.watchdog')
                path = obs.export_incident('MANIFEST_PRIVACY_TEST', boundary='observability.bundle')
                with ZipFile(path) as z:
                    files = {entry: z.read(entry) for entry in z.namelist()}
                manifest = json.loads(files['manifest.json'])
                manifest['access_token'] = 'agent07-manifest-secret'
                files['manifest.json'] = (json.dumps(manifest, sort_keys=True, ensure_ascii=True, indent=2) + '\n').encode('utf8')
                with ZipFile(path, 'w', ZIP_DEFLATED) as z:
                    for entry, data in files.items():
                        z.writestr(entry, data)
                result = verify_incident(path)
                self.assertEqual(result['status'], 'FAIL')
                self.assertIn('UNREDACTED_SENSITIVE_DATA:manifest.json', result['errors'])
            finally:
                obs.finish('BLOCKED')

    def test_sensitive_detector_allows_redacted_value_and_safe_token_count(self):
        self.assertFalse(has_unredacted_sensitive_data({'access_token': '[REDACTED]', 'token_count': 7}))
        self.assertTrue(has_unredacted_sensitive_data({'access_token': 'plain-secret'}))
        self.assertTrue(has_unredacted_sensitive_data('Bearer plain-secret'))


if __name__ == '__main__':
    unittest.main()
