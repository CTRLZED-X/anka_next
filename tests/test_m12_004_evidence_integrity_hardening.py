from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from threading import Event, Thread
from zipfile import ZIP_DEFLATED, ZipFile
import json
import tempfile
import unittest

from anka_app.cli import ROOT
from anka_app.startup_acceptance import blockers_for, boundary_for
from anka_capture.windows_live import capture_bounded_sample
from anka_capture.live import LiveCaptureAudit
from anka_contracts.capture import CapturePoll
from anka_contracts.protocol import (ProtocolAdmissionDecision, AdapterReleaseDescriptor,
    CandidateCanonicalBatch, DecoderCheckpointRef, WireEnvelopeRef)
from anka_contracts.wire import WireEnvelope
from anka_protocol.api import ProtocolInspector
from anka_protocol.sdk.runtime import AdapterContextCheckpoint, ProtocolTransaction
from anka_protocol.adapters.historical import load_reference
from anka_observability.api import LocalDiagnostics
from anka_observability.bundle import verify_incident


def _healthy_host() -> dict:
    return {
        'platform': 'WINDOWS',
        'candidate_windows': 2,
        'issues': [],
        'capture': {
            'scapy_installed': True,
            'npcap_driver': 'DETECTED_UNVERIFIED',
            'server_port_candidates': 2,
            'interface_resolution': 'RESOLVED',
        },
        'bridge': {'process_generation_matches': 2},
        'client_build': {'status': 'CONSISTENT', 'version': 'test-build'},
    }


def _captured_receipt(*, status='UNCERTIFIED', dropped=0, visibility='UNKNOWN') -> dict:
    return {
        'status': 'CAPTURED_UNCERTIFIED',
        'receipt': {
            'status': status,
            'queue_dropped': dropped,
            'driver_loss_visibility': visibility,
            'capture_scope_stability_observed': True,
            'capture_scope_stable': True,
            'process_generation_stability_observed': True,
            'process_generation_stable': True,
            'protocol_wire': {
                'status': 'OBSERVED_UNCERTIFIED',
                'selected_segments': 8,
                'quarantined_streams': 0,
                'unanchored_streams': 0,
                'framed_messages': 4,
            },
        },
    }


class _PrimaryAndCleanupFailureSource:
    def __init__(self, *, mark_fails=False):
        self.mark_fails = mark_fails
        self.stop_calls = 0
        self.mark_calls = 0
    def start(self):
        return None
    def poll(self, **_kwargs):
        raise ValueError('PRIMARY_POLL_FAILURE')
    def mark_capture_interrupted(self):
        self.mark_calls += 1
        if self.mark_fails:
            raise RuntimeError('SECONDARY_MARK_FAILURE')
    def stop(self):
        self.stop_calls += 1
        raise OSError('SECONDARY_STOP_FAILURE')




class _NeverExhaustsAfterQuiesce:
    def __init__(self):
        self.quiesced = False
        self.stop_calls = 0
        self.mark_calls = 0
    def start(self):
        return None
    def quiesce(self):
        self.quiesced = True
    def poll(self, **_kwargs):
        return CapturePoll('generation-test', (), 0, False, False, 'UNKNOWN')
    def mark_capture_interrupted(self):
        self.mark_calls += 1
    def stop(self):
        self.stop_calls += 1



class _RollbackFailureAdapter:
    connection_id='conn-test'
    connection_generation=1
    def __init__(self, *, checkpoint_fails=False):
        self.checkpoint_fails=checkpoint_fails;self.decode_calls=0;self.restore_calls=0
        self.descriptor=AdapterReleaseDescriptor('adapter-test','build-test','0'*64,'1'*64,1,0,'REPLAY_CERTIFIED')
    def checkpoint_runtime_context(self):
        if self.checkpoint_fails: raise RuntimeError('checkpoint failed')
        return AdapterContextCheckpoint('adapter-test','build-test',self.connection_id,self.connection_generation,0,object(),'0'*64)
    def restore_runtime_context(self,_checkpoint):
        self.restore_calls+=1
        raise RuntimeError('rollback failed')
    def decode_envelope(self,_envelope):
        self.decode_calls+=1
        raise RuntimeError('decode failed after mutation')




