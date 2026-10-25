import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from anka_observability.api import LocalDiagnostics
from anka_observability.bundle import verify_incident
from anka_observability.forensics import FirstDivergenceAnalyzer, READY_TRACE, evidence_matrix
from anka_contracts.diagnostics import BoundaryExpectation, OperationTraceSpec, DiagnosticEvent, now_utc


class TestQ8DiagnosticsForensics(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.obs=LocalDiagnostics(Path(self.tmp.name),run_id='run-q8',invocation_id='inv-q8',max_recent=100)
        self.addCleanup(self.obs.finish,'CLOSED')

    def emit(self,name,owner,boundary,*,severity='INFO',failure_code=None,physical=None,payload=None):
        return self.obs.record(name,severity=severity,owner_system=owner,boundary=boundary,
                               failure_code=failure_code,physical_input_state=physical,payload=payload or {})

    def test_ready_first_divergence_is_server_observation_not_ui_symptom(self):
        self.emit('ready.requested','anka_workflow','workflow.ready_request')
        self.emit('execution.admitted','anka_execution','execution.pre_input_authorization',physical='NOT_SENT')
        self.emit('execution.input_sent','anka_execution','execution.external_boundary',physical='SENT')
        self.emit('protocol.ready_missing','anka_protocol','protocol.ready_observation',severity='ERROR',
                  failure_code='READY_SERVER_EVIDENCE_MISSING',physical='SENT')
        result=FirstDivergenceAnalyzer().analyze(READY_TRACE,self.obs.recent,control_state='BLOCKED')
        self.assertEqual(result.finding.first_divergent_boundary,'protocol.ready_observation')
        self.assertEqual(result.finding.suspected_owner,'anka_protocol')
        self.assertEqual(result.finding.confidence,'HIGH')
        self.assertEqual(result.finding.missing_evidence,('protocol.ready_observed',))
        self.assertIn('READY_SERVER_EVIDENCE_MISSING',result.finding.candidate_causes)

    def test_full_expected_trace_has_no_false_finding(self):
        for exp in READY_TRACE.expectations:
            self.emit(exp.event_name,exp.owner_system,exp.boundary)
        result=FirstDivergenceAnalyzer().analyze(READY_TRACE,self.obs.recent)
        self.assertIsNone(result.finding)
        self.assertTrue(all(edge['status']=='OBSERVED' for edge in result.boundary_graph))

    def test_same_event_name_from_wrong_owner_or_boundary_cannot_mask_divergence(self):
        first=READY_TRACE.expectations[0]
        self.emit(first.event_name,first.owner_system,first.boundary)
        second=READY_TRACE.expectations[1]
        # Both are deliberately deceptive: the semantic name is right but the
        # authority/boundary provenance is wrong.  Neither may satisfy the trace.
        self.emit(second.event_name,'anka_client',second.boundary)
        self.emit(second.event_name,second.owner_system,'execution.wrong_boundary')
        result=FirstDivergenceAnalyzer().analyze(READY_TRACE,self.obs.recent)
        self.assertEqual(result.finding.first_divergent_boundary,second.boundary)
        self.assertEqual(result.finding.suspected_owner,second.owner_system)
        self.assertEqual(result.boundary_graph[1]['status'],'MISSING')

    def test_multiple_plausible_failures_preserved_without_fake_certainty(self):
        self.emit('ready.requested','anka_workflow','workflow.ready_request')
        self.emit('execution.guard_failed','anka_execution','execution.other',severity='ERROR',failure_code='FOCUS_CHANGED')
        self.emit('client.attestation_stale','anka_client','client.identity',severity='ERROR',failure_code='WINDOW_GENERATION_STALE')
        result=FirstDivergenceAnalyzer().analyze(READY_TRACE,self.obs.recent)
        self.assertEqual(result.finding.first_divergent_boundary,'execution.pre_input_authorization')
        self.assertEqual(result.finding.confidence,'MEDIUM')
        self.assertEqual(set(result.finding.candidate_causes),{'FOCUS_CHANGED','WINDOW_GENERATION_STALE'})
        path=self.obs.export_incident('READY_AMBIGUOUS',boundary='execution.pre_input_authorization',trace_spec=READY_TRACE,control_state='BLOCKED')
        self.assertEqual(verify_incident(path)['status'],'PASS')
        with ZipFile(path) as z:
            gpt=json.loads(z.read('analysis/gpt_summary.json'))
            diagnosis=json.loads(z.read('analysis/diagnosis.json'))
            read_first=z.read('GPT_READ_FIRST.md').decode('utf8')
        self.assertEqual(gpt['cause_status'],'MULTIPLE_PLAUSIBLE')
        self.assertEqual(set(gpt['candidate_causes']),{'FOCUS_CHANGED','WINDOW_GENERATION_STALE'})
        self.assertEqual(diagnosis['cause_status'],'MULTIPLE_PLAUSIBLE')
        self.assertIn('Cause status:** MULTIPLE_PLAUSIBLE',read_first)


    def test_canonical_commit_uncertainty_names_canonical_commit_as_first_break(self):
        spec=OperationTraceSpec('CANONICAL_COMMIT',(
            BoundaryExpectation('protocol.batch_decoded','protocol.decode','anka_protocol','protocol'),
            BoundaryExpectation('canonical.batch_admitted','canonical.admission','anka_canonical','canonical'),
            BoundaryExpectation('canonical.commit_acknowledged','canonical.commit','anka_canonical','canonical'),
            BoundaryExpectation('live_state.snapshot_published','live_state.publish','anka_live_state','live_state'),
        ))
        self.emit('protocol.batch_decoded','anka_protocol','protocol.decode')
        self.emit('canonical.batch_admitted','anka_canonical','canonical.admission')
        self.emit('canonical.commit_uncertain','anka_canonical','canonical.commit',severity='SAFETY',
                  failure_code='CANONICAL_COMMIT_UNCERTAIN')
        result=FirstDivergenceAnalyzer().analyze(spec,self.obs.recent,control_state='BLOCKED')
        self.assertEqual(result.finding.first_divergent_boundary,'canonical.commit')
        self.assertEqual(result.finding.failure_code,'CANONICAL_COMMIT_UNCERTAIN')
        self.assertEqual(result.finding.suspected_owner,'anka_canonical')

    def test_execution_may_have_sent_stops_at_server_outcome_boundary(self):
        spec=OperationTraceSpec('CAST',(
            BoundaryExpectation('execution.admitted','execution.pre_input_authorization','anka_execution','execution'),
            BoundaryExpectation('execution.input_sent','execution.external_boundary','anka_execution','execution'),
            BoundaryExpectation('execution.outcome_observed','execution.outcome','anka_execution','outcome'),
            BoundaryExpectation('execution.action_settled','execution.settlement','anka_execution','outcome'),
        ))
        self.emit('execution.admitted','anka_execution','execution.pre_input_authorization',physical='NOT_SENT')
        self.emit('execution.input_sent','anka_execution','execution.external_boundary',physical='MAY_HAVE_SENT')
        self.emit('execution.outcome_missing','anka_execution','execution.outcome',severity='SAFETY',
                  failure_code='AUTHORITATIVE_OUTCOME_MISSING',physical='MAY_HAVE_SENT')
        result=FirstDivergenceAnalyzer().analyze(spec,self.obs.recent,control_state='BLOCKED')
        self.assertEqual(result.finding.first_divergent_boundary,'execution.outcome')
        self.assertEqual(result.finding.failure_code,'AUTHORITATIVE_OUTCOME_MISSING')
        self.assertEqual(result.finding.confidence,'HIGH')

    def test_evidence_matrix_is_derived_from_actual_producers(self):
        self.emit('capture.flow_started','anka_capture','capture.flow')
        self.emit('protocol.adapter_selected','anka_protocol','protocol.adapter')
        matrix=evidence_matrix(self.obs.recent,dropped=3)
        self.assertEqual(matrix['capture'],'PRESENT')
        self.assertEqual(matrix['protocol'],'PRESENT')
        self.assertEqual(matrix['canonical'],'MISSING')
        self.assertEqual(matrix['observability'],'PARTIAL')

    def test_blocked_client_inspection_is_partial_identity_not_present(self):
        self.emit('client.inspection_completed','anka_client','client.read_only_inspection',
                  payload={'account_states':['IDENTITY_MATCHED','BLOCKED'],
                           'reasons':['INDEPENDENT_IDENTITY_MATCH','AMBIGUOUS_WINDOWS'],
                           'scan_errors':[]})
        matrix=evidence_matrix(self.obs.recent)
        self.assertEqual(matrix['identity'],'PARTIAL')

    def test_bundle_contains_definitive_analysis_and_physical_state(self):
        self.emit('ready.requested','anka_workflow','workflow.ready_request')
        self.emit('execution.admitted','anka_execution','execution.pre_input_authorization',physical='NOT_SENT')
        self.emit('execution.input_sent','anka_execution','execution.external_boundary',physical='MAY_HAVE_SENT')
        path=self.obs.export_incident('READY_SERVER_EVIDENCE_MISSING',boundary='protocol.ready_observation',
                                      detail='Both UI surfaces appeared Ready but authoritative server proof was absent.',
                                      trace_spec=READY_TRACE,control_state='BLOCKED')
        self.assertEqual(verify_incident(path)['status'],'PASS')
        with ZipFile(path) as z:
            names=set(z.namelist())
            for expected in ('analysis/diagnosis.json','analysis/boundary_graph.json','analysis/evidence_gaps.json',
                             'analysis/next_verification.json','logs/relevant_timeline.jsonl','run_manifest.json'):
                self.assertIn(expected,names)
            diagnosis=json.loads(z.read('analysis/diagnosis.json'))
            run=json.loads(z.read('run_manifest.json'))
            readme=z.read('GPT_READ_FIRST.md').decode()
            self.assertEqual(diagnosis['first_divergent_boundary'],'protocol.ready_observation')
            self.assertEqual(diagnosis['physical_input_state'],'MAY_HAVE_SENT')
            self.assertEqual(run['physical_input_state'],'MAY_HAVE_SENT')
            self.assertIn('protocol.ready_observed',readme)
            self.assertIn('MAY_HAVE_SENT',readme)

    def test_primary_export_failure_uses_marked_partial_fallback(self):
        from anka_observability import bundle
        real=bundle._write_zip
        calls={'n':0}
        def fail_primary_once(path,artifacts,manifest):
            calls['n']+=1
            if calls['n']==1:
                raise OSError('simulated disk failure')
            return real(path,artifacts,manifest)
        with patch('anka_observability.bundle._write_zip',side_effect=fail_primary_once):
            path=self.obs.export_incident('EXPORT_FAULT',boundary='observability.export',detail='original failure preserved')
        self.assertNotIn(str(self.obs.folder),str(path))
        self.assertEqual(verify_incident(path)['status'],'PASS')
        with ZipFile(path) as z:
            manifest=json.loads(z.read('manifest.json'))
            matrix=json.loads(z.read('evidence_matrix.json'))
            self.assertTrue(manifest['primary_export_failed'])
            self.assertEqual(matrix['sections']['observability'],'EXPORT_FAILED')
            self.assertIn('INCIDENT_PRIMARY_EXPORT_FAILED',z.read('GPT_READ_FIRST.md').decode())
        path.unlink(missing_ok=True)

    def test_nested_secrets_are_absent_from_share_bundle(self):
        self.emit('execution.admission_rejected','anka_execution','execution.pre_input_authorization',severity='ERROR',
                  failure_code='BAD_PROOF',payload={'credentials':{'token':'q8-super-secret'},
                  'path':'C:\\Users\\private-user\\secret.txt','email':'secret@example.com'})
        path=self.obs.export_incident('BAD_PROOF',boundary='execution.pre_input_authorization')
        with ZipFile(path) as z:
            blob=b'\n'.join(z.read(n) for n in z.namelist()).decode('utf8','ignore')
        self.assertNotIn('q8-super-secret',blob)
        self.assertNotIn('private-user',blob)
        self.assertNotIn('secret@example.com',blob)

    def test_observer_storage_loss_never_grants_or_revokes_authority(self):
        tiny=LocalDiagnostics(Path(self.tmp.name)/'tiny',max_journal_bytes=1)
        result=tiny.record('execution.admitted',owner_system='anka_execution',boundary='execution.pre_input_authorization')
        self.assertEqual(result,'DROPPED')
        self.assertEqual(tiny.dropped,1)
        # The observer returns a recording status only; it has no permit/action API.
        self.assertFalse(hasattr(tiny,'grant_permit'))
        self.assertFalse(hasattr(tiny,'send_input'))


if __name__=='__main__': unittest.main()

class TestQ8ConfigurationEvidenceRecognition(unittest.TestCase):
    def test_real_configuration_validated_event_marks_configuration_present(self):
        from anka_observability.forensics import evidence_matrix
        event=DiagnosticEvent(1,'evt-config-real','configuration.validated','INFO',now_utc(),1,1,
                              'inv-config-real','run-config-real',boundary='configuration.validation',
                              payload={'config_sha256':'a'*64})
        matrix=evidence_matrix([event])
        self.assertEqual(matrix['configuration'],'PRESENT')
