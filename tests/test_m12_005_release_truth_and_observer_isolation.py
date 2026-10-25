from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from threading import Event, Thread, current_thread
import json
import unittest

from anka_app.architecture_guard import SYSTEM_IMPORTS, audit_source_boundaries
from anka_app.cli import ROOT
from anka_app.configuration import load_user_config
from anka_app.ingress_readiness import probe_start_ingress
from anka_app.verification_runner import verification_fingerprint
from anka_capture.windows_live import capture_bounded_sample
from anka_contracts.capture import CapturePoll, CapturedTcpSegment
from anka_contracts.action import ActionCommand
from anka_contracts.execution import ExecutionOutcomeEvidence
from anka_contracts.protocol import (AdapterReleaseDescriptor, CandidateCanonicalBatch,
    DecoderCheckpointRef, ProtocolAdmissionDecision, WireEnvelopeRef)
from anka_contracts.wire import WireEnvelope
from anka_protocol.adapters.historical import load_reference
from anka_protocol.adapters.dofus_3_7_10_10.adapter import Historical371010Adapter
from anka_protocol.adapters.dofus_3_7_10_10.manifest import descriptor as historical_descriptor
from anka_protocol.api import ProtocolInspector
from anka_protocol.sdk.runtime import AdapterContextCheckpoint, ProtocolTransaction
from anka_observability.api import LocalDiagnostics
from anka_execution.definitive_ledger import DefinitiveExecutionLedger


class _BrokenDiagnostics:
    def record(self, *_args, **_kwargs):
        raise OSError('diagnostic sink unavailable')


class _CompleteSource:
    def __init__(self):
        self.stop_calls = 0
        self.quiesce_calls = 0
    def start(self):
        return None
    def poll(self, **_kwargs):
        return CapturePoll('generation-test', (), 0, False, True, 'UNKNOWN')
    def quiesce(self):
        self.quiesce_calls += 1
    def stop(self):
        self.stop_calls += 1
    def safe_stats(self):
        return {'accepted_segments': 0, 'queued_segments': 0, 'queue_drop_total': 0,
                'invalid_frames': 0, 'rejected_frames': 0, 'unsupported_frames': 0,
                'driver_loss_visibility': 'UNKNOWN', 'account_binding_verified': False,
                'physical_input_sent': False, 'raw_evidence': None}


class TestM12005ObserverIsolation(unittest.TestCase):
    def test_protocol_quarantine_survives_broken_diagnostic_sink(self):
        inspector = ProtocolInspector(load_reference(ROOT), requested_build='Dofus 3.7.10.10',
                                      observer=_BrokenDiagnostics())
        inspector.consume(CapturedTcpSegment('flow', 'client_to_server', 100, b'', 1, 0x02))
        # RST forces quarantine and therefore a diagnostic record attempt.
        inspector.consume(CapturedTcpSegment('flow', 'client_to_server', 101, b'', 2, 0x04))
        receipt = inspector.finish()
        self.assertEqual(receipt.quarantined_streams, 1)
        self.assertGreaterEqual(receipt.invalid_frames, 1)

    def test_protocol_finish_survives_broken_diagnostic_sink(self):
        inspector = ProtocolInspector(load_reference(ROOT), requested_build='unverified-build',
                                      observer=_BrokenDiagnostics())
        receipt = inspector.finish()
        self.assertEqual(receipt.status, 'UNSUPPORTED_BUILD_OBSERVATION_ONLY')
        self.assertIs(receipt, inspector.finish())

    def test_capture_completion_survives_broken_diagnostic_sink(self):
        source = _CompleteSource()
        # One clock value starts the window, the second exits it immediately.
        with patch('anka_capture.windows_live.monotonic_ns', side_effect=[0, 1_000_000_001]):
            receipt = capture_bounded_sample(interface='test', server_ports=(40400,),
                                             duration_seconds=1, source=source,
                                             require_windows=False, observer=_BrokenDiagnostics())
        self.assertEqual(receipt['status'], 'UNCERTIFIED')
        self.assertEqual(source.quiesce_calls, 1)
        self.assertEqual(source.stop_calls, 1)

    def test_ingress_result_survives_broken_diagnostic_sink(self):
        config = load_user_config(ROOT/'config/user.json')
        report = probe_start_ingress(config, {'platform': 'NON_WINDOWS'}, platform='posix',
                                     observer=_BrokenDiagnostics())
        self.assertEqual(report['status'], 'SKIPPED')
        self.assertEqual(report['reason'], 'WINDOWS_ONLY')
        self.assertFalse(report['physical_input_permitted'])



    def test_diagnostics_finish_seals_event_and_snapshot_mutation(self):
        with TemporaryDirectory() as td:
            observer = LocalDiagnostics(Path(td))
            self.assertEqual(observer.record('before.finish'), 'RECORDED')
            self.assertEqual(observer.register_snapshot('before_finish', {'ok': True}), 'RECORDED')
            observer.finish('CLOSED')
            state_before = (observer.folder/'run_state.json').read_bytes()
            events_before = (observer.folder/'events.jsonl').read_bytes()
            self.assertEqual(observer.record('after.finish'), 'DROPPED')
            self.assertEqual(observer.register_snapshot('after_finish', {'bad': True}), 'DROPPED')
            observer.finish('FAILED')
            self.assertEqual((observer.folder/'run_state.json').read_bytes(), state_before)
            self.assertEqual((observer.folder/'events.jsonl').read_bytes(), events_before)
            self.assertNotIn('after_finish', observer.snapshots)

    def test_finished_diagnostics_can_still_export_read_only_incident(self):
        with TemporaryDirectory() as td:
            observer = LocalDiagnostics(Path(td))
            observer.record('before.finish', boundary='test.boundary')
            observer.finish('BLOCKED')
            path = observer.export_incident('TEST_AFTER_FINISH', boundary='test.boundary',
                                            detail='read-only export after finalization')
            self.assertTrue(path.is_file())



