"""P58 admission contract falsification: checks never confer live authority."""
from __future__ import annotations
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from anka_contracts.admission import (AdmissionScope,UntrustedPacketClaim,
    UntrustedCharacterClaim,AdmissionRehearsal)
from anka_contracts.canonical import EvidenceRef,CanonicalDraft
from anka_canonical.admission_review import review_admission_rehearsal, MANDATORY_BLOCKERS
from anka_canonical.journal import SQLiteFixtureJournal
from anka_live_state.reducer import apply_offline_event


def _ref(packet:int, *,flow=None,build='Dofus-Current-Claim',adapter='claim-only',
         generation=7,wire='jvj',message_index=0):
    return EvidenceRef(build,adapter,wire,packet,generation,flow or 'a'*64,1,message_index)


def _packet(ref,body=b'claim',capture=None):
    return UntrustedPacketClaim(ref,'server_to_client',body,sha256(body).hexdigest(),capture or 'b'*64)


def fixture():
    scope=AdmissionScope('s01','account01',1,'fight01','Dofus-Current-Claim',
        'claim-only','a'*64,7,12,24,'b'*64)
    identity=UntrustedCharacterClaim(_ref(2,wire='jnj'),41,'c'*64)
    packet0=_packet(identity.evidence,b'world')
    ref=_ref(3)
    packet1=_packet(ref,b'active-turn')
    fact=CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',41,ref,resource='AP',value=11)
    return AdmissionRehearsal(scope,identity,(packet0,packet1),(fact,))


