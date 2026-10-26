"""Chat 02 Issue #31 Phase B: Protocol client-binding consumer enforcement."""
from __future__ import annotations

from hashlib import sha256
import unittest

from anka_contracts.canonical import CanonicalCandidate
from anka_contracts.evidence import EvidencePointer
from anka_contracts.protocol import (
    AdapterReleaseDescriptor,
    CandidateCanonicalBatch,
    DecoderCheckpointRef,
    ProtocolAdmissionDecision,
    WireEnvelopeRef,
)
from anka_contracts.wire import WireEnvelope
from anka_protocol.sdk.runtime import AdapterContextCheckpoint, ProtocolTransaction


ADAPTER = "adapter-agent02-issue31"
BUILD = "Dofus Issue31"
CONNECTION = "conn-agent02-issue31"


def descriptor() -> AdapterReleaseDescriptor:
    return AdapterReleaseDescriptor(
        ADAPTER, BUILD, "0" * 64, "1" * 64, 1, 0, "STAGED"
    )


def envelope(
    *,
    client: str = "client-cra",
    generation: int = 1,
    producer: int = 1,
    payload: bytes = b"wire",
    connection: str = CONNECTION,
    capture: str = "capture-agent02-issue31",
    direction: str = "server_to_client",
) -> WireEnvelope:
    return WireEnvelope(
        capture,
        client,
        connection,
        direction,
        0,
        producer,
        "2026-10-26T02:00:00+00:00",
        producer,
        payload,
        "COMPLETE",
        len(payload),
        generation,
        producer,
        "TEST_FIXTURE",
    )


def evidence(tag: str) -> EvidencePointer:
    digest = sha256(tag.encode()).hexdigest()
    return EvidencePointer(
        "evidence-" + digest[:32],
        "OBSERVED_EXTERNAL",
        "anka_protocol",
        "issue31-phase-b:" + digest,
        digest,
        "ISSUE31_PHASE_B",
    )


def candidate(
    tag: str,
    *,
    client: str = "client-cra",
    account: str = "acct-cra",
) -> CanonicalCandidate:
    digest = sha256(tag.encode()).hexdigest()
    return CanonicalCandidate(
        "candidate-" + digest[:32],
        "ACTOR_SEEN",
        account,
        client,
        (evidence(tag),),
        (("actor_id", "41"),),
    )


def legacy_ref(source: WireEnvelope) -> WireEnvelopeRef:
    return WireEnvelopeRef(
        source.capture_session_id,
        source.connection_id,
        source.connection_generation,
        source.producer_sequence,
        source.direction,
        source.continuity,
        sha256(source.payload).hexdigest(),
    )


class RecordingAdmission:
    def __init__(self):
        self.calls = []

    def admit_candidate_batch(self, batch):
        self.calls.append(batch)
        return ProtocolAdmissionDecision("COMMITTED", len(self.calls), None)


class FakeAdapter:
    def __init__(self, factory, *, generation: int = 1, connection: str = CONNECTION):
        self.descriptor = descriptor()
        self.connection_id = connection
        self.connection_generation = generation
        self.factory = factory
        self.revision = 0
        self.decode_calls = 0
        self.restore_calls = 0

    def _digest(self) -> str:
        return sha256(
            f"{self.connection_id}|{self.connection_generation}|{self.revision}".encode()
        ).hexdigest()

    def checkpoint_runtime_context(self) -> AdapterContextCheckpoint:
        return AdapterContextCheckpoint(
            self.descriptor.adapter_release_id,
            self.descriptor.observed_client_build,
            self.connection_id,
            self.connection_generation,
            self.revision,
            self.revision,
            self._digest(),
        )

    def restore_runtime_context(self, checkpoint: AdapterContextCheckpoint) -> None:
        self.restore_calls += 1
        self.revision = checkpoint.revision

    def decode_envelope(self, source: WireEnvelope) -> CandidateCanonicalBatch:
        self.decode_calls += 1
        self.revision += 1
        return self.factory(self, source)


