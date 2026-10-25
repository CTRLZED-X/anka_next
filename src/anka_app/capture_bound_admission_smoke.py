"""Small hermetic P59 preflight: file-backed bytes, changed bytes, no authority."""
from __future__ import annotations
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from anka_app.capture_bound_admission_offline import review_capture_bound_admission
from anka_app.historical_pcapng_offline import _synthetic_pcap, _frame
from anka_contracts.admission import (AdmissionScope, AdmissionRehearsal,
                                      UntrustedCharacterClaim, UntrustedPacketClaim)
from anka_contracts.canonical import EvidenceRef, CanonicalDraft
from anka_capture.pcapng import read_pcapng_tcp_segments
from anka_protocol.adapters.historical import load_reference


def capture_bound_admission_smoke(root: Path) -> dict:
    catalog=load_reference(root)
    with TemporaryDirectory(prefix='anka_p59_capture_') as tmp:
        path=Path(tmp)/'research.pcapng'
        path.write_bytes(_synthetic_pcap(_frame('jnj',b'world')+_frame('jvj',b'turn')))
        flow=read_pcapng_tcp_segments(path,server_ports={40400})[0].flow_id
        flow_sha=sha256(flow.encode()).hexdigest()
        capture_sha=sha256(path.read_bytes()).hexdigest()
        scope=AdmissionScope('p59-session','p59-account',1,'p59-fight',
             catalog.protocol_build,catalog.adapter_id,flow_sha,1,2,3,capture_sha)
        def packet(name, body, index):
            source=EvidenceRef(catalog.protocol_build,catalog.adapter_id,name,2,1,flow_sha,
                               message_index=index)
            return UntrustedPacketClaim(source,'server_to_client',body,
                sha256(body).hexdigest(),capture_sha)
        first=packet('jnj',b'world',0)
        second=packet('jvj',b'turn',1)
        character=UntrustedCharacterClaim(first.evidence,7,sha256(b'private').hexdigest())
        draft=CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',7,second.evidence,resource='AP',value=11)
        rehearsal=AdmissionRehearsal(scope,character,(first,second),(draft,))
        valid=review_capture_bound_admission(rehearsal,capture_path=path,root=root,ports=(40400,))
        forged=replace(second,body=b'fake',body_sha256=sha256(b'fake').hexdigest())
        rejected=review_capture_bound_admission(replace(rehearsal,packets=(first,forged)),
                                                capture_path=path,root=root,ports=(40400,))
    if not (valid.status=='FILE_WIRE_MATCH_UNTRUSTED' and valid.matching_messages==2 and
            valid.file_bytes_match and not valid.authoritative and not valid.actionable and
            valid.canonical_commits==0 and not valid.physical_input_sent and
            rejected.status=='QUARANTINED' and
            'P59_CLAIM_WIRE_BYTES_MISMATCH' in rejected.reasons):
        raise RuntimeError('P59_SOURCE_CORROBORATION_BROKEN')
    return {'status':'PASS_PCAPNG_WIRE_CROSSCHECK_UNTRUSTED',
            'matched_source_records':valid.matching_messages,
            'forged_wire_claim_rejected':True,
            'current_client_certified':False,'account_binding_verified':False,
            'canonical_commits':0,'physical_input_sent':False}