class _RollbackFailureAfterDecodeAdapter(_RollbackFailureAdapter):
    def decode_envelope(self,envelope):
        self.decode_calls+=1
        ref=WireEnvelopeRef.from_envelope(envelope)
        cp=DecoderCheckpointRef('adapter-test','build-test',self.connection_id,self.connection_generation,0,'0'*64)
        return CandidateCanonicalBatch('batch-test-admission','adapter-test','build-test',self.connection_id,
                                       self.connection_generation,(ref,),(),'OPAQUE_CERTIFIED_ZERO_SEMANTIC',cp)

class _RaisingAdmission:
    def admit_candidate_batch(self,_batch):
        raise RuntimeError('admission failed')


class _InvalidCheckpointAdapter(_RollbackFailureAdapter):
    def checkpoint_runtime_context(self):
        return object()


def _transaction_envelope() -> WireEnvelope:
    return WireEnvelope('capture-test','client-test','conn-test','server_to_client',0,1,
                        '2026-10-23T00:00:00+00:00',1,b'x',continuity='COMPLETE',
                        connection_generation=1,source_packet_number=1,timestamp_provenance='TEST_FIXTURE')


class TestM12004EvidenceIntegrityHardening(unittest.TestCase):
    def test_protocol_rollback_failure_poisons_connection_generation(self):
        adapter=_RollbackFailureAdapter()
        tx=ProtocolTransaction(adapter,object())
        first=tx.process(_transaction_envelope())
        self.assertEqual(first.status,'ROLLBACK_FAILED')
        self.assertEqual(first.failure_code,'PROTOCOL_RUNTIME_CONTEXT_ROLLBACK_FAILED_AFTER_DECODER_EXCEPTION')
        self.assertFalse(first.rollback_performed)
        self.assertTrue(tx.poisoned)
        second=tx.process(_transaction_envelope())
        self.assertEqual(second.status,'REJECTED_POISONED')
        self.assertEqual(adapter.decode_calls,1)

    def test_protocol_rollback_failure_preserves_admission_failure_context(self):
        adapter=_RollbackFailureAfterDecodeAdapter()
        tx=ProtocolTransaction(adapter,_RaisingAdmission())
        result=tx.process(_transaction_envelope())
        self.assertEqual(result.status,'ROLLBACK_FAILED')
        self.assertEqual(result.failure_code,'PROTOCOL_RUNTIME_CONTEXT_ROLLBACK_FAILED_AFTER_CANONICAL_ADMISSION_EXCEPTION')
        self.assertTrue(tx.poisoned)
        self.assertEqual(adapter.restore_calls,1)

    def test_protocol_invalid_checkpoint_contract_poisons_before_decoding(self):
        adapter=_InvalidCheckpointAdapter()
        tx=ProtocolTransaction(adapter,object())
        result=tx.process(_transaction_envelope())
        self.assertEqual(result.status,'CHECKPOINT_FAILED')
        self.assertEqual(result.failure_code,'PROTOCOL_RUNTIME_CONTEXT_CHECKPOINT_INVALID')
        self.assertTrue(tx.poisoned)
        self.assertEqual(adapter.decode_calls,0)

    def test_protocol_checkpoint_failure_poisons_without_decoding(self):
        adapter=_RollbackFailureAdapter(checkpoint_fails=True)
        tx=ProtocolTransaction(adapter,object())
        result=tx.process(_transaction_envelope())
        self.assertEqual(result.status,'CHECKPOINT_FAILED')
        self.assertEqual(result.failure_code,'PROTOCOL_RUNTIME_CONTEXT_CHECKPOINT_FAILED')
        self.assertTrue(tx.poisoned)
        self.assertEqual(adapter.decode_calls,0)

    def test_release_identity_sources_agree(self):
        project = dict(line.split('=',1) for line in (ROOT/'PROJECT_INFO.txt').read_text().splitlines() if '=' in line)
        build = (ROOT/'tools/build_release.py').read_text()
        self.assertIn("RELEASE_ID='"+project['PROJECT_VERSION']+"'", build)

    def test_known_capture_queue_loss_is_not_hidden_by_semantic_blocker(self):
        codes = blockers_for(_healthy_host(), _captured_receipt(status='LOSS_DETECTED', dropped=7))
        self.assertEqual(codes[0], 'START_CAPTURE_QUEUE_LOSS_DETECTED')
        self.assertIn('CURRENT_CLIENT_SEMANTIC_ADAPTER_UNCERTIFIED', codes)
        self.assertEqual(boundary_for(codes[0]), 'capture.observe_only')

    def test_transport_uncertainty_is_reported_before_semantic_blocker(self):
        codes = blockers_for(_healthy_host(), _captured_receipt(status='TRANSPORT_UNCERTAIN'))
        self.assertEqual(codes[0], 'START_CAPTURE_TRANSPORT_UNCERTAIN')
        self.assertIn('CURRENT_CLIENT_SEMANTIC_ADAPTER_UNCERTIFIED', codes)

    def test_driver_loss_visibility_gap_is_explicit_when_wire_observation_succeeds(self):
        codes = blockers_for(_healthy_host(), _captured_receipt(visibility='UNKNOWN'))
        self.assertEqual(codes[0], 'START_CAPTURE_DRIVER_LOSS_VISIBILITY_UNAVAILABLE')
        self.assertIn('CURRENT_CLIENT_SEMANTIC_ADAPTER_UNCERTIFIED', codes)

    def test_legacy_receipt_without_driver_visibility_does_not_invent_loss(self):
        ingress = _captured_receipt(visibility='AVAILABLE_CLEAN')
        ingress['receipt'].pop('driver_loss_visibility')
        codes = blockers_for(_healthy_host(), ingress)
        self.assertEqual(codes[0], 'CURRENT_CLIENT_SEMANTIC_ADAPTER_UNCERTIFIED')

    def test_release_bound_stale_setup_records_are_preserved_as_supplemental_gaps(self):
        codes = blockers_for(
            _healthy_host(),
            _captured_receipt(visibility='AVAILABLE_CLEAN'),
            capture_setup={'status': 'STALE_SETUP_RECORD'},
            bridge_setup={'status': 'RECORD_INVALID'},
        )
        self.assertIn('START_CAPTURE_SETUP_EVIDENCE_STALE', codes)
        self.assertIn('START_BRIDGE_SETUP_EVIDENCE_STALE', codes)
        self.assertEqual(boundary_for('START_CAPTURE_SETUP_EVIDENCE_STALE'), 'capture.observe_only')
        self.assertEqual(boundary_for('START_BRIDGE_SETUP_EVIDENCE_STALE'), 'client.host_observation')

    def test_primary_capture_failure_survives_cleanup_failure(self):
        source = _PrimaryAndCleanupFailureSource()
        with self.assertRaisesRegex(ValueError, 'PRIMARY_POLL_FAILURE') as cm:
            capture_bounded_sample(interface='test', server_ports=(40400,), duration_seconds=1,
                                   source=source, require_windows=False)
        self.assertEqual(source.mark_calls, 1)
        self.assertEqual(source.stop_calls, 1)
        self.assertTrue(any('CAPTURE_CLEANUP_FAILED:OSError' in note for note in (cm.exception.__notes__ or ())))

    def test_primary_capture_failure_survives_mark_and_cleanup_failures(self):
        source = _PrimaryAndCleanupFailureSource(mark_fails=True)
        with self.assertRaisesRegex(ValueError, 'PRIMARY_POLL_FAILURE') as cm:
            capture_bounded_sample(interface='test', server_ports=(40400,), duration_seconds=1,
                                   source=source, require_windows=False)
        notes = cm.exception.__notes__ or ()
        self.assertTrue(any('CAPTURE_INTERRUPT_MARK_FAILED:RuntimeError' in note for note in notes))
        self.assertTrue(any('CAPTURE_CLEANUP_FAILED:OSError' in note for note in notes))

    def test_capture_audit_can_represent_genuinely_clean_driver_visibility(self):
        audit = LiveCaptureAudit()
        audit.observe(CapturePoll('generation-test', (), 0, False, True, 'AVAILABLE_CLEAN'))
        self.assertEqual(audit.receipt()['driver_drop_visibility'], 'AVAILABLE_CLEAN')

    def test_capture_audit_unknown_or_drop_dominates_clean_visibility(self):
        audit = LiveCaptureAudit()
        audit.observe(CapturePoll('generation-test', (), 0, False, False, 'AVAILABLE_CLEAN'))
        audit.observe(CapturePoll('generation-test', (), 0, False, False, 'UNKNOWN'))
        audit.observe(CapturePoll('generation-test', (), 0, False, True, 'AVAILABLE_CLEAN'))
        self.assertEqual(audit.receipt()['driver_drop_visibility'], 'UNKNOWN')
        audit2 = LiveCaptureAudit()
        audit2.observe(CapturePoll('generation-test', (), 0, False, False, 'UNKNOWN'))
        audit2.observe(CapturePoll('generation-test', (), 1, True, True, 'AVAILABLE_DROPPED'))
        self.assertEqual(audit2.receipt()['driver_drop_visibility'], 'AVAILABLE_DROPPED')

    def test_post_quiesce_drain_has_progress_bound(self):
        from unittest.mock import patch
        source = _NeverExhaustsAfterQuiesce()
        with patch('anka_capture.windows_live.monotonic_ns', side_effect=[0, 1_000_000_001]):
            with self.assertRaisesRegex(RuntimeError, 'CAPTURE_FINAL_DRAIN_DID_NOT_EXHAUST'):
                capture_bounded_sample(interface='test', server_ports=(40400,), duration_seconds=1,
                                       source=source, require_windows=False)
        self.assertTrue(source.quiesced)
        self.assertEqual(source.mark_calls, 1)
        self.assertEqual(source.stop_calls, 1)

    def test_protocol_finish_is_serialized_with_mutation_owner_lock(self):
        inspector = ProtocolInspector(load_reference(Path(__file__).resolve().parents[1]),
                                      requested_build='Dofus 3.7.10.10')
        started = Event(); done = Event()
        inspector._lock.acquire()
        try:
            def worker():
                started.set(); inspector.finish(); done.set()
            t = Thread(target=worker, daemon=True)
            t.start(); self.assertTrue(started.wait(1))
            self.assertFalse(done.wait(.05), 'Protocol finish bypassed mutation-owner lock')
        finally:
            inspector._lock.release()
        t.join(2); self.assertTrue(done.is_set())

    def _write_zip(self, folder: Path, entries: dict[str, bytes]) -> Path:
        path = folder / 'incident.zip'
        with ZipFile(path, 'w', ZIP_DEFLATED) as z:
            for name, data in entries.items():
                z.writestr(name, data)
        return path

    def test_incident_verifier_rejects_non_object_manifest_without_crashing(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._write_zip(Path(td), {'manifest.json': b'[]'})
            result = verify_incident(path)
        self.assertEqual(result['status'], 'FAIL')
        self.assertIn('MANIFEST_SHAPE_INVALID', result['errors'])

    def test_incident_verifier_rejects_malformed_file_receipt_without_crashing(self):
        with tempfile.TemporaryDirectory() as td:
            data = b'{}\n'
            manifest = {
                'schema_version': 2,
                'raw_protocol_included': False,
                'files': {'diagnosis.json': 'not-a-receipt'},
            }
            path = self._write_zip(Path(td), {
                'diagnosis.json': data,
                'manifest.json': json.dumps(manifest).encode(),
            })
            result = verify_incident(path)
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(any(x.startswith('MANIFEST_FILE_RECEIPT_INVALID') for x in result['errors']))

    def test_incident_verifier_rejects_bad_zip_without_crashing(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'not-a-zip.zip'
            path.write_bytes(b'not a zip')
            result = verify_incident(path)
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(any(x.startswith('BUNDLE_OPEN_FAILED:') for x in result['errors']))

    def test_incident_export_is_serialized_with_observer_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            observer = LocalDiagnostics(Path(td))
            started = Event(); done = Event(); outcome = []
            observer._lock.acquire()
            try:
                def worker():
                    started.set()
                    outcome.append(observer.export_incident('SERIALIZATION_TEST', boundary='observability.concurrent_export'))
                    done.set()
                t = Thread(target=worker, daemon=True)
                t.start(); self.assertTrue(started.wait(1))
                self.assertFalse(done.wait(.05), 'incident export bypassed observer lock')
            finally:
                observer._lock.release()
            t.join(2)
            self.assertTrue(done.is_set())
            self.assertEqual(verify_incident(outcome[0])['status'], 'PASS')


if __name__ == '__main__':
    unittest.main()
