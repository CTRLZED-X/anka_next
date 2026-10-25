"""P59 saved-capture corroboration never becomes independent current-client proof."""
import tempfile
import unittest
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from anka_app.historical_pcapng_offline import _synthetic_pcap, _frame
from anka_app.capture_bound_admission_offline import review_capture_bound_admission
from anka_canonical.admission_review import review_admission_rehearsal
from anka_contracts.admission import (AdmissionScope, AdmissionRehearsal,
                                      UntrustedPacketClaim, UntrustedCharacterClaim)
from anka_contracts.canonical import EvidenceRef, CanonicalDraft
from anka_capture.pcapng import read_pcapng_tcp_segments
from anka_protocol.adapters.historical import load_reference
from anka_canonical.journal import SQLiteFixtureJournal
from anka_live_state.reducer import apply_offline_event

ROOT = Path(__file__).resolve().parents[1]


def scenario(directory, *, wire=None):
    catalog = load_reference(ROOT)
    wire = wire if wire is not None else _frame('jnj', b'world') + _frame('jvj', b'turn')
    path = directory / 'capture.pcapng'
    path.write_bytes(_synthetic_pcap(wire))
    selected = read_pcapng_tcp_segments(path, server_ports={40400})[0]
    digest = sha256(selected.flow_id.encode()).hexdigest()
    capture_sha = sha256(path.read_bytes()).hexdigest()
    scope = AdmissionScope('s59', 'account59', 1, 'fight59', catalog.protocol_build,
        catalog.adapter_id, digest, 1, 4, 5, capture_sha)
    def packet(name, body, index):
        ref=EvidenceRef(catalog.protocol_build, catalog.adapter_id, name, 2, 1,
                        digest, message_index=index)
        return UntrustedPacketClaim(ref, 'server_to_client', body,
                                    sha256(body).hexdigest(), capture_sha)
    p0,p1=packet('jnj', b'world',0),packet('jvj',b'turn',1)
    char=UntrustedCharacterClaim(p0.evidence,41,sha256(b'private-char').hexdigest())
    fact=CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',41,p1.evidence,resource='AP',value=11)
    return path,AdmissionRehearsal(scope,char,(p0,p1),(fact,))