class _AdmissionProbe:
    def __init__(self, status='REJECTED'):
        self.status=status;self.calls=0
    def admit_candidate_batch(self, _batch):
        self.calls+=1
        if self.status=='COMMITTED':
            return ProtocolAdmissionDecision('COMMITTED', committed_cursor=0)
        return ProtocolAdmissionDecision(self.status, reason_code='TEST_REJECT')


class _ProtocolRuntimeProbe:
    def __init__(self, *, batch_release='adapter-probe', batch_build='build-probe',
                 checkpoint_digest_override=None, silent_bad_restore=False, source_ref_override=None):
        self.connection_id='conn-probe';self.connection_generation=1;self.revision=0
        self.descriptor=AdapterReleaseDescriptor('adapter-probe','build-probe','0'*64,'1'*64,1,0,'REPLAY_CERTIFIED')
        self.batch_release=batch_release;self.batch_build=batch_build
        self.checkpoint_digest_override=checkpoint_digest_override
        self.silent_bad_restore=silent_bad_restore;self.source_ref_override=source_ref_override
        self.decode_calls=0;self.restore_calls=0
    def _digest(self):
        return __import__('hashlib').sha256(f'probe:{self.revision}'.encode()).hexdigest()
    def checkpoint_runtime_context(self):
        return AdapterContextCheckpoint(self.descriptor.adapter_release_id,self.descriptor.observed_client_build,
            self.connection_id,self.connection_generation,self.revision,self.revision,self._digest())
    def restore_runtime_context(self, checkpoint):
        self.restore_calls+=1
        if not self.silent_bad_restore:self.revision=checkpoint.revision
    def decode_envelope(self, envelope):
        self.decode_calls+=1;self.revision+=1
        digest=self.checkpoint_digest_override or self._digest()
        cp=DecoderCheckpointRef(self.batch_release,self.batch_build,self.connection_id,
                                self.connection_generation,self.revision,digest)
        source_ref=self.source_ref_override or WireEnvelopeRef.from_envelope(envelope)
        return CandidateCanonicalBatch('batch-probe-'+str(self.decode_calls),self.batch_release,self.batch_build,
            self.connection_id,self.connection_generation,(source_ref,),(),
            'OPAQUE_CERTIFIED_ZERO_SEMANTIC',cp)


def _protocol_transaction_envelope():
    return WireEnvelope('capture-probe','client-probe','conn-probe','server_to_client',0,1,
                        '2026-10-23T00:00:00+00:00',1,b'x',continuity='COMPLETE',
                        connection_generation=1,source_packet_number=1,timestamp_provenance='TEST_FIXTURE')


