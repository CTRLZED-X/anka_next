import json
import tempfile
import unittest
from unittest.mock import patch
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from anka_contracts.diagnostics import DiagnosticEvent
from anka_observability.api import LocalDiagnostics
from anka_observability.bundle import verify_incident
from anka_observability.recovery import recover_unclean_run
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

    def test_decision_plan_result_survives_recent_ring_overwrite_for_forensics(self):
        with tempfile.TemporaryDirectory() as td:
            obs = LocalDiagnostics(
                Path(td),
                run_id='run-agent07-plan-retention',
                invocation_id='inv-agent07-plan-retention',
                max_recent=2,
                max_priority=8,
            )
            try:
                obs.record(
                    'decision.plan_result',
                    owner_system='anka_decision',
                    boundary='decision.plan',
                    account_id='acct-cra',
                    fight_epoch=8,
                    turn_epoch=21,
                    payload={
                        'frame_id':'frame-agent07-retained-wait',
                        'disposition':'WAIT',
                        'reason':'TARGETS_NOT_PROVEN',
                        'required_evidence':['targets'],
                    },
                )
                for i in range(12):
                    obs.record(
                        'workflow.heartbeat',
                        owner_system='anka_workflow',
                        boundary='workflow.watchdog',
                        payload={'i':i},
                    )
                self.assertGreater(obs.recent_overwrites, 0)
                self.assertNotIn(
                    'decision.plan_result',
                    {row.get('event_name') for row in obs.recent},
                )
                self.assertIn(
                    'decision.plan_result',
                    {row.get('event_name') for row in obs.priority},
                )

                path = obs.export_incident('PLAN_RETENTION_AUDIT', boundary='decision.plan')
                result = verify_incident(path)
                self.assertEqual(result['status'], 'PASS', result['errors'])
                with ZipFile(path) as z:
                    lifecycles = json.loads(z.read('analysis/action_lifecycles.json'))
                self.assertEqual(lifecycles['pre_action_outcomes'][-1]['state'], 'DECISION_WAIT')
                self.assertEqual(lifecycles['pre_action_outcomes'][-1]['reason'], 'TARGETS_NOT_PROVEN')
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


class TestAgent07ExternalEventSequenceIsolation(unittest.TestCase):
    def test_foreign_run_event_cannot_consume_future_sequence(self):
        with tempfile.TemporaryDirectory() as td:
            obs = LocalDiagnostics(Path(td), run_id='run-agent07-seq-foreign', invocation_id='inv-agent07-seq-foreign')
            try:
                obs.record('workflow.heartbeat', owner_system='anka_workflow', boundary='workflow.watchdog')
                previous_seq = obs._seq
                bad = DiagnosticEvent(
                    1,
                    'evt-agent07-foreign-seq',
                    'debug.external',
                    'INFO',
                    '2026-10-25T12:00:00Z',
                    obs._last_monotonic_ns + 1,
                    previous_seq + 100,
                    obs.invocation_id,
                    'run-agent07-foreign-other',
                    owner_system='anka_observability',
                )
                self.assertEqual(obs.emit(bad), 'DROPPED')
                self.assertEqual(obs._seq, previous_seq)

                good = DiagnosticEvent(
                    1,
                    'evt-agent07-foreign-followup',
                    'debug.external',
                    'INFO',
                    '2026-10-25T12:00:01Z',
                    obs._last_monotonic_ns + 1,
                    previous_seq + 1,
                    obs.invocation_id,
                    obs.run_id,
                    owner_system='anka_observability',
                )
                self.assertIn(obs.emit(good), ('RECORDED', 'DROPPED', 'UNAVAILABLE'))
                self.assertEqual(obs._seq, previous_seq + 1)
                self.assertIn('evt-agent07-foreign-followup', {row.get('event_id') for row in obs.recent})
            finally:
                obs.finish('BLOCKED')

    def test_monotonic_regression_cannot_consume_future_sequence(self):
        with tempfile.TemporaryDirectory() as td:
            obs = LocalDiagnostics(Path(td), run_id='run-agent07-seq-mono', invocation_id='inv-agent07-seq-mono')
            try:
                obs.record('workflow.heartbeat', owner_system='anka_workflow', boundary='workflow.watchdog')
                previous_seq = obs._seq
                bad = DiagnosticEvent(
                    1,
                    'evt-agent07-mono-seq',
                    'debug.external',
                    'INFO',
                    '2026-10-25T12:00:00Z',
                    max(0, obs._last_monotonic_ns - 1),
                    previous_seq + 100,
                    obs.invocation_id,
                    obs.run_id,
                    owner_system='anka_observability',
                )
                self.assertEqual(obs.emit(bad), 'DROPPED')
                self.assertEqual(obs._seq, previous_seq)
                self.assertIn('EVENT_MONOTONIC_REGRESSION', obs.errors)

                good = DiagnosticEvent(
                    1,
                    'evt-agent07-mono-followup',
                    'debug.external',
                    'INFO',
                    '2026-10-25T12:00:01Z',
                    obs._last_monotonic_ns + 1,
                    previous_seq + 1,
                    obs.invocation_id,
                    obs.run_id,
                    owner_system='anka_observability',
                )
                self.assertIn(obs.emit(good), ('RECORDED', 'DROPPED', 'UNAVAILABLE'))
                self.assertEqual(obs._seq, previous_seq + 1)
                self.assertIn('evt-agent07-mono-followup', {row.get('event_id') for row in obs.recent})
            finally:
                obs.finish('BLOCKED')




