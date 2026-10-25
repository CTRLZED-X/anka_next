"""P60 synthetic multi-flow preflight; verifies capture-packet-local selectors.

This exercises the real capture -> protocol -> P59 byte-corroboration path.
The synthetic 'character' / 'resource' claims are intentionally untrusted.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from struct import pack
from tempfile import TemporaryDirectory

from anka_app.historical_pcapng_offline import _block, _packet, _frame
from anka_app.capture_bound_admission_offline import review_capture_bound_admission
from anka_capture.pcapng import read_pcapng_tcp_segments
from anka_contracts.admission import AdmissionScope,AdmissionRehearsal,UntrustedPacketClaim,UntrustedCharacterClaim
from anka_contracts.canonical import EvidenceRef,CanonicalDraft
from anka_protocol.adapters.historical import load_reference


def _server_packet(seq: int, client_port: int, flags: int, body: bytes = b'') -> bytes:
    frame=bytearray(_packet(seq, flags, body))
    frame[36:38]=client_port.to_bytes(2,'big')
    return bytes(frame)


def packet_provenance_smoke(root:Path)->dict:
    catalog=load_reference(Path(root))
    a0,a1=_frame('jnj',b'char-a'),_frame('jvj',b'turn-a')
    b0,b1=_frame('jnj',b'char-b'),_frame('jvj',b'turn-b')
    packets=(
        _server_packet(100, 55001, 2), _server_packet(200, 55002, 2),
        _server_packet(101, 55001, 0x18, a0), _server_packet(201, 55002, 0x18, b0),
        _server_packet(101+len(a0), 55001, 0x18, a1),
        _server_packet(201+len(b0), 55002, 0x18, b1),
    )
    raw=(_block(0x0a0d0d0a,b'\x4d\x3c\x2b\x1a'+pack('<HHq',1,0,-1))+
         _block(1,pack('<HHI',1,0,65535))+
         b''.join(_block(6,pack('<IIIII',0,0,0,len(p),len(p))+p) for p in packets))
    with TemporaryDirectory(prefix='anka_p60_packet_scope_') as tmp:
        path=Path(tmp)/'mixed.pcapng'
        path.write_bytes(raw)
        capture_sha=sha256(raw).hexdigest()
        segments=read_pcapng_tcp_segments(path,server_ports={40400},raw=raw)
        flows={segments[2].flow_id:((3,b'char-a'),(5,b'turn-a')),
               segments[3].flow_id:((4,b'char-b'),(6,b'turn-b'))}
        if len(flows)!=2: raise RuntimeError('P60_FLOWS_NOT_DISTINCT')
        reviewed=0
        for ordinal,(flow,witness) in enumerate(flows.items()):
            flow_sha=sha256(flow.encode()).hexdigest()
            first,second=witness
            def claim(packet_and_body, name):
                packet_number,body=packet_and_body
                ref=EvidenceRef(catalog.protocol_build,catalog.adapter_id,name,
                    packet_number,1,flow_sha,message_index=0)
                return UntrustedPacketClaim(ref,'server_to_client',body,sha256(body).hexdigest(),capture_sha)
            a,b=claim(first,'jnj'),claim(second,'jvj')
            scope=AdmissionScope('p60-session',f'p60-actor-{ordinal}',1,'p60-fight',
                catalog.protocol_build,catalog.adapter_id,flow_sha,1,2,3,capture_sha)
            character=UntrustedCharacterClaim(a.evidence,13,sha256(b'character-'+bytes([ordinal])).hexdigest())
            draft=CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',13,b.evidence,resource='AP',value=11)
            report=review_capture_bound_admission(AdmissionRehearsal(scope,character,(a,b),(draft,)),
                capture_path=path,root=root,ports=(40400,))
            if report.status!='FILE_WIRE_MATCH_UNTRUSTED' or report.matching_messages!=2 or report.actionable:
                raise RuntimeError('P60_PACKET_LOCAL_WIRE_PROVENANCE_BROKEN')
            reviewed+=1
    return {'status':'PASS_MULTI_FLOW_PACKET_LOCAL_PROVENANCE',
            'flow_candidates_correlated':reviewed,'wire_observations_correlated':4,
            'current_client_certified':False,'account_binding_verified':False,
            'canonical_commits':0,'physical_input_sent':False}