class TestM12005ProtocolRuntimeProvenance(unittest.TestCase):
    def test_batch_release_must_match_actual_runtime_descriptor(self):
        adapter=_ProtocolRuntimeProbe(batch_release='adapter-other')
        admission=_AdmissionProbe()
        result=ProtocolTransaction(adapter,admission).process(_protocol_transaction_envelope())
        self.assertEqual((result.status,result.failure_code,result.rollback_performed),
                         ('DECODE_FAILED','PROTOCOL_DECODER_BATCH_SCOPE_MISMATCH',True))
        self.assertEqual(admission.calls,0);self.assertEqual(adapter.revision,0)

    def test_batch_build_must_match_actual_runtime_descriptor(self):
        adapter=_ProtocolRuntimeProbe(batch_build='build-other')
        admission=_AdmissionProbe()
        result=ProtocolTransaction(adapter,admission).process(_protocol_transaction_envelope())
        self.assertEqual(result.failure_code,'PROTOCOL_DECODER_BATCH_SCOPE_MISMATCH')
        self.assertEqual(admission.calls,0);self.assertEqual(adapter.revision,0)

    def test_candidate_checkpoint_must_match_actual_postdecode_state(self):
        adapter=_ProtocolRuntimeProbe(checkpoint_digest_override='f'*64)
        admission=_AdmissionProbe()
        result=ProtocolTransaction(adapter,admission).process(_protocol_transaction_envelope())
        self.assertEqual((result.status,result.failure_code,result.rollback_performed),
                         ('DECODE_FAILED','PROTOCOL_CANDIDATE_CHECKPOINT_MISMATCH',True))
        self.assertEqual(admission.calls,0);self.assertEqual(adapter.revision,0)

    def test_silent_failed_restore_poisons_connection_generation(self):
        adapter=_ProtocolRuntimeProbe(silent_bad_restore=True)
        admission=_AdmissionProbe('REJECTED')
        tx=ProtocolTransaction(adapter,admission)
        result=tx.process(_protocol_transaction_envelope())
        self.assertEqual(result.status,'ROLLBACK_FAILED');self.assertTrue(tx.poisoned)
        self.assertEqual(adapter.revision,1)
        self.assertEqual(tx.process(_protocol_transaction_envelope()).status,'REJECTED_POISONED')
        self.assertEqual(adapter.decode_calls,1)

    def test_missing_runtime_descriptor_is_poisoned_before_decode(self):
        adapter=_ProtocolRuntimeProbe();adapter.descriptor=None
        tx=ProtocolTransaction(adapter,_AdmissionProbe())
        result=tx.process(_protocol_transaction_envelope())
        self.assertEqual((result.status,result.failure_code),
                         ('RUNTIME_INVALID','PROTOCOL_ADAPTER_RUNTIME_DESCRIPTOR_INVALID'))
        self.assertTrue(tx.poisoned);self.assertEqual(adapter.decode_calls,0)


    def test_batch_must_prove_current_envelope_evidence(self):
        other=WireEnvelope('capture-probe','client-probe','conn-probe','server_to_client',0,99,
                           '2026-10-23T00:00:00+00:00',99,b'other',continuity='COMPLETE',
                           connection_generation=1,source_packet_number=99,timestamp_provenance='TEST_FIXTURE')
        adapter=_ProtocolRuntimeProbe(source_ref_override=WireEnvelopeRef.from_envelope(other))
        admission=_AdmissionProbe()
        tx=ProtocolTransaction(adapter,admission)
        result=tx.process(_protocol_transaction_envelope())
        self.assertEqual((result.status,result.failure_code,result.rollback_performed),
                         ('DECODE_FAILED','PROTOCOL_BATCH_CURRENT_ENVELOPE_EVIDENCE_MISSING',True))
        self.assertTrue(tx.poisoned);self.assertEqual(admission.calls,0)

    def test_wire_ref_rejects_invalid_continuity(self):
        with self.assertRaisesRegex(ValueError,'INVALID_WIRE_REF_CONTINUITY'):
            WireEnvelopeRef('capture-probe','conn-probe',1,1,'server_to_client','INVENTED','0'*64)

    def test_batch_source_causality_rejects_future_or_cross_session_ref(self):
        current=_protocol_transaction_envelope();current_ref=WireEnvelopeRef.from_envelope(current)
        for bad in (
            WireEnvelopeRef('capture-probe','conn-probe',1,99,'server_to_client','COMPLETE','1'*64),
            WireEnvelopeRef('capture-other','conn-probe',1,0,'server_to_client','COMPLETE','2'*64),
            WireEnvelopeRef('capture-probe','conn-probe',1,0,'client_to_server','COMPLETE','3'*64),
        ):
            with self.subTest(bad=bad):
                class Probe(_ProtocolRuntimeProbe):
                    def decode_envelope(self, envelope):
                        batch=super().decode_envelope(envelope)
                        refs=(current_ref,bad) if bad.producer_sequence>=current_ref.producer_sequence else (bad,current_ref)
                        return CandidateCanonicalBatch(batch.batch_id,batch.adapter_release_id,batch.observed_client_build,
                            batch.connection_id,batch.connection_generation,refs,batch.candidates,batch.decode_health,
                            batch.candidate_checkpoint,batch.unknown_fingerprints,batch.failure_codes)
                tx=ProtocolTransaction(Probe(),_AdmissionProbe())
                result=tx.process(current)
                self.assertEqual(result.failure_code,'PROTOCOL_BATCH_SOURCE_CAUSALITY_INVALID')
                self.assertTrue(tx.poisoned)

    def test_any_postdecode_rollback_fences_stream_generation(self):
        for status in ('REJECTED','UNCERTAIN'):
            with self.subTest(status=status):
                adapter=_ProtocolRuntimeProbe();tx=ProtocolTransaction(adapter,_AdmissionProbe(status))
                first=tx.process(_protocol_transaction_envelope())
                self.assertEqual(first.status,'ROLLED_BACK');self.assertTrue(first.rollback_performed)
                self.assertTrue(tx.poisoned)
                self.assertEqual(tx.process(_protocol_transaction_envelope()).status,'REJECTED_POISONED')

    @staticmethod
    def _varint(value):
        out=[]
        while value>=128:
            out.append((value & 127)|128);value >>= 7
        out.append(value);return bytes(out)

    @classmethod
    def _framed_any(cls,name,body):
        def field(number,value):
            return cls._varint((number<<3)|2)+cls._varint(len(value))+value
        any_msg=field(1,b'type.ankama.com/'+name.encode())+field(2,body)
        return cls._varint(len(any_msg))+any_msg

    def test_tcp_fragmented_frame_advances_only_decoder_context_until_complete(self):
        body=bytes.fromhex('0a1b221110010a0d080b10feffffffffffffffff01220610170a020805108906')
        framed=self._framed_any('jtk',body);cut=len(framed)//2
        adapter=Historical371010Adapter(descriptor=historical_descriptor(),account_id='acct-cra',
            client_instance_id='client-cra',connection_id='conn-cra-1',connection_generation=1)
        tx=ProtocolTransaction(adapter,_AdmissionProbe('COMMITTED'))
        def envelope(payload,seq,offset):
            return WireEnvelope('capture-fragment','client-cra','conn-cra-1','server_to_client',offset,seq,
                '2026-10-23T00:00:00+00:00',seq,payload,continuity='CONTIGUOUS',connection_generation=1,
                source_packet_number=seq,timestamp_provenance='TEST_FIXTURE')
        first=tx.process(envelope(framed[:cut],1,0))
        self.assertEqual(first.status,'COMMITTED');self.assertEqual(first.batch.decode_health,'FRAMING_IN_PROGRESS')
        self.assertEqual(first.batch.candidates,());self.assertFalse(tx.poisoned)
        second=tx.process(envelope(framed[cut:],2,cut))
        self.assertEqual(second.status,'COMMITTED');self.assertEqual(second.batch.decode_health,'SEMANTIC_CANDIDATES')
        self.assertEqual([x.producer_sequence for x in second.batch.source_envelopes],[1,2])
        self.assertEqual([x.semantic_kind for x in second.batch.candidates],
                         ['ACTOR_RESOURCE_ABSOLUTE','ACTOR_RESOURCE_ABSOLUTE'])

    def test_candidate_batch_contract_binds_checkpoint_build(self):
        envelope=_protocol_transaction_envelope()
        cp=DecoderCheckpointRef('adapter-probe','wrong-build','conn-probe',1,1,'0'*64)
        with self.assertRaisesRegex(ValueError,'PROTOCOL_BATCH_CHECKPOINT_SCOPE_MISMATCH'):
            CandidateCanonicalBatch('batch-contract','adapter-probe','build-probe','conn-probe',1,
                (WireEnvelopeRef.from_envelope(envelope),),(),'OPAQUE_CERTIFIED_ZERO_SEMANTIC',cp)