def make_batch(
    adapter: FakeAdapter,
    refs,
    candidates=(),
    *,
    health: str | None = None,
    batch_id: str = "batch-agent02-issue31",
) -> CandidateCanonicalBatch:
    refs = tuple(refs)
    candidates = tuple(candidates)
    checkpoint = adapter.checkpoint_runtime_context()
    return CandidateCanonicalBatch(
        batch_id,
        adapter.descriptor.adapter_release_id,
        adapter.descriptor.observed_client_build,
        adapter.connection_id,
        adapter.connection_generation,
        refs,
        candidates,
        health or ("SEMANTIC_CANDIDATES" if candidates else "FRAMING_IN_PROGRESS"),
        DecoderCheckpointRef(
            checkpoint.adapter_release_id,
            checkpoint.observed_client_build,
            checkpoint.connection_id,
            checkpoint.connection_generation,
            checkpoint.revision,
            checkpoint.digest,
        ),
    )


def matching_factory(adapter: FakeAdapter, source: WireEnvelope) -> CandidateCanonicalBatch:
    return make_batch(
        adapter,
        (WireEnvelopeRef.from_envelope(source),),
        (candidate("matching-" + source.client_instance_id, client=source.client_instance_id),),
        batch_id="batch-matching-" + source.client_instance_id,
    )