class P59CaptureBoundTests(unittest.TestCase):
    def check(self, rehearsal, path, *, wanted):
        r=review_capture_bound_admission(rehearsal,capture_path=path,root=ROOT,ports=(40400,))
        self.assertEqual(r.status,'QUARANTINED')
        self.assertIn(wanted,r.reasons)
        self.assertFalse(r.actionable)
        self.assertFalse(r.authoritative)
        self.assertFalse(r.current_client_certified)
        return r

    def test_exact_historical_bytes_and_ordinal_match_untrusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,claim=scenario(Path(tmp))
            self.assertTrue(review_admission_rehearsal(claim).structural_consistency)
            r=review_capture_bound_admission(claim,capture_path=path,root=ROOT,ports=(40400,))
            self.assertEqual(r.status,'FILE_WIRE_MATCH_UNTRUSTED')
            self.assertEqual(r.matching_messages,2)
            self.assertEqual(r.observed_selected_messages,2)
            self.assertTrue(r.file_bytes_match)
            self.assertFalse(r.driver_loss_proven)
            self.assertFalse(r.account_binding_verified)
            self.assertEqual(r.canonical_commits,0)
            with SQLiteFixtureJournal(Path(tmp)/'events.db',reducer=apply_offline_event) as journal:
                with self.assertRaises(TypeError):journal.append_fixture_envelope(r)
                self.assertEqual(journal.audit()['events'],0)

    def test_caller_supplied_fake_capture_hash_cannot_corroborate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,x=scenario(Path(tmp)); fake='a'*64
            new_scope=replace(x.scope,capture_sha256=fake)
            new_packets=tuple(replace(p,capture_sha256=fake) for p in x.packets)
            r=self.check(replace(x,scope=new_scope,packets=new_packets),path,
                         wanted='P59_CAPTURE_FILE_HASH_MISMATCH')
            self.assertFalse(r.file_bytes_match)

    def test_claimed_bytes_are_not_independent_wire_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,x=scenario(Path(tmp))
            p=x.packets[1]
            bad=replace(p,body=b'other',body_sha256=sha256(b'other').hexdigest())
            self.assertTrue(review_admission_rehearsal(replace(x,packets=(x.packets[0],bad))).structural_consistency)
            self.check(replace(x,packets=(x.packets[0],bad)),path,
                       wanted='P59_CLAIM_WIRE_BYTES_MISMATCH')

    def test_wire_position_cannot_be_relabelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,x=scenario(Path(tmp))
            moved=replace(x.packets[1].evidence,message_index=99)
            y=replace(x,packets=(x.packets[0],replace(x.packets[1],evidence=moved)),
                      drafts=(replace(x.drafts[0],evidence=moved),))
            self.check(y,path,wanted='P59_CLAIM_SOURCE_NOT_OBSERVED')

    def test_extra_selected_wire_never_disappears(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,x=scenario(Path(tmp))
            new_wire=_frame('jnj',b'world')+_frame('jvj',b'turn')+_frame('jup',b'end')
            path.write_bytes(_synthetic_pcap(new_wire))
            new_sha=sha256(path.read_bytes()).hexdigest()
            new_x=replace(x,scope=replace(x.scope,capture_sha256=new_sha),
                          packets=tuple(replace(p,capture_sha256=new_sha) for p in x.packets))
            self.check(new_x,path,wanted='P59_UNCLAIMED_SELECTED_WIRE_MESSAGE')

    def test_missing_second_message_is_not_reported_as_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,x=scenario(Path(tmp))
            path.write_bytes(_synthetic_pcap(_frame('jnj',b'world')))
            new_sha=sha256(path.read_bytes()).hexdigest()
            new_x=replace(x,scope=replace(x.scope,capture_sha256=new_sha),
                          packets=tuple(replace(p,capture_sha256=new_sha) for p in x.packets))
            self.check(new_x,path,wanted='P59_CLAIM_SOURCE_NOT_OBSERVED')

    def test_malformed_file_is_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,x=scenario(Path(tmp))
            path.write_bytes(b'invalid')
            self.check(x,path,wanted='P59_CAPTURE_OR_WIRE_READ_REJECTED')

    def test_missing_file_quarantined_without_raw_path_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,x=scenario(Path(tmp))
            path.unlink()
            r=self.check(x,path,wanted='P59_CAPTURE_OR_WIRE_READ_REJECTED')
            self.assertNotIn(str(path),repr(r.to_dict()))

    def test_unknown_current_client_build_is_rejected_even_if_file_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,x=scenario(Path(tmp))
            build='Dofus-Unknown-Current'
            y=replace(x,scope=replace(x.scope,protocol_build=build),
                      packets=tuple(replace(p,evidence=replace(p.evidence,protocol_build=build)) for p in x.packets),
                      character=replace(x.character,evidence=replace(x.character.evidence,protocol_build=build)),
                      drafts=(replace(x.drafts[0],evidence=replace(x.drafts[0].evidence,protocol_build=build)),))
            self.check(y,path,wanted='P59_UNSUPPORTED_OR_MISMATCHED_HISTORICAL_BUILD')

    def test_capture_content_change_between_passes_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,x=scenario(Path(tmp))
            from anka_app import capture_bound_admission_offline as module
            actual=module.inspect_pcapng
            def change(*args, **kwargs):
                r=actual(*args,**kwargs)
                path.write_bytes(path.read_bytes()+b'tampered')
                return r
            with patch.object(module,'inspect_pcapng',side_effect=change):
                self.check(x,path,wanted='P59_CAPTURE_FILE_CHANGED')

    def test_frame_without_envelope_is_visible_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,x=scenario(Path(tmp))
            # A zero-field protobuf-looking frame with no Any envelope.
            weird=b'\x02\x08\x01'
            path.write_bytes(_synthetic_pcap(_frame('jnj',b'world')+_frame('jvj',b'turn')+weird))
            new_sha=sha256(path.read_bytes()).hexdigest()
            y=replace(x,scope=replace(x.scope,capture_sha256=new_sha),
                      packets=tuple(replace(p,capture_sha256=new_sha) for p in x.packets))
            self.check(y,path,wanted='P59_WIRE_STREAM_INCOMPLETE_OR_QUARANTINED')

    def test_corrupt_claim_type_cannot_trigger_implicit_normalization(self):
        with self.assertRaisesRegex(TypeError,'P59_ADMISSION_REHEARSAL_REQUIRED'):
            review_capture_bound_admission({'claims':()},capture_path=Path('whatever'),root=ROOT,ports=(40400,))

    def test_no_extra_fields_in_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,x=scenario(Path(tmp));r=review_capture_bound_admission(x,capture_path=path,root=ROOT,ports=(40400,))
            serialized=repr(r.to_dict())
            for secret in (str(path),x.scope.account_id,x.scope.flow_digest,x.scope.capture_sha256,
                           x.packets[0].body.decode(),'actor_id','password','endpoint'):
                self.assertNotIn(secret,serialized)


if __name__=='__main__':unittest.main()