class TestM12005ExecutionRaceHardening(unittest.TestCase):
    @staticmethod
    def _command(n: int) -> ActionCommand:
        return ActionCommand(
            f'action-m12-005-{n}', 'run-m12-005', 'acct-cra', 'client-cra', 7, 11,
            f'{n:064x}'[-64:], 'CAST', 100,
            (('spell_id', '1234'), ('grade', '3'), ('target_cell', '250')),
            ('SPELL_CAST_CONFIRMED', 'RESOURCE_DELTA_OR_TURN_PROGRESS'),
            basis_snapshot_id='snap-plan', party_id='party-main',
            basis_party_generation=3, basis_permit_generation=5, actor_id=41)

    @staticmethod
    def _evidence(command: ActionCommand, suffix: str = '1') -> ExecutionOutcomeEvidence:
        return ExecutionOutcomeEvidence(
            f'outcome-m12-005-{suffix}', command.account_id, command.client_instance_id,
            command.fight_epoch, command.turn_epoch, 201, 'CONFIRMATION',
            command.expected_outcome_proofs, True, None, command.actor_id)

    def test_driver_return_and_authoritative_outcome_cannot_split_status(self):
        # This hook deterministically opens the old get()->transition() TOCTOU window.
        # The hardened implementation makes the decision in one DB transaction, so it
        # never observes SEND_STARTED through this external get() before mutating.
        with TemporaryDirectory() as td:
            command = self._command(1)
            ledger = DefinitiveExecutionLedger(Path(td)/'race.sqlite3')
            ledger.prepare(command, 2, 9)
            ledger.mark_send_started(command.action_id, 'attempt-race')
            entered = Event(); release = Event(); original_get = ledger.get

            def hooked_get(action_id):
                current = original_get(action_id)
                if (current_thread().name == 'driver-return' and
                        current.status == 'SEND_STARTED' and not entered.is_set()):
                    entered.set(); release.wait(2)
                return current

            ledger.get = hooked_get
            box = {}
            def driver_return():
                try:
                    box['result'] = ledger.mark_sent(command.action_id)
                except Exception as exc:  # regression signal from the old TOCTOU path
                    box['error'] = exc

            thread = Thread(target=driver_return, name='driver-return')
            thread.start()
            if entered.wait(0.5):
                settled = ledger.apply_outcome(
                    command.action_id, 'SETTLED_SUCCESS', self._evidence(command),
                    'EXPECTED_OUTCOME_PROOFS_SATISFIED', ())
                self.assertEqual(settled.status, 'SETTLED_SUCCESS')
                release.set()
            thread.join(2)
            self.assertFalse(thread.is_alive())
            if not entered.is_set():
                settled = ledger.apply_outcome(
                    command.action_id, 'SETTLED_SUCCESS', self._evidence(command),
                    'EXPECTED_OUTCOME_PROOFS_SATISFIED', ())
                self.assertEqual(settled.status, 'SETTLED_SUCCESS')
            self.assertNotIn('error', box)
            self.assertEqual(ledger.get(command.action_id).status, 'SETTLED_SUCCESS')
            ledger.audit()

    def test_late_not_sent_driver_result_never_erases_raced_ahead_outcome(self):
        with TemporaryDirectory() as td:
            command = self._command(2)
            ledger = DefinitiveExecutionLedger(Path(td)/'not-sent-race.sqlite3')
            ledger.prepare(command, 2, 9)
            ledger.mark_send_started(command.action_id, 'attempt-race')
            ledger.apply_outcome(command.action_id, 'SETTLED_SUCCESS',
                                 self._evidence(command, '2'),
                                 'EXPECTED_OUTCOME_PROOFS_SATISFIED', ())
            result = ledger.mark_not_sent(command.action_id, 'LATE_DRIVER_NOT_SENT')
            self.assertEqual(result.status, 'SETTLED_SUCCESS')
            self.assertEqual(ledger.get(command.action_id).status, 'SETTLED_SUCCESS')
            ledger.audit()

    def test_terminal_outcome_is_idempotent_under_late_uncertainty_and_terminalize(self):
        with TemporaryDirectory() as td:
            command = self._command(3)
            ledger = DefinitiveExecutionLedger(Path(td)/'terminal-race.sqlite3')
            ledger.prepare(command, 2, 9)
            ledger.mark_send_started(command.action_id, 'attempt-race')
            ledger.apply_outcome(command.action_id, 'PROVEN_FAILURE',
                                 self._evidence(command, '3'), 'SERVER_REJECTED', ())
            self.assertEqual(ledger.mark_uncertain(command.action_id, 'LATE_EXCEPTION').status,
                             'PROVEN_FAILURE')
            self.assertEqual(ledger.mark_terminal_unresolved(command.action_id, 'LATE_TIMEOUT').status,
                             'PROVEN_FAILURE')
            ledger.audit()

