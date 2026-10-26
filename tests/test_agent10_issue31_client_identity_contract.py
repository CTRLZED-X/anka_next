"""Chat 10 Issue #31 Phase A: immutable Protocol source-client binding."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from hashlib import sha256
import unittest

from anka_contracts.canonical import CanonicalCandidate
from anka_contracts.evidence import EvidencePointer
from anka_contracts.protocol import (
    CandidateCanonicalBatch,
    DecoderCheckpointRef,
    WireEnvelopeRef,
    derive_protocol_client_binding,
)
from anka_contracts.wire import WireEnvelope

ADAPTER='adapter-issue31-r1'
BUILD='Dofus Issue31'
CONNECTION='conn-issue31'


def envelope(*,client='client-cra',seq=1,payload=b'wire',capture='capture-issue31'):
    return WireEnvelope(
        capture,client,CONNECTION,'server_to_client',0,seq,
        '2026-10-26T00:00:00+00:00',seq,payload,
        continuity='COMPLETE',transport_end_offset=len(payload),
        connection_generation=1,source_packet_number=seq,
        timestamp_provenance='TEST_FIXTURE',
    )


def evidence(tag):
    digest=sha256(tag.encode()).hexdigest()
    return EvidencePointer(
        'evidence-'+digest[:32],'OBSERVED_EXTERNAL','anka_protocol',
        'issue31:'+digest,digest,'ISSUE31_PHASE_A',
    )


def candidate(tag,*,client='client-cra',account='acct-cra'):
    digest=sha256(tag.encode()).hexdigest()
    return CanonicalCandidate(
        'candidate-'+digest[:32],'ACTOR_SEEN',account,client,
        (evidence(tag),),(('actor_id','41'),),
    )


def checkpoint():
    return DecoderCheckpointRef(ADAPTER,BUILD,CONNECTION,1,1,'1'*64)


def batch(refs, candidates=(), *, batch_id='batch-issue31'):
    candidates=tuple(candidates)
    return CandidateCanonicalBatch(
        batch_id,ADAPTER,BUILD,CONNECTION,1,tuple(refs),candidates,
        'SEMANTIC_CANDIDATES' if candidates else 'FRAMING_IN_PROGRESS',
        checkpoint(),
    )


class TestIssue31SourceClientExpansion(unittest.TestCase):
    def test_source_evidence_from_wire_preserves_exact_client_identity(self):
        source=envelope(client='client-cra')
        ref=WireEnvelopeRef.from_envelope(source)
        self.assertEqual(ref.client_instance_id,source.client_instance_id)
        self.assertTrue(ref.client_identity_proven)
        with self.assertRaises(FrozenInstanceError):
            ref.client_instance_id='client-enu'

    def test_cra_source_cannot_be_represented_as_enu_candidate_without_mismatch(self):
        b=batch(
            (WireEnvelopeRef.from_envelope(envelope(client='client-cra')),),
            (candidate('wrong-client',client='client-enu',account='acct-enu'),),
        )
        binding=b.client_binding
        self.assertEqual(binding.status,'CANDIDATE_MISMATCH')
        self.assertEqual(binding.source_client_instance_id,'client-cra')
        self.assertEqual(binding.candidate_client_instance_ids,('client-enu',))
        self.assertFalse(binding.authoritative)

    def test_multiple_source_clients_are_conflicting_and_non_authoritative(self):
        refs=(
            WireEnvelopeRef.from_envelope(envelope(client='client-cra',seq=1,payload=b'a')),
            WireEnvelopeRef.from_envelope(envelope(client='client-enu',seq=2,payload=b'b')),
        )
        binding=batch(refs).client_binding
        self.assertEqual(binding.status,'SOURCE_CONFLICT')
        self.assertEqual(binding.source_client_instance_ids,('client-cra','client-enu'))
        self.assertIsNone(binding.source_client_instance_id)
        self.assertFalse(binding.authoritative)

    def test_first_batch_wrong_client_is_detectable_without_historical_state(self):
        first=batch(
            (WireEnvelopeRef.from_envelope(envelope(client='client-cra',seq=1)),),
            (candidate('first-batch-enu',client='client-enu'),),
            batch_id='batch-first',
        )
        result=derive_protocol_client_binding(first)
        self.assertEqual(result.status,'CANDIDATE_MISMATCH')
        self.assertFalse(result.authoritative)

    def test_zero_candidate_framing_batch_retains_proven_source_client(self):
        framing=batch(
            (WireEnvelopeRef.from_envelope(envelope(client='client-cra')),),
            (),
            batch_id='batch-framing',
        )
        self.assertEqual(framing.decode_health,'FRAMING_IN_PROGRESS')
        self.assertEqual(framing.client_binding.status,'PROVEN')
        self.assertEqual(framing.client_binding.source_client_instance_id,'client-cra')
        self.assertTrue(framing.client_binding.authoritative)

    def test_identical_wire_bytes_under_different_clients_have_distinct_source_identity(self):
        cra_ref=WireEnvelopeRef.from_envelope(envelope(client='client-cra',payload=b'same'))
        enu_ref=WireEnvelopeRef.from_envelope(envelope(client='client-enu',payload=b'same'))
        self.assertEqual(cra_ref.payload_sha256,enu_ref.payload_sha256)
        self.assertNotEqual(cra_ref.source_identity_sha256,enu_ref.source_identity_sha256)
        self.assertNotEqual(
            batch((cra_ref,),batch_id='batch-cra').source_identity_sha256,
            batch((enu_ref,),batch_id='batch-enu').source_identity_sha256,
        )

    def test_candidate_relabel_cannot_rewrite_immutable_source_identity(self):
        ref=WireEnvelopeRef.from_envelope(envelope(client='client-cra',payload=b'same-source'))
        good=batch((ref,),(candidate('good',client='client-cra'),),batch_id='batch-good')
        relabeled=batch((ref,),(candidate('bad',client='client-enu'),),batch_id='batch-bad')
        self.assertEqual(good.source_identity_sha256,relabeled.source_identity_sha256)
        self.assertEqual(good.client_binding.status,'PROVEN')
        self.assertEqual(relabeled.client_binding.status,'CANDIDATE_MISMATCH')
        self.assertFalse(relabeled.client_binding.authoritative)

    def test_legacy_unbound_source_is_explicit_and_non_authoritative(self):
        legacy=WireEnvelopeRef(
            'capture-legacy',CONNECTION,1,1,'server_to_client','COMPLETE','a'*64
        )
        self.assertIsNone(legacy.client_instance_id)
        self.assertFalse(legacy.client_identity_proven)
        binding=batch((legacy,),batch_id='batch-legacy').client_binding
        self.assertEqual(binding.status,'LEGACY_UNBOUND')
        self.assertIsNone(binding.source_client_instance_id)
        self.assertFalse(binding.authoritative)

    def test_mixed_bound_and_unbound_sources_do_not_mean_same_client(self):
        bound=WireEnvelopeRef.from_envelope(envelope(client='client-cra',seq=1))
        unbound=WireEnvelopeRef(
            'capture-issue31',CONNECTION,1,2,'server_to_client','COMPLETE','b'*64
        )
        binding=batch((bound,unbound),batch_id='batch-partial-legacy').client_binding
        self.assertEqual(binding.status,'LEGACY_UNBOUND')
        self.assertEqual(binding.source_client_instance_ids,('client-cra',))
        self.assertFalse(binding.authoritative)

    def test_source_conflict_outranks_unbound_when_bound_sources_disagree(self):
        refs=(
            WireEnvelopeRef.from_envelope(envelope(client='client-cra',seq=1,payload=b'a')),
            WireEnvelopeRef.from_envelope(envelope(client='client-enu',seq=2,payload=b'b')),
            WireEnvelopeRef('capture-issue31',CONNECTION,1,3,'server_to_client','COMPLETE','c'*64),
        )
        binding=batch(refs,batch_id='batch-conflict-plus-unbound').client_binding
        self.assertEqual(binding.status,'SOURCE_CONFLICT')
        self.assertFalse(binding.authoritative)

    def test_account_identity_is_not_inferred_from_client_identity(self):
        ref=WireEnvelopeRef.from_envelope(envelope(client='client-cra'))
        c=candidate('separate-account-axis',client='client-cra',account='acct-explicit-other')
        b=batch((ref,),(c,),batch_id='batch-account-axis')
        self.assertEqual(b.client_binding.status,'PROVEN')
        self.assertEqual(c.account_id,'acct-explicit-other')
        self.assertFalse(hasattr(b.client_binding,'account_id'))

    def test_same_client_multi_envelope_buffered_source_is_proven(self):
        refs=(
            WireEnvelopeRef.from_envelope(envelope(client='client-cra',seq=1,payload=b'part-a')),
            WireEnvelopeRef.from_envelope(envelope(client='client-cra',seq=2,payload=b'part-b')),
        )
        b=batch(refs,(candidate('buffered-cra'),),batch_id='batch-buffered')
        self.assertEqual(b.client_binding.status,'PROVEN')
        self.assertEqual(b.client_binding.source_client_instance_ids,('client-cra',))
        self.assertTrue(b.client_binding.authoritative)

    def test_legacy_positional_contract_construction_remains_available_but_unbound(self):
        legacy=WireEnvelopeRef(
            'capture-old',CONNECTION,1,7,'server_to_client','CONTIGUOUS','d'*64
        )
        b=CandidateCanonicalBatch(
            'batch-old-positional',ADAPTER,BUILD,CONNECTION,1,(legacy,),(),
            'FRAMING_IN_PROGRESS',checkpoint(),
        )
        self.assertEqual(b.client_binding.status,'LEGACY_UNBOUND')
        self.assertFalse(b.client_binding.authoritative)

    def test_direct_constructor_cannot_assert_bound_source_client(self):
        with self.assertRaises(TypeError):
            WireEnvelopeRef(
                'capture-x',CONNECTION,1,1,'server_to_client','COMPLETE','e'*64,
                'client-forged',
            )
        with self.assertRaises(TypeError):
            WireEnvelopeRef(
                'capture-x',CONNECTION,1,1,'server_to_client','COMPLETE','e'*64,
                client_instance_id='client-forged',
            )


if __name__=='__main__':
    unittest.main()