class P58AdmissionTests(unittest.TestCase):
    def check_reason(self,changed,reason):
        r=review_admission_rehearsal(changed)
        self.assertEqual(r.status,'QUARANTINED')
        self.assertIn(reason,r.reasons)
        self.assertFalse(r.authoritative)
        self.assertEqual(r.canonical_commits,0)

    def test_consistent_looking_current_claim_still_untrusted(self):
        result=review_admission_rehearsal(fixture())
        self.assertEqual(result.status,'STRUCTURALLY_CONSISTENT_UNTRUSTED')
        self.assertTrue(result.structural_consistency)
        self.assertTrue(set(MANDATORY_BLOCKERS).issubset(result.reasons))
        self.assertFalse(result.certified)
        self.assertFalse(result.authoritative)
        self.assertFalse(result.actionable)
        self.assertFalse(result.physical_input_sent)
        self.assertEqual(result.canonical_commits,0)

    def test_privacy_safe_report_has_no_actor_account_flow_or_packet_data(self):
        report=review_admission_rehearsal(fixture()).to_dict()
        combined=repr(report)
        for forbidden in ('account01','fight01','Dofus-Current-Claim','claim-only','a'*64,
                          'active-turn','world','actor_id','character_name','session_id'):
            self.assertNotIn(forbidden,combined)
        self.assertEqual(report['checked_packets'],2)
        self.assertEqual(report['checked_drafts'],1)

    def test_message_bytes_hash_mismatch_denied(self):
        with self.assertRaisesRegex(ValueError,'BODY_HASH_MISMATCH'):
            UntrustedPacketClaim(_ref(1),'server_to_client',b'wrong','0'*64,'b'*64)

    def test_empty_body_can_be_an_untrusted_packet(self):
        self.assertEqual(_packet(_ref(1),b'').body_sha256,sha256(b'').hexdigest())

    def test_body_size_bounded(self):
        with self.assertRaisesRegex(ValueError,'BODY_INVALID'):
            UntrustedPacketClaim(_ref(1),'server_to_client',b'x'*16385,sha256(b'x'*16385).hexdigest(),'b'*64)

    def test_packet_direction_must_be_declared(self):
        with self.assertRaisesRegex(ValueError,'SCOPE_INVALID'):
            UntrustedPacketClaim(_ref(1),'unknown',b'x',sha256(b'x').hexdigest(),'b'*64)

    def test_client_to_server_cannot_certify_server_observation(self):
        x=fixture();p=x.packets[1]
        self.check_reason(replace(x,packets=(x.packets[0],replace(p,direction='client_to_server'))),
                          'P58_UNTRUSTED_OR_NONSERVER_DIRECTION')

    def test_cross_capture_snapshot_is_rejected(self):
        x=fixture()
        self.check_reason(replace(x,packets=(x.packets[0],_packet(x.packets[1].evidence,capture='f'*64))),
                          'P58_CAPTURE_SNAPSHOT_MISMATCH')

    def test_historical_build_with_spaces_still_cannot_certify(self):
        x=fixture()
        build='Dofus 3.7.10.10'
        s=replace(x.scope,protocol_build=build)
        refs=[replace(p.evidence,protocol_build=build) for p in x.packets]
        packets=tuple(replace(p,evidence=ref) for p,ref in zip(x.packets,refs))
        identity=replace(x.character,evidence=refs[0])
        draft=replace(x.drafts[0],evidence=refs[1])
        r=review_admission_rehearsal(AdmissionRehearsal(s,identity,packets,(draft,)))
        self.assertTrue(r.structural_consistency)
        self.assertFalse(r.certified)

    def test_cross_flow_packet_is_rejected(self):
        x=fixture();ref=_ref(3,flow='d'*64)
        draft=replace(x.drafts[0],evidence=ref)
        self.check_reason(replace(x,packets=(x.packets[0],_packet(ref)),drafts=(draft,)),
                          'P58_PACKET_SCOPE_MISMATCH')

    def test_cross_build_packet_is_rejected(self):
        x=fixture();ref=_ref(3,build='DifferentBuild')
        self.check_reason(replace(x,packets=(x.packets[0],_packet(ref))),
                          'P58_PACKET_SCOPE_MISMATCH')

    def test_cross_adapter_packet_is_rejected(self):
        x=fixture();ref=_ref(3,adapter='OtherAdapter')
        self.check_reason(replace(x,packets=(x.packets[0],_packet(ref))),
                          'P58_PACKET_SCOPE_MISMATCH')

    def test_cross_transport_generation_is_rejected(self):
        x=fixture();ref=_ref(3,generation=8)
        self.check_reason(replace(x,packets=(x.packets[0],_packet(ref))),
                          'P58_PACKET_SCOPE_MISMATCH')

    def test_semantic_without_source_packet_fails(self):
        x=fixture()
        self.check_reason(replace(x,packets=(x.packets[0],)),
                          'P58_SEMANTIC_PACKET_NOT_PRESENT')

    def test_character_without_source_packet_fails(self):
        x=fixture()
        self.check_reason(replace(x,packets=(x.packets[1],)),
                          'P58_CHARACTER_PACKET_NOT_PRESENT')

    def test_same_source_twice_rejected(self):
        x=fixture();self.check_reason(replace(x,packets=(x.packets[0],x.packets[1],x.packets[1])),
            'P58_DUPLICATE_PACKET_SOURCE')

    def test_reordered_source_rejected(self):
        x=fixture();self.check_reason(replace(x,packets=tuple(reversed(x.packets))),
            'P58_PACKET_SOURCE_NOT_ORDERED')

    def test_same_ordinal_different_wire_rejected(self):
        x=fixture();ref=_ref(3,wire='other')
        changed=replace(x,packets=(x.packets[0],_packet(ref)))
        self.check_reason(changed,'P58_SEMANTIC_PACKET_PROVENANCE_MISMATCH')

    def test_identity_precedes_semantic(self):
        x=fixture();new_identity=replace(x.character,evidence=_ref(4,wire='jnj'))
        changed=replace(x,character=new_identity,packets=(x.packets[1],_packet(new_identity.evidence)))
        self.check_reason(changed,'P58_SEMANTIC_NOT_AFTER_CHARACTER_WITNESS')

    def test_duplicate_fact_source_rejected(self):
        x=fixture();self.check_reason(replace(x,drafts=(x.drafts[0],x.drafts[0])),
            'P58_DUPLICATE_OR_CONFLICTING_FACT_SOURCE')

    def test_different_fields_same_message_allowed_for_research_only(self):
        x=fixture()
        hp=CanonicalDraft('ACTOR_HP_ABSOLUTE',41,x.drafts[0].evidence,value=300,maximum=500)
        result=review_admission_rehearsal(replace(x,drafts=(x.drafts[0],hp)))
        self.assertTrue(result.structural_consistency)
        self.assertEqual(result.checked_drafts,2)
        self.assertFalse(result.certified)

    def test_conflicting_fact_same_packet_rejected(self):
        x=fixture();changed=replace(x.drafts[0],value=9)
        self.check_reason(replace(x,drafts=(x.drafts[0],changed)),
            'P58_DUPLICATE_OR_CONFLICTING_FACT_SOURCE')

    def test_foreign_actor_allowed_but_not_as_only_local_actor(self):
        x=fixture();enemy=replace(x.drafts[0],actor_id=123)
        self.check_reason(replace(x,drafts=(enemy,)),
            'P58_LOCAL_CHARACTER_ACTOR_NOT_OBSERVED')
        other_ref=_ref(4)
        added=replace(x,packets=x.packets+(_packet(other_ref),),
            drafts=x.drafts+(replace(enemy,evidence=other_ref),))
        self.assertTrue(review_admission_rehearsal(added).structural_consistency)

    def test_unknown_provenance_generation_change_fails(self):
        x=fixture()
        changed=replace(x,character=replace(x.character,evidence=_ref(2,generation=8,wire='jnj')))
        self.check_reason(changed,'P58_CHARACTER_SCOPE_MISMATCH')

    def test_invalid_account_generation_and_sha_are_rejected(self):
        x=fixture()
        with self.assertRaisesRegex(ValueError,'GENERATION_INVALID'):
            replace(x.scope,account_generation=True)
        with self.assertRaisesRegex(ValueError,'DIGEST_INVALID'):
            replace(x.scope,capture_sha256='not_sha')

    def test_unbounded_or_non_tuple_batch_is_rejected(self):
        x=fixture()
        with self.assertRaisesRegex(ValueError,'PACKET_LIMIT_OR_TYPE'):
            replace(x,packets=list(x.packets))
        with self.assertRaisesRegex(ValueError,'DRAFT_LIMIT_OR_TYPE'):
            replace(x,drafts=())

    def test_journal_rejects_untrusted_claims_even_when_structurally_consistent(self):
        x=fixture();self.assertTrue(review_admission_rehearsal(x).structural_consistency)
        with tempfile.TemporaryDirectory() as d:
            with SQLiteFixtureJournal(Path(d)/'test.db',reducer=apply_offline_event) as journal:
                with self.assertRaises(TypeError):
                    journal.append_fixture_envelope(x)
                with self.assertRaises(Exception):
                    journal.append_fixture_batch(x.drafts)
                self.assertEqual(journal.audit()['events'],0)
                self.assertEqual(journal.audit()['batch_receipts'],0)

    def test_invalid_rehearsal_type_is_not_normalized(self):
        with self.assertRaisesRegex(TypeError,'REHEARSAL_REQUIRED'):
            review_admission_rehearsal({'scope':'something'})

    def test_preflight_smoke(self):
        from anka_app.admission_offline import admission_boundary_smoke
        result=admission_boundary_smoke()
        self.assertEqual(result['status'],'PASS_UNTRUSTED_ADMISSION_BLOCKED')
        self.assertEqual(result['canonical_commits'],0)
        self.assertFalse(result['live_ready'])

if __name__=='__main__':unittest.main()