class TestAgent07DiagnosticIdentityIntegrity(unittest.TestCase):
    @staticmethod
    def _rewrite_timeline_aliases(path: Path, mutate) -> None:
        with ZipFile(path) as z:
            files = {name: z.read(name) for name in z.namelist()}
        rows = [json.loads(line) for line in files['timeline.jsonl'].decode('utf8').splitlines() if line]
        mutate(rows)
        blob = b''.join(
            (json.dumps(row, sort_keys=True, ensure_ascii=True, separators=(',', ':')) + '\n').encode('utf8')
            for row in rows
        )
        files['timeline.jsonl'] = blob
        files['logs/relevant_timeline.jsonl'] = blob
        manifest = json.loads(files['manifest.json'])
        for name in ('timeline.jsonl', 'logs/relevant_timeline.jsonl'):
            manifest['files'][name] = {'sha256': sha256(blob).hexdigest(), 'bytes': len(blob)}
        files['manifest.json'] = (json.dumps(manifest, sort_keys=True, ensure_ascii=True, indent=2) + '\n').encode('utf8')
        with ZipFile(path, 'w', ZIP_DEFLATED) as z:
            for name, data in files.items():
                z.writestr(name, data)

    def test_rehashed_bundle_rejects_event_id_outside_live_namespace(self):
        with tempfile.TemporaryDirectory() as td:
            obs = LocalDiagnostics(Path(td), run_id='run-agent07-id-bundle', invocation_id='inv-agent07-id-bundle')
            try:
                obs.record('workflow.heartbeat', owner_system='anka_workflow', boundary='workflow.watchdog')
                path = obs.export_incident('IDENTITY_NAMESPACE_TEST', boundary='workflow.watchdog')
                self.assertEqual(verify_incident(path)['status'], 'PASS')
                invalid_event_id = 'evt-' + ('a' * 113)
                self._rewrite_timeline_aliases(
                    path,
                    lambda rows: rows[0].__setitem__('event_id', invalid_event_id),
                )
                result = verify_incident(path)
                self.assertEqual(result['status'], 'FAIL')
                self.assertIn('TIMELINE_EVENT_ID_INVALID', result['errors'])
            finally:
                obs.finish('BLOCKED')

    def test_rehashed_bundle_rejects_invalid_parent_event_id(self):
        with tempfile.TemporaryDirectory() as td:
            obs = LocalDiagnostics(Path(td), run_id='run-agent07-parent-id', invocation_id='inv-agent07-parent-id')
            try:
                obs.record('workflow.heartbeat', owner_system='anka_workflow', boundary='workflow.watchdog')
                path = obs.export_incident('PARENT_ID_NAMESPACE_TEST', boundary='workflow.watchdog')
                self._rewrite_timeline_aliases(
                    path,
                    lambda rows: rows[0].__setitem__('parent_event_id', 'bad-parent-id'),
                )
                result = verify_incident(path)
                self.assertEqual(result['status'], 'FAIL')
                self.assertIn('TIMELINE_PARENT_EVENT_ID_INVALID', result['errors'])
            finally:
                obs.finish('BLOCKED')

    def test_crash_recovery_rejects_broken_symlink_marker_without_writing_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            obs = LocalDiagnostics(
                root,
                run_id='run-agent07-recovery-marker-link',
                invocation_id='inv-agent07-recovery-marker-link',
            )
            obs.record(
                'workflow.heartbeat',
                owner_system='anka_workflow',
                boundary='workflow.watchdog',
            )
            self.assertTrue(obs.flush_journals())

            marker = obs.folder / 'unclean_recovery.json'
            outside = root / 'outside-recovery-marker.json'
            try:
                marker.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest('symlink unavailable')

            self.assertTrue(marker.is_symlink())
            self.assertFalse(outside.exists())
            self.assertIsNone(recover_unclean_run(obs.folder))
            self.assertFalse(outside.exists())


    def test_crash_recovery_rejects_mixed_invocation_journal_when_state_identity_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            obs = LocalDiagnostics(root, run_id='run-agent07-recovery-mixed', invocation_id='inv-agent07-recovery-a')
            obs.record('workflow.heartbeat', owner_system='anka_workflow', boundary='workflow.watchdog')
            self.assertTrue(obs.flush_journals())

            state_path = obs.folder / 'run_state.json'
            state = json.loads(state_path.read_text(encoding='utf8'))
            state.pop('invocation_id', None)
            state_path.write_text(json.dumps(state, sort_keys=True) + '\n', encoding='utf8')

            event_path = obs.folder / 'events.jsonl'
            rows = [json.loads(line) for line in event_path.read_text(encoding='utf8').splitlines() if line]
            self.assertEqual(len(rows), 1)
            mixed = dict(rows[0])
            mixed['event_id'] = 'evt-agent07-mixed-invocation'
            mixed['invocation_id'] = 'inv-agent07-recovery-b'
            mixed['producer_seq'] = rows[0]['producer_seq'] + 1
            mixed['monotonic_ns'] = rows[0]['monotonic_ns'] + 1
            event_path.write_text(
                ''.join(json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n' for row in (rows[0], mixed)),
                encoding='utf8',
            )

            self.assertIsNone(recover_unclean_run(obs.folder))
            self.assertFalse((obs.folder / 'unclean_recovery.json').exists())


    def test_crash_recovery_reads_only_bounded_tail_of_oversized_sparse_journal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            obs = LocalDiagnostics(root, run_id='run-agent07-recovery-bound', invocation_id='inv-agent07-recovery-bound')
            obs.record('workflow.heartbeat', owner_system='anka_workflow', boundary='workflow.watchdog')
            self.assertTrue(obs.flush_journals())

            event_path = obs.folder / 'events.jsonl'
            original_rows = [line for line in event_path.read_bytes().splitlines() if line]
            self.assertEqual(len(original_rows), 1)
            with event_path.open('wb') as handle:
                handle.seek(4 * 1024 * 1024)
                handle.write(b'\n')
                handle.write(original_rows[0] + b'\n')

            path = recover_unclean_run(obs.folder)
            self.assertIsNotNone(path)
            result = verify_incident(path)
            self.assertEqual(result['status'], 'PASS', result['errors'])
            with ZipFile(path) as z:
                recovered_rows = [
                    json.loads(line)
                    for line in z.read('timeline.jsonl').decode('utf8').splitlines()
                    if line
                ]
                run_manifest = json.loads(z.read('run_manifest.json'))
            self.assertEqual(len(recovered_rows), 1)
            self.assertEqual(recovered_rows[0]['event_name'], 'workflow.heartbeat')
            self.assertIn('RECOVERY_JOURNAL_TRUNCATED_TO_BOUND', run_manifest['observer_errors'])
            self.assertEqual(run_manifest['evidence_completeness'], 'PARTIAL')


    def test_crash_recovery_skips_journal_event_live_recorder_would_reject(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            obs = LocalDiagnostics(root, run_id='run-agent07-recovery-id', invocation_id='inv-agent07-recovery-id')
            obs.record('workflow.heartbeat', owner_system='anka_workflow', boundary='workflow.watchdog')
            self.assertTrue(obs.flush_journals())
            event_path = obs.folder / 'events.jsonl'
            rows = [json.loads(line) for line in event_path.read_text(encoding='utf8').splitlines() if line]
            self.assertTrue(rows)
            rows[0]['event_id'] = 'evt-' + ('x' * 113)
            event_path.write_text(
                ''.join(json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n' for row in rows),
                encoding='utf8',
            )
            path = recover_unclean_run(obs.folder)
            self.assertIsNotNone(path)
            result = verify_incident(path)
            self.assertEqual(result['status'], 'PASS', result['errors'])
            with ZipFile(path) as z:
                recovered_rows = [
                    json.loads(line)
                    for line in z.read('timeline.jsonl').decode('utf8').splitlines()
                    if line
                ]
                run_manifest = json.loads(z.read('run_manifest.json'))
            self.assertNotIn('evt-' + ('x' * 113), {row.get('event_id') for row in recovered_rows})
            self.assertIn('RECOVERY_EVENT_CONTRACT_INVALID_SKIPPED', run_manifest['observer_errors'])




class TestAgent07EvidenceMatrixDerivation(unittest.TestCase):
    @staticmethod
    def _rewrite_json_files(path: Path, mutations: dict[str, object]) -> None:
        with ZipFile(path) as z:
            files = {name: z.read(name) for name in z.namelist()}
        manifest = json.loads(files['manifest.json'])
        for name, mutate in mutations.items():
            payload = json.loads(files[name])
            mutate(payload)
            blob = (
                json.dumps(payload, sort_keys=True, ensure_ascii=True, indent=2) + '\n'
            ).encode('utf8')
            files[name] = blob
            manifest['files'][name] = {
                'sha256': sha256(blob).hexdigest(),
                'bytes': len(blob),
            }
        files['manifest.json'] = (
            json.dumps(manifest, sort_keys=True, ensure_ascii=True, indent=2) + '\n'
        ).encode('utf8')
        with ZipFile(path, 'w', ZIP_DEFLATED) as z:
            for name, data in files.items():
                z.writestr(name, data)

    def test_rehashed_matrix_cannot_claim_protocol_evidence_absent_from_timeline(self):
        with tempfile.TemporaryDirectory() as td:
            obs = LocalDiagnostics(
                Path(td),
                run_id='run-agent07-matrix-derive',
                invocation_id='inv-agent07-matrix-derive',
            )
            try:
                obs.record(
                    'workflow.heartbeat',
                    owner_system='anka_workflow',
                    boundary='workflow.watchdog',
                )
                path = obs.export_incident(
                    'MATRIX_DERIVATION_TEST',
                    boundary='workflow.watchdog',
                )
                self.assertEqual(verify_incident(path)['status'], 'PASS')

                def promote_protocol(matrix):
                    matrix['sections']['protocol'] = 'PRESENT'

                def remove_protocol_gap(gaps):
                    gaps['gaps'] = [
                        row for row in gaps['gaps']
                        if row.get('section') != 'protocol'
                    ]

                def promote_protocol_summary(summary):
                    summary['status'] = 'PRESENT'

                self._rewrite_json_files(
                    path,
                    {
                        'evidence_matrix.json': promote_protocol,
                        'analysis/evidence_gaps.json': remove_protocol_gap,
                        'metadata/capture_protocol_summary.json': promote_protocol_summary,
                    },
                )
                result = verify_incident(path)
                self.assertEqual(result['status'], 'FAIL')
                self.assertIn('EVIDENCE_MATRIX_DERIVATION_MISMATCH', result['errors'])
            finally:
                obs.finish('BLOCKED')

    def test_gpt_coverage_gaps_must_match_verified_matrix(self):
        with tempfile.TemporaryDirectory() as td:
            obs = LocalDiagnostics(
                Path(td),
                run_id='run-agent07-gpt-gaps',
                invocation_id='inv-agent07-gpt-gaps',
            )
            try:
                obs.record(
                    'workflow.heartbeat',
                    owner_system='anka_workflow',
                    boundary='workflow.watchdog',
                )
                path = obs.export_incident(
                    'GPT_COVERAGE_GAPS_TEST',
                    boundary='workflow.watchdog',
                )
                self.assertEqual(verify_incident(path)['status'], 'PASS')
                TestAgent07EvidenceLossCertainty._rewrite_json_artifacts(
                    path,
                    {
                        'analysis/gpt_summary.json': lambda payload: payload.__setitem__(
                            'diagnostic_coverage_gaps', []
                        ),
                    },
                )
                result = verify_incident(path)
                self.assertEqual(result['status'], 'FAIL')
                self.assertIn('GPT_SUMMARY_COVERAGE_GAPS_MISMATCH', result['errors'])
            finally:
                obs.finish('BLOCKED')




class TestAgent07ReadFirstDerivationIntegrity(unittest.TestCase):
    @staticmethod
    def _rewrite_read_first(path: Path, mutate) -> None:
        with ZipFile(path) as z:
            files = {name: z.read(name) for name in z.namelist()}
        original = files['GPT_READ_FIRST.md'].decode('utf8')
        rewritten = mutate(original).encode('utf8')
        files['GPT_READ_FIRST.md'] = rewritten
        manifest = json.loads(files['manifest.json'])
        manifest['files']['GPT_READ_FIRST.md'] = {
            'sha256': sha256(rewritten).hexdigest(),
            'bytes': len(rewritten),
        }
        files['manifest.json'] = (
            json.dumps(manifest, sort_keys=True, ensure_ascii=True, indent=2) + '\n'
        ).encode('utf8')
        with ZipFile(path, 'w', ZIP_DEFLATED) as z:
            for name, data in files.items():
                z.writestr(name, data)

    def test_rehashed_read_first_cannot_add_false_causal_claim(self):
        with tempfile.TemporaryDirectory() as td:
            obs = LocalDiagnostics(
                Path(td),
                run_id='run-agent07-read-first',
                invocation_id='inv-agent07-read-first',
            )
            try:
                obs.record(
                    'workflow.heartbeat',
                    owner_system='anka_workflow',
                    boundary='workflow.watchdog',
                )
                path = obs.export_incident(
                    'READ_FIRST_DERIVATION_TEST',
                    boundary='workflow.watchdog',
                )
                self.assertEqual(verify_incident(path)['status'], 'PASS')
                self._rewrite_read_first(
                    path,
                    lambda text: text.replace(
                        '# ANKA diagnostic incident\n\n',
                        '# ANKA diagnostic incident\n\n'
                        '**ROOT CAUSE:** Protocol definitely failed.\n\n',
                        1,
                    ),
                )
                result = verify_incident(path)
                self.assertEqual(result['status'], 'FAIL')
                self.assertIn('GPT_READ_FIRST_DERIVATION_MISMATCH', result['errors'])
                # The machine-summary marker was deliberately preserved. Exact
                # rendering, not only marker presence, must detect the lie.
                self.assertNotIn('GPT_READ_FIRST_SUMMARY_HASH_MISMATCH', result['errors'])
            finally:
                obs.finish('BLOCKED')

    def test_rehashed_emergency_read_first_cannot_add_false_root_cause(self):
        with tempfile.TemporaryDirectory() as td:
            obs = LocalDiagnostics(
                Path(td),
                run_id='run-agent07-emergency-read-first',
                invocation_id='inv-agent07-emergency-read-first',
            )
            try:
                obs.record(
                    'ready.requested',
                    owner_system='anka_workflow',
                    boundary='workflow.ready_request',
                    account_id='acct-cra',
                )
                with patch(
                    'anka_observability.bundle._build_artifacts',
                    side_effect=RuntimeError('agent07-forced-analysis-failure'),
                ):
                    path = obs.export_incident(
                        'EMERGENCY_READ_FIRST_TEST',
                        boundary='protocol.ready_observation',
                        trace_spec=READY_TRACE,
                        control_state='BLOCKED',
                    )
                initial = verify_incident(path)
                self.assertEqual(initial['status'], 'PASS', initial['errors'])
                with ZipFile(path) as z:
                    manifest = json.loads(z.read('manifest.json'))
                    self.assertTrue(manifest['advanced_analysis_failed'])

                self._rewrite_read_first(
                    path,
                    lambda text: text.replace(
                        '# ANKA emergency diagnostic incident\n\n',
                        '# ANKA emergency diagnostic incident\n\n'
                        '**ROOT CAUSE:** Client definitely failed.\n\n',
                        1,
                    ),
                )
                result = verify_incident(path)
                self.assertEqual(result['status'], 'FAIL')
                self.assertIn('GPT_READ_FIRST_DERIVATION_MISMATCH', result['errors'])
                self.assertNotIn('GPT_READ_FIRST_SUMMARY_HASH_MISMATCH', result['errors'])
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