class TestM12005ArchitectureAndReleaseTruth(unittest.TestCase):
    def _layout(self, base: Path) -> Path:
        src = base/'src'
        for package in SYSTEM_IMPORTS:
            (src/package).mkdir(parents=True, exist_ok=True)
            (src/package/'__init__.py').write_text('', encoding='utf8')
        return src

    def test_window_control_primitives_are_execution_only(self):
        for primitive in ('SetForegroundWindow', 'SetActiveWindow', 'SetFocus',
                          'PostMessageW', 'SendMessageW'):
            with self.subTest(primitive=primitive), TemporaryDirectory() as td:
                src = self._layout(Path(td))
                (src/'anka_client'/'bad.py').write_text(
                    f'def mutate(user32):\n    user32.{primitive}(1)\n', encoding='utf8')
                audit = audit_source_boundaries(src)
                self.assertTrue(any(x.startswith('ARCH_INPUT_AUTHORITY_BYPASS:')
                                    for x in audit.violations), audit.violations)

    def test_input_control_modules_are_execution_only(self):
        for module in ('pyautogui', 'pydirectinput', 'pynput', 'keyboard', 'mouse'):
            with self.subTest(module=module), TemporaryDirectory() as td:
                src = self._layout(Path(td))
                (src/'anka_protocol'/'bad.py').write_text(f'import {module}\n', encoding='utf8')
                audit = audit_source_boundaries(src)
                self.assertTrue(any(x.startswith('ARCH_INPUT_MODULE_BYPASS:')
                                    for x in audit.violations), audit.violations)

    def test_current_release_identity_is_consistent(self):
        project = dict(line.split('=', 1) for line in (ROOT/'PROJECT_INFO.txt').read_text().splitlines()
                       if '=' in line)
        pyproject = (ROOT/'pyproject.toml').read_text(encoding='utf8')
        build = (ROOT/'tools/build_release.py').read_text(encoding='utf8')
        self.assertEqual(project['PROJECT_VERSION'], 'ANKA_NEXT_M12_006')
        self.assertIn('version = "0.12.6"', pyproject)
        self.assertIn("RELEASE_ID='ANKA_NEXT_M12_006'", build)

    def test_current_handoff_docs_do_not_claim_obsolete_release_truth(self):
        files = ('README.md', 'IMPLEMENTATION_STATUS.md', '00_READ_FIRST_NEXT_CHAT.md')
        text = '\n'.join((ROOT/name).read_text(encoding='utf8') for name in files)
        self.assertIn('ANKA_NEXT_M12_006', text)
        for stale in (
            'final architecture has 13 packages / 349 modules',
            'start intentionally exits 40 with `LIVE_RUNTIME_NOT_IMPLEMENTED`',
            'currently **refuses physical gameplay** (`LIVE_RUNTIME_NOT_IMPLEMENTED`',
            'Current release candidate:** `ANKA_NEXT_M12_004`',
        ):
            self.assertNotIn(stale, text)


    def test_current_gate_table_counts_match_sealed_receipts(self):
        status=(ROOT/'IMPLEMENTATION_STATUS.md').read_text(encoding='utf8')
        specs=(
            ('Q4 Capture/Protocol','Q4_capture_protocol_receipt.json'),
            ('Q5 Canonical/State','Q5_canonical_live_state_receipt.json'),
            ('Q6 Planning/Coordination/Workflow','Q6_planning_coordination_workflow_receipt.json'),
            ('Q7 Execution Safety','Q7_execution_safety_receipt.json'),
        )
        lines=status.splitlines()
        for label,name in specs:
            with self.subTest(gate=label):
                receipt=json.loads((ROOT/'verification'/name).read_text(encoding='utf8'))
                passed=receipt['test_counts']['passed']
                line=next((x for x in lines if f'| {label} |' in x),None)
                self.assertIsNotNone(line,label)
                self.assertIn(f'{passed} tests',line)

    def test_verification_checkpoint_fingerprint_binds_current_handoff_docs(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            # Minimal tree is enough: fingerprint intentionally records absent standard inputs.
            for name in ('README.md', 'IMPLEMENTATION_STATUS.md', '00_READ_FIRST_NEXT_CHAT.md'):
                (root/name).write_text('A\n', encoding='utf8')
            first = verification_fingerprint(root)
            (root/'README.md').write_text('B\n', encoding='utf8')
            second = verification_fingerprint(root)
        self.assertNotEqual(first, second)


if __name__ == '__main__':
    unittest.main()