class TestAgent02Issue31ProtocolClientBinding(unittest.TestCase):
    def transaction(self, factory=matching_factory, *, generation=1):
        admission = RecordingAdmission()
        adapter = FakeAdapter(factory, generation=generation)
        return ProtocolTransaction(adapter, admission), adapter, admission

    def assert_binding_rejected(self, result, admission, failure_code):
        self.assertEqual(result.status, "REJECTED_CLIENT_BINDING")
        self.assertEqual(result.failure_code, failure_code)
        self.assertEqual(admission.calls, [])

    def test_01_first_matching_semantic_batch_may_reach_canonical(self):
        txn, adapter, admission = self.transaction()
        result = txn.process(envelope(client="client-cra"))
        self.assertEqual(result.status, "COMMITTED")
        self.assertEqual(len(admission.calls), 1)
        self.assertEqual(txn.client_instance_id, "client-cra")
        self.assertFalse(txn.poisoned)
        self.assertEqual(adapter.restore_calls, 0)

    def test_02_first_batch_cra_source_enu_candidate_is_rejected(self):
        def factory(adapter, source):
            return make_batch(
                adapter,
                (WireEnvelopeRef.from_envelope(source),),
                (candidate("cra-source-enu-candidate", client="client-enu", account="acct-enu"),),
            )

        txn, adapter, admission = self.transaction(factory)
        result = txn.process(envelope(client="client-cra"))
        self.assert_binding_rejected(
            result, admission, "PROTOCOL_BATCH_CLIENT_CANDIDATE_MISMATCH"
        )
        self.assertEqual(adapter.restore_calls, 1)
        self.assertTrue(txn.poisoned)

    def test_03_first_batch_enu_source_cra_candidate_is_rejected(self):
        def factory(adapter, source):
            return make_batch(
                adapter,
                (WireEnvelopeRef.from_envelope(source),),
                (candidate("enu-source-cra-candidate", client="client-cra"),),
            )

        txn, adapter, admission = self.transaction(factory)
        result = txn.process(envelope(client="client-enu"))
        self.assert_binding_rejected(
            result, admission, "PROTOCOL_BATCH_CLIENT_CANDIDATE_MISMATCH"
        )
        self.assertEqual(adapter.restore_calls, 1)
        self.assertTrue(txn.poisoned)

    def test_04_mixed_bound_source_clients_are_rejected(self):
        def factory(adapter, source):
            enu = envelope(
                client="client-enu",
                producer=max(1, source.producer_sequence - 1),
                payload=b"buffered-enu",
            )
            return make_batch(
                adapter,
                (WireEnvelopeRef.from_envelope(enu), WireEnvelopeRef.from_envelope(source)),
            )

        txn, _adapter, admission = self.transaction(factory)
        result = txn.process(envelope(client="client-cra", producer=2))
        self.assert_binding_rejected(
            result, admission, "PROTOCOL_BATCH_CLIENT_SOURCE_CONFLICT"
        )

    def test_05_bound_plus_unbound_sources_are_rejected(self):
        def factory(adapter, source):
            return make_batch(
                adapter,
                (legacy_ref(source), WireEnvelopeRef.from_envelope(source)),
            )

        txn, _adapter, admission = self.transaction(factory)
        result = txn.process(envelope(client="client-cra"))
        self.assert_binding_rejected(
            result, admission, "PROTOCOL_BATCH_CLIENT_UNBOUND"
        )

    def test_06_entirely_legacy_unbound_source_is_rejected(self):
        def factory(adapter, source):
            return make_batch(adapter, (legacy_ref(source),))

        txn, _adapter, admission = self.transaction(factory)
        result = txn.process(envelope(client="client-cra"))
        self.assert_binding_rejected(
            result, admission, "PROTOCOL_BATCH_CLIENT_UNBOUND"
        )

    def test_07_proven_source_client_different_from_current_envelope_is_rejected(self):
        def factory(adapter, source):
            relabeled = envelope(
                client="client-enu",
                generation=source.connection_generation,
                producer=source.producer_sequence,
                payload=source.payload,
                connection=source.connection_id,
                capture=source.capture_session_id,
                direction=source.direction,
            )
            return make_batch(
                adapter,
                (WireEnvelopeRef.from_envelope(relabeled),),
                (candidate("proven-enu-source", client="client-enu", account="acct-enu"),),
            )

        txn, adapter, admission = self.transaction(factory)
        result = txn.process(envelope(client="client-cra"))
        self.assert_binding_rejected(
            result, admission, "PROTOCOL_BATCH_CLIENT_SOURCE_MISMATCH"
        )
        self.assertEqual(adapter.restore_calls, 1)

    def test_08_same_client_buffered_multi_envelope_batch_is_allowed(self):
        def factory(adapter, source):
            earlier = envelope(
                client=source.client_instance_id,
                producer=1,
                payload=b"part-a",
                capture=source.capture_session_id,
                direction=source.direction,
            )
            return make_batch(
                adapter,
                (
                    WireEnvelopeRef.from_envelope(earlier),
                    WireEnvelopeRef.from_envelope(source),
                ),
                (candidate("buffered-same-client", client=source.client_instance_id),),
            )

        txn, _adapter, admission = self.transaction(factory)
        result = txn.process(
            envelope(client="client-cra", producer=2, payload=b"part-b")
        )
        self.assertEqual(result.status, "COMMITTED")
        self.assertEqual(len(admission.calls), 1)

    def test_09_zero_candidate_framing_with_bound_client_is_allowed(self):
        def factory(adapter, source):
            return make_batch(
                adapter,
                (WireEnvelopeRef.from_envelope(source),),
                (),
                health="FRAMING_IN_PROGRESS",
                batch_id="batch-framing-proven",
            )

        txn, _adapter, admission = self.transaction(factory)
        result = txn.process(envelope(client="client-cra"))
        self.assertEqual(result.status, "COMMITTED")
        self.assertEqual(result.batch.decode_health, "FRAMING_IN_PROGRESS")
        self.assertEqual(result.batch.candidates, ())
        self.assertEqual(len(admission.calls), 1)

    def test_10_zero_candidate_unbound_or_conflicting_source_is_rejected(self):
        def unbound_factory(adapter, source):
            return make_batch(
                adapter,
                (legacy_ref(source),),
                (),
                health="FRAMING_IN_PROGRESS",
                batch_id="batch-zero-unbound",
            )

        def conflict_factory(adapter, source):
            other = envelope(
                client="client-enu",
                producer=1,
                payload=b"other",
                capture=source.capture_session_id,
                direction=source.direction,
            )
            return make_batch(
                adapter,
                (WireEnvelopeRef.from_envelope(other), WireEnvelopeRef.from_envelope(source)),
                (),
                health="FRAMING_IN_PROGRESS",
                batch_id="batch-zero-conflict",
            )

        for factory, code in (
            (unbound_factory, "PROTOCOL_BATCH_CLIENT_UNBOUND"),
            (conflict_factory, "PROTOCOL_BATCH_CLIENT_SOURCE_CONFLICT"),
        ):
            with self.subTest(code=code):
                txn, _adapter, admission = self.transaction(factory)
                result = txn.process(envelope(client="client-cra", producer=2))
                self.assert_binding_rejected(result, admission, code)

    def test_11_bad_client_binding_rolls_back_verified_decoder_state(self):
        def factory(adapter, source):
            return make_batch(
                adapter,
                (WireEnvelopeRef.from_envelope(source),),
                (candidate("rollback-client-mismatch", client="client-enu"),),
            )

        txn, adapter, admission = self.transaction(factory)
        before = adapter.checkpoint_runtime_context()
        result = txn.process(envelope(client="client-cra"))
        after = adapter.checkpoint_runtime_context()
        self.assert_binding_rejected(
            result, admission, "PROTOCOL_BATCH_CLIENT_CANDIDATE_MISMATCH"
        )
        self.assertTrue(result.rollback_performed)
        self.assertEqual(adapter.restore_calls, 1)
        self.assertEqual(before.revision, after.revision)
        self.assertEqual(before.digest, after.digest)

    def test_12_bad_client_binding_poisons_transaction_generation(self):
        def factory(adapter, source):
            return make_batch(adapter, (legacy_ref(source),))

        txn, _adapter, admission = self.transaction(factory)
        result = txn.process(envelope(client="client-cra"))
        self.assert_binding_rejected(
            result, admission, "PROTOCOL_BATCH_CLIENT_UNBOUND"
        )
        self.assertTrue(txn.poisoned)

    def test_13_later_same_generation_after_binding_failure_is_rejected_poisoned(self):
        def factory(adapter, source):
            return make_batch(adapter, (legacy_ref(source),))

        txn, adapter, admission = self.transaction(factory)
        first = txn.process(envelope(client="client-cra", producer=1))
        second = txn.process(envelope(client="client-cra", producer=2, payload=b"later"))
        self.assertEqual(first.status, "REJECTED_CLIENT_BINDING")
        self.assertEqual(second.status, "REJECTED_POISONED")
        self.assertEqual(second.failure_code, "PROTOCOL_TRANSACTION_POISONED")
        self.assertEqual(adapter.decode_calls, 1)
        self.assertEqual(admission.calls, [])

    def test_14_same_transaction_generation_client_drift_rejects_before_decode(self):
        txn, adapter, admission = self.transaction()
        first = txn.process(envelope(client="client-cra", producer=1))
        self.assertEqual(first.status, "COMMITTED")
        self.assertEqual(txn.client_instance_id, "client-cra")
        revision_before = adapter.revision
        decode_before = adapter.decode_calls

        drift = txn.process(envelope(client="client-enu", producer=2, payload=b"drift"))
        self.assertEqual(drift.status, "REJECTED_CLIENT_BINDING")
        self.assertEqual(drift.failure_code, "PROTOCOL_TRANSACTION_CLIENT_DRIFT")
        self.assertFalse(drift.rollback_performed)
        self.assertEqual(adapter.decode_calls, decode_before)
        self.assertEqual(adapter.revision, revision_before)
        self.assertEqual(len(admission.calls), 1)
        self.assertTrue(txn.poisoned)

    def test_15_fresh_generation_new_transaction_can_bind_new_client(self):
        old_txn, _old_adapter, old_admission = self.transaction()
        self.assertEqual(
            old_txn.process(envelope(client="client-cra", generation=1)).status,
            "COMMITTED",
        )
        self.assertEqual(
            old_txn.process(envelope(client="client-enu", generation=1, producer=2)).status,
            "REJECTED_CLIENT_BINDING",
        )
        self.assertTrue(old_txn.poisoned)
        self.assertEqual(len(old_admission.calls), 1)

        fresh_txn, _fresh_adapter, fresh_admission = self.transaction(generation=2)
        fresh = fresh_txn.process(
            envelope(client="client-enu", generation=2, producer=1)
        )
        self.assertEqual(fresh.status, "COMMITTED")
        self.assertEqual(fresh_txn.client_instance_id, "client-enu")
        self.assertEqual(len(fresh_admission.calls), 1)

    def test_16_current_bound_ref_equality_and_membership_remain_valid(self):
        seen = {}

        def factory(adapter, source):
            current = WireEnvelopeRef.from_envelope(source)
            duplicate = WireEnvelopeRef.from_envelope(source)
            seen["equal"] = current == duplicate
            seen["member"] = current in (duplicate,)
            return make_batch(
                adapter,
                (duplicate,),
                (candidate("current-membership", client=source.client_instance_id),),
            )

        txn, _adapter, admission = self.transaction(factory)
        result = txn.process(envelope(client="client-cra"))
        self.assertEqual(result.status, "COMMITTED")
        self.assertEqual(seen, {"equal": True, "member": True})
        self.assertEqual(len(admission.calls), 1)

    def test_17_current_ref_must_remain_final_causal_source(self):
        def factory(adapter, source):
            current = WireEnvelopeRef.from_envelope(source)
            later = envelope(
                client=source.client_instance_id,
                producer=source.producer_sequence + 1,
                payload=b"later-evidence",
                capture=source.capture_session_id,
                direction=source.direction,
            )
            return make_batch(
                adapter,
                (current, WireEnvelopeRef.from_envelope(later)),
                (candidate("causal-finality", client=source.client_instance_id),),
            )

        txn, adapter, admission = self.transaction(factory)
        result = txn.process(envelope(client="client-cra", producer=1))
        self.assertEqual(result.status, "DECODE_FAILED")
        self.assertEqual(result.failure_code, "PROTOCOL_BATCH_SOURCE_CAUSALITY_INVALID")
        self.assertEqual(admission.calls, [])
        self.assertEqual(adapter.restore_calls, 1)
        self.assertTrue(txn.poisoned)

    def test_18_canonical_is_never_called_for_any_non_proven_binding_state(self):
        def unbound(adapter, source):
            return make_batch(adapter, (legacy_ref(source),), batch_id="batch-unbound")

        def conflict(adapter, source):
            other = envelope(
                client="client-enu",
                producer=1,
                payload=b"other",
                capture=source.capture_session_id,
                direction=source.direction,
            )
            return make_batch(
                adapter,
                (WireEnvelopeRef.from_envelope(other), WireEnvelopeRef.from_envelope(source)),
                batch_id="batch-conflict",
            )

        def mismatch(adapter, source):
            return make_batch(
                adapter,
                (WireEnvelopeRef.from_envelope(source),),
                (candidate("all-states-mismatch", client="client-enu"),),
                batch_id="batch-mismatch",
            )

        for factory, expected in (
            (unbound, "PROTOCOL_BATCH_CLIENT_UNBOUND"),
            (conflict, "PROTOCOL_BATCH_CLIENT_SOURCE_CONFLICT"),
            (mismatch, "PROTOCOL_BATCH_CLIENT_CANDIDATE_MISMATCH"),
        ):
            with self.subTest(expected=expected):
                txn, _adapter, admission = self.transaction(factory)
                result = txn.process(envelope(client="client-cra", producer=2))
                self.assert_binding_rejected(result, admission, expected)

    def test_19_candidate_relabel_cannot_bypass_by_changing_batch_id(self):
        def factory(adapter, source):
            return make_batch(
                adapter,
                (WireEnvelopeRef.from_envelope(source),),
                (candidate("relabel-bypass", client="client-enu", account="acct-enu"),),
                batch_id="batch-entirely-different-id",
            )

        txn, _adapter, admission = self.transaction(factory)
        result = txn.process(envelope(client="client-cra"))
        self.assert_binding_rejected(
            result, admission, "PROTOCOL_BATCH_CLIENT_CANDIDATE_MISMATCH"
        )

    def test_20_account_identity_remains_separate_from_client_identity(self):
        def factory(adapter, source):
            return make_batch(
                adapter,
                (WireEnvelopeRef.from_envelope(source),),
                (
                    candidate(
                        "separate-account-axis",
                        client=source.client_instance_id,
                        account="acct-explicit-other",
                    ),
                ),
                batch_id="batch-account-independent",
            )

        txn, _adapter, admission = self.transaction(factory)
        result = txn.process(envelope(client="client-cra"))
        self.assertEqual(result.status, "COMMITTED")
        self.assertEqual(len(admission.calls), 1)
        self.assertEqual(
            admission.calls[0].candidates[0].account_id,
            "acct-explicit-other",
        )
        self.assertEqual(
            admission.calls[0].client_binding.source_client_instance_id,
            "client-cra",
        )
        self.assertFalse(hasattr(admission.calls[0].client_binding, "account_id"))


if __name__ == "__main__":
    unittest.main()
