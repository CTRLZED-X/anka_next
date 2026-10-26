"""Chat 10 Issue #31 Phase A: immutable Protocol source-client binding."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict, fields
from hashlib import sha256
import json
import unittest

from anka_contracts.canonical import CanonicalCandidate
from anka_contracts.evidence import EvidencePointer
from anka_contracts.protocol import (
    BoundWireEnvelopeRef,
    CandidateCanonicalBatch,
    DecoderCheckpointRef,
    WireEnvelopeRef,
    derive_protocol_client_binding,
)
from anka_contracts.wire import WireEnvelope

ADAPTER='adapter-issue31-r1'
BUILD='Dofus Issue31'
CONNECTION='conn-issue31'

# Accepted-base Canonical-style digest for the direct legacy fixture below.
LEGACY_SOURCE_DIGEST='a958cad9999b3ccfa7491dc47a82e8579f6038e8a9fdf26e029a5289870e6965'
# Accepted-base Canonical-style digest for the real/default from_envelope source.
NORMAL_PRODUCTION_SOURCE_DIGEST='dd5e57220eb57fb4eb0052dc61a47fa197dccc07ae0cb0366a1e955c7daaff08'


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


def canonical_style_source_digest(value):
    """Mirror unchanged Canonical production _source_digest behavior."""
    obj={
        'adapter_release_id':value.adapter_release_id,
        'observed_client_build':value.observed_client_build,
        'connection_id':value.connection_id,
        'connection_generation':value.connection_generation,
        'source_envelopes':[asdict(x) for x in value.source_envelopes],
    }
    raw=json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)
    return sha256(raw.encode('utf-8')).hexdigest()


def legacy_ref():
    return WireEnvelopeRef(
        'capture-legacy',CONNECTION,1,7,'server_to_client','COMPLETE','a'*64
    )


def accepted_base_ref_for(source):
    """Reconstruct exactly what accepted-base from_envelope() serialized."""
    return WireEnvelopeRef(
        source.capture_session_id,source.connection_id,source.connection_generation,
        source.producer_sequence,source.direction,source.continuity,
        sha256(source.payload).hexdigest(),
    )


class TestIssue31LegacyCompatibility(unittest.TestCase):
    def test_old_seven_field_constructor_remains_valid(self):
        ref=legacy_ref()
        self.assertIsInstance(ref,WireEnvelopeRef)
        self.assertNotIsInstance(ref,BoundWireEnvelopeRef)
        self.assertFalse(ref.client_identity_proven)

    def test_legacy_dataclass_field_set_is_exactly_the_accepted_base_shape(self):
        self.assertEqual(
            tuple(x.name for x in fields(WireEnvelopeRef)),
            (
                'capture_session_id','connection_id','connection_generation',
                'producer_sequence','direction','continuity','payload_sha256',
            ),
        )

    def test_legacy_asdict_shape_is_exactly_unchanged(self):
        self.assertEqual(
            asdict(legacy_ref()),
            {
                'capture_session_id':'capture-legacy',
                'connection_id':CONNECTION,
                'connection_generation':1,
                'producer_sequence':7,
                'direction':'server_to_client',
                'continuity':'COMPLETE',
                'payload_sha256':'a'*64,
            },
        )

    def test_canonical_style_legacy_source_digest_matches_accepted_base_constant(self):
        b=batch((legacy_ref(),),batch_id='batch-legacy-digest')
        self.assertEqual(canonical_style_source_digest(b),LEGACY_SOURCE_DIGEST)
        self.assertEqual(b.source_identity_sha256,LEGACY_SOURCE_DIGEST)

    def test_stored_legacy_source_digest_still_matches_exact_legacy_replay(self):
        stored=LEGACY_SOURCE_DIGEST
        replay=batch((legacy_ref(),),batch_id='batch-legacy-replay')
        self.assertEqual(canonical_style_source_digest(replay),stored)
        self.assertEqual(replay.source_identity_sha256,stored)

    def test_legacy_source_remains_distinguishable_and_non_authoritative(self):
        b=batch((legacy_ref(),),batch_id='batch-legacy-unbound')
        binding=b.client_binding
        self.assertEqual(binding.status,'LEGACY_UNBOUND')
        self.assertIsNone(binding.source_client_instance_id)
        self.assertEqual(binding.source_client_instance_ids,())
        self.assertFalse(binding.authoritative)


class TestIssue31NormalProductionCompatibility(unittest.TestCase):
    def test_from_envelope_returns_client_bound_ref(self):
        source=envelope(client='client-cra')
        ref=WireEnvelopeRef.from_envelope(source)
        self.assertIsInstance(ref,WireEnvelopeRef)
        self.assertIsInstance(ref,BoundWireEnvelopeRef)
        self.assertEqual(ref.client_instance_id,'client-cra')
        self.assertTrue(ref.client_identity_proven)
        with self.assertRaises(FrozenInstanceError):
            ref.client_instance_id='client-enu'

    def test_direct_bound_constructor_cannot_assert_client_identity(self):
        source=envelope(client='client-cra')
        old=accepted_base_ref_for(source)
        with self.assertRaisesRegex(ValueError,'BOUND_WIRE_REF_REQUIRES_ENVELOPE'):
            BoundWireEnvelopeRef(
                old.capture_session_id,old.connection_id,old.connection_generation,
                old.producer_sequence,old.direction,old.continuity,old.payload_sha256,
                'client-forged',
            )

    def test_from_envelope_asdict_remains_exact_accepted_base_seven_fields(self):
        source=envelope(client='client-cra')
        bound=WireEnvelopeRef.from_envelope(source)
        accepted=accepted_base_ref_for(source)
        self.assertEqual(asdict(bound),asdict(accepted))
        self.assertEqual(
            tuple(asdict(bound)),
            (
                'capture_session_id','connection_id','connection_generation',
                'producer_sequence','direction','continuity','payload_sha256',
            ),
        )
        self.assertNotIn('client_instance_id',asdict(bound))

    def test_normal_production_canonical_digest_matches_accepted_base_constant(self):
        source=envelope(client='client-cra')
        current=batch((WireEnvelopeRef.from_envelope(source),),batch_id='batch-current')
        accepted=batch((accepted_base_ref_for(source),),batch_id='batch-accepted-base')
        self.assertEqual(canonical_style_source_digest(current),NORMAL_PRODUCTION_SOURCE_DIGEST)
        self.assertEqual(canonical_style_source_digest(accepted),NORMAL_PRODUCTION_SOURCE_DIGEST)

    def test_persisted_preupgrade_normal_batch_recognizes_same_replay_digest(self):
        stored=NORMAL_PRODUCTION_SOURCE_DIGEST
        replay=batch(
            (WireEnvelopeRef.from_envelope(envelope(client='client-cra')),),
            batch_id='batch-normal-replay',
        )
        self.assertEqual(canonical_style_source_digest(replay),stored)

    def test_current_canonical_digest_stays_compatible_while_new_identity_distinguishes_clients(self):
        cra=batch(
            (WireEnvelopeRef.from_envelope(envelope(client='client-cra',payload=b'same')),),
            batch_id='batch-cra',
        )
        enu=batch(
            (WireEnvelopeRef.from_envelope(envelope(client='client-enu',payload=b'same')),),
            batch_id='batch-enu',
        )
        # Existing Canonical is intentionally unchanged during EXPAND.
        self.assertEqual(canonical_style_source_digest(cra),canonical_style_source_digest(enu))
        # The new contract helper carries the stronger client-bound identity.
        self.assertNotEqual(cra.source_identity_sha256,enu.source_identity_sha256)

    def test_bound_ref_explicit_source_identity_distinguishes_cra_and_enu(self):
        cra=WireEnvelopeRef.from_envelope(envelope(client='client-cra',payload=b'same'))
        enu=WireEnvelopeRef.from_envelope(envelope(client='client-enu',payload=b'same'))
        self.assertEqual(asdict(cra),asdict(enu))
        self.assertNotEqual(cra.source_identity_sha256,enu.source_identity_sha256)

    def test_protocol_current_ref_equality_hash_and_membership_work_for_bound_refs(self):
        source=envelope(client='client-cra',seq=9,payload=b'current')
        current_ref=WireEnvelopeRef.from_envelope(source)
        adapter_ref=WireEnvelopeRef.from_envelope(source)
        self.assertEqual(current_ref,adapter_ref)
        self.assertEqual(hash(current_ref),hash(adapter_ref))
        self.assertIn(current_ref,(adapter_ref,))

    def test_bound_refs_for_different_clients_are_not_equal_or_hash_equal(self):
        cra=WireEnvelopeRef.from_envelope(envelope(client='client-cra',payload=b'same'))
        enu=WireEnvelopeRef.from_envelope(envelope(client='client-enu',payload=b'same'))
        self.assertNotEqual(cra,enu)
        self.assertNotEqual(hash(cra),hash(enu))

    def test_bound_and_unbound_evidence_are_not_equal_authority(self):
        source=envelope(client='client-cra',seq=4,payload=b'equal-shape')
        bound=WireEnvelopeRef.from_envelope(source)
        unbound=accepted_base_ref_for(source)
        self.assertEqual(asdict(bound),asdict(unbound))
        self.assertNotEqual(bound,unbound)
        binding=batch((bound,unbound),batch_id='batch-bound-unbound').client_binding
        self.assertEqual(binding.status,'LEGACY_UNBOUND')
        self.assertEqual(binding.source_client_instance_ids,('client-cra',))
        self.assertFalse(binding.authoritative)


class TestIssue31BindingSemantics(unittest.TestCase):
    def test_same_client_multi_envelope_buffered_source_is_proven(self):
        refs=(
            WireEnvelopeRef.from_envelope(envelope(client='client-cra',seq=1,payload=b'part-a')),
            WireEnvelopeRef.from_envelope(envelope(client='client-cra',seq=2,payload=b'part-b')),
        )
        b=batch(refs,(candidate('buffered-cra'),),batch_id='batch-buffered')
        self.assertEqual(b.client_binding.status,'PROVEN')
        self.assertEqual(b.client_binding.source_client_instance_id,'client-cra')
        self.assertEqual(b.client_binding.source_client_instance_ids,('client-cra',))
        self.assertTrue(b.client_binding.authoritative)

    def test_mixed_bound_clients_are_source_conflict(self):
        refs=(
            WireEnvelopeRef.from_envelope(envelope(client='client-cra',seq=1,payload=b'a')),
            WireEnvelopeRef.from_envelope(envelope(client='client-enu',seq=2,payload=b'b')),
        )
        binding=batch(refs,batch_id='batch-conflict').client_binding
        self.assertEqual(binding.status,'SOURCE_CONFLICT')
        self.assertEqual(binding.source_client_instance_ids,('client-cra','client-enu'))
        self.assertIsNone(binding.source_client_instance_id)
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

    def test_bound_source_wrong_candidate_client_is_mismatch(self):
        b=batch(
            (WireEnvelopeRef.from_envelope(envelope(client='client-cra')),),
            (candidate('wrong-client',client='client-enu',account='acct-enu'),),
            batch_id='batch-mismatch',
        )
        binding=b.client_binding
        self.assertEqual(binding.status,'CANDIDATE_MISMATCH')
        self.assertEqual(binding.source_client_instance_id,'client-cra')
        self.assertEqual(binding.candidate_client_instance_ids,('client-enu',))
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

    def test_bound_plus_unbound_remains_non_authoritative(self):
        source=envelope(client='client-cra',seq=2,payload=b'partial')
        refs=(WireEnvelopeRef.from_envelope(source),accepted_base_ref_for(source))
        binding=batch(refs,batch_id='batch-partial-unbound').client_binding
        self.assertEqual(binding.status,'LEGACY_UNBOUND')
        self.assertFalse(binding.authoritative)

    def test_zero_candidate_framing_batch_retains_bound_client_proof(self):
        framing=batch(
            (WireEnvelopeRef.from_envelope(envelope(client='client-cra')),),
            (),
            batch_id='batch-framing',
        )
        self.assertEqual(framing.decode_health,'FRAMING_IN_PROGRESS')
        self.assertEqual(framing.client_binding.status,'PROVEN')
        self.assertEqual(framing.client_binding.source_client_instance_id,'client-cra')
        self.assertTrue(framing.client_binding.authoritative)

    def test_account_identity_is_not_inferred_from_client_identity(self):
        ref=WireEnvelopeRef.from_envelope(envelope(client='client-cra'))
        c=candidate('separate-account-axis',client='client-cra',account='acct-explicit-other')
        b=batch((ref,),(c,),batch_id='batch-account-axis')
        self.assertEqual(b.client_binding.status,'PROVEN')
        self.assertEqual(c.account_id,'acct-explicit-other')
        self.assertFalse(hasattr(b.client_binding,'account_id'))

    def test_candidate_relabel_cannot_rewrite_immutable_source_identity(self):
        ref=WireEnvelopeRef.from_envelope(envelope(client='client-cra',payload=b'same-source'))
        good=batch((ref,),(candidate('good',client='client-cra'),),batch_id='batch-good')
        relabeled=batch((ref,),(candidate('bad',client='client-enu'),),batch_id='batch-bad')
        self.assertEqual(good.source_identity_sha256,relabeled.source_identity_sha256)
        self.assertEqual(good.client_binding.status,'PROVEN')
        self.assertEqual(relabeled.client_binding.status,'CANDIDATE_MISMATCH')
        self.assertFalse(relabeled.client_binding.authoritative)


if __name__=='__main__':
    unittest.main()
