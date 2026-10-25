import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from anka_observability.api import LocalDiagnostics
from anka_observability.bundle import verify_incident
from anka_observability.forensics import READY_TRACE
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
