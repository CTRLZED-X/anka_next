import json
from hashlib import sha256
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from anka_observability.api import LocalDiagnostics,NullDiagnostics
from anka_observability.bundle import verify_incident
from anka_observability.redaction import sanitize
from anka_contracts.diagnostics import DiagnosticEvent,now_utc

class TestDiagnostics(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.obs=LocalDiagnostics(self.root,max_recent=3)
        self.addCleanup(self.obs.finish,'CLOSED')
    def test_contract_accepts_version_and_requires_valid_events(self):
        event=DiagnosticEvent(1,'id','setup.stage_started','INFO',now_utc(),1,1,'inv',payload={})
        self.assertEqual(DiagnosticEvent.from_dict(event.to_dict()),event)
        with self.assertRaises(ValueError):DiagnosticEvent(2,'id','setup.stage_started','INFO',now_utc(),1,1,'inv',payload={})
        with self.assertRaises(ValueError):DiagnosticEvent(1,'id','bad event name','INFO',now_utc(),1,1,'inv',payload={})
    def test_diagnostic_causal_numeric_fields_require_exact_integers(self):
        base=dict(schema_version=1,event_id='id',event_name='setup.stage_started',severity='INFO',
                  occurred_utc=now_utc(),monotonic_ns=1,producer_seq=1,invocation_id='inv',payload={})
        for field,value in (('producer_seq',1.5),('producer_seq',True),('monotonic_ns',1.5),
                            ('fight_epoch',2.5),('turn_epoch',2.5),('canonical_revision',3.5),
                            ('canonical_cursor',4.5)):
            row=dict(base);row[field]=value
            with self.subTest(field=field,value=value):
                with self.assertRaises(ValueError):DiagnosticEvent(**row)

    def test_observer_non_authoritative_interface(self):
        self.assertEqual(self.obs.record('setup.stage_started'),'RECORDED')
        self.assertEqual(NullDiagnostics().emit(None),'UNAVAILABLE')
        self.assertTrue(self.obs.flush_journals())
        self.assertEqual(json.loads((self.obs.folder/'events.jsonl').read_text().splitlines()[0])['event_name'],'setup.stage_started')
    def test_bounded_memory_and_drop_count(self):
        for i in range(20):self.obs.record('debug.sample',payload={'seq':i})
        self.assertEqual(len(self.obs.recent),3)
        self.assertEqual(self.obs.recent[-1]['payload']['seq'],19)
    def test_single_emit_failure_counts_exactly_one_dropped_event(self):
        with patch.object(LocalDiagnostics,'_line',side_effect=RuntimeError('synthetic')):
            self.assertEqual(self.obs.record('setup.stage_started'),'UNAVAILABLE')
        self.assertEqual(self.obs.dropped,1)
        self.assertIn('OBSERVER_EMIT_FAILED:RuntimeError',self.obs.errors)

    def test_disk_limit_loss_is_explicit(self):
        obs=LocalDiagnostics(self.root, max_journal_bytes=1)
        self.assertEqual(obs.record('setup.stage_started'),'DROPPED')
        self.assertEqual(obs.dropped,1)
    def test_sanitization_nested(self):
        self.obs.record('setup.stage_failed',severity='ERROR',payload={'credentials':{'token':'supersecret'},'free_text':'Bearer abcdef0123456789'})
        self.assertTrue(self.obs.flush_journals())
        text=(self.obs.folder/'events.jsonl').read_text()
        self.assertNotIn('supersecret',text)
        self.assertNotIn('abcdef0123456789',text)
        self.assertIn('[REDACTED]',text)
    def test_bundle_verifies_and_claims_missing_evidence(self):
        self.obs.record('coordination.owner_not_proven',severity='ERROR',failure_code='TURN_OWNER_UNPROVEN',boundary='coordination.ready_to_first_turn')
        path=self.obs.export_incident('TURN_OWNER_UNPROVEN',boundary='coordination.ready_to_first_turn')
        self.assertEqual(verify_incident(path)['status'],'PASS')
        with ZipFile(path) as z:
            diag=json.loads(z.read('diagnosis.json'))
            matrix=json.loads(z.read('evidence_matrix.json'))
            self.assertEqual(diag['confidence'],'UNDETERMINED')
            self.assertEqual(matrix['sections']['execution'],'MISSING')
            self.assertFalse(json.loads(z.read('manifest.json'))['raw_protocol_included'])
    def test_corrupt_manifest_checksum_is_detected(self):
        path=self.obs.export_incident('FAULT_INJECTION',boundary='test.bundle')
        with ZipFile(path) as z:files={name:z.read(name) for name in z.namelist()}
        files['diagnosis.json']=b'CORRUPTED'+files['diagnosis.json']
        with ZipFile(path,'w',ZIP_DEFLATED) as z:
            for name,blob in files.items():z.writestr(name,blob)
        result=verify_incident(path)
        self.assertEqual(result['status'],'FAIL')
        self.assertTrue(any('BAD_CHECKSUM' in s for s in result['errors']))
    def test_zip_path_traversal_rejected(self):
        path=self.obs.export_incident('FAULT_INJECTION',boundary='test.bundle')
        with ZipFile(path, 'a') as z:z.writestr('../injected.txt','malicious')
        self.assertEqual(verify_incident(path)['status'],'FAIL')
    def test_failure_of_observer_cannot_crash_business(self):
        self.obs.available=False
        self.assertEqual(self.obs.record('setup.stage_failed',severity='ERROR'),'UNAVAILABLE')
        self.assertFalse((self.obs.folder/'events.jsonl').exists())
    def test_unclean_start_state_detectable(self):
        self.assertEqual(json.loads((self.obs.folder/'run_state.json').read_text())['state'],'RUNNING')
        self.obs.finish('BLOCKED')
        self.assertEqual(json.loads((self.obs.folder/'run_state.json').read_text())['state'],'BLOCKED')
    def test_sanitize_plain_text_path(self):
        value=sanitize('Found C:\\Users\\dell\\private.txt token=bigsecret')
        self.assertNotIn('dell',value)
        self.assertNotIn('bigsecret',value)

class TestSafeExceptionFrames(unittest.TestCase):
    def test_stack_frames_are_project_relative_and_contain_no_source_text_or_locals(self):
        from anka_observability.redaction import safe_exception_frames
        secret='super-secret-local-value'
        try:
            raise RuntimeError(secret)
        except RuntimeError as exc:
            frames=safe_exception_frames(exc,Path(__file__).resolve().parents[1])
        self.assertTrue(frames)
        last=frames[-1]
        self.assertTrue(last['file'].startswith('tests/'))
        self.assertIn('function',last);self.assertIn('line',last)
        raw=json.dumps(frames)
        self.assertNotIn(secret,raw)
        self.assertNotIn('Users\\',raw)
        self.assertNotIn('/home/',raw)

    def test_external_stack_path_is_reduced_to_basename(self):
        from anka_observability.redaction import safe_exception_frames
        try:
            json.loads('{')
        except Exception as exc:
            frames=safe_exception_frames(exc,Path('/definitely/not/the/python/stdlib'))
        self.assertTrue(frames)
        self.assertTrue(all('/home/' not in row['file'] and 'Users\\' not in row['file'] for row in frames))

class TestDiagnosticRedactionHardening(unittest.TestCase):
    def test_common_credential_key_variants_are_redacted(self):
        value=sanitize({'access_token':'aaa','refresh-token':'bbb','client_secret':'ccc',
                        'authorization_header':'ddd','token_count':7,'safe':'ok'})
        self.assertEqual(value['access_token'],'[REDACTED]')
        self.assertEqual(value['refresh-token'],'[REDACTED]')
        self.assertEqual(value['client_secret'],'[REDACTED]')
        self.assertEqual(value['authorization_header'],'[REDACTED]')
        self.assertEqual(value['token_count'],7)
        self.assertEqual(value['safe'],'ok')

    def test_sanitization_marks_bounded_payload_truncation(self):
        mapping={f'k{i}':i for i in range(55)}
        cleaned=sanitize({'mapping':mapping,'items':list(range(45)),'text':'x'*1100})
        self.assertEqual(cleaned['mapping']['__diagnostic_truncation__']['__mapping_items__'],5)
        self.assertEqual(cleaned['items'][-1],39)
        self.assertEqual(cleaned['__diagnostic_truncation__']['items'],5)
        self.assertTrue(cleaned['text'].endswith('[DIAGNOSTIC_TRUNCATED]'))
