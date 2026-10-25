"""P60: independent TCP flows must not change each other's packet-scoped wire selectors."""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from anka_app.capture_bound_admission_offline import review_capture_bound_admission
from anka_app.historical_pcapng_offline import _frame
from anka_capture.pcapng import read_pcapng_tcp_segments
from anka_contracts.admission import AdmissionRehearsal, AdmissionScope, UntrustedCharacterClaim, UntrustedPacketClaim
from anka_contracts.canonical import CanonicalDraft, EvidenceRef
from anka_protocol.adapters.historical import load_reference
from anka_protocol.api import ProtocolInspector
from tests.capture_fixtures import packet, pcapng

ROOT = Path(__file__).resolve().parents[1]


def server_packet(seq: int, client_port: int, flags: int, data: bytes = b'') -> bytes:
    raw = bytearray(packet(seq=seq, flags=flags, data=data, reverse=True))
    raw[36:38] = client_port.to_bytes(2, 'big')
    return bytes(raw)


def interleaved_capture():
    first = _frame('jnj', b'world-a')
    second = _frame('jvj', b'turn-a')
    other_first = _frame('jnj', b'world-b')
    other_second = _frame('jvj', b'turn-b')
    return pcapng(
        server_packet(100, 55001, 2), server_packet(200, 55002, 2),
        server_packet(101, 55001, 0x18, first),
        server_packet(201, 55002, 0x18, other_first),
        server_packet(101 + len(first), 55001, 0x18, second),
        server_packet(201 + len(other_first), 55002, 0x18, other_second),
    )


class PacketLocalProvenanceTests(unittest.TestCase):
    def test_interleaved_connections_each_have_stable_packet_local_indexes(self):
        with tempfile.TemporaryDirectory() as tmp:
            capture = Path(tmp) / 'mixed.pcapng'
            capture.write_bytes(interleaved_capture())
            segments = read_pcapng_tcp_segments(capture, server_ports={40400})
            observed = []
            c = load_reference(ROOT)
            decoder = ProtocolInspector(c, requested_build=c.protocol_build, on_message=observed.append)
            for segment in segments: decoder.consume(segment)
            receipt = decoder.finish()
            self.assertEqual(receipt.framed_messages, 4)
            self.assertEqual(decoder.messages, 4)  # global count remains a *count*
            self.assertEqual([(m.packet_number, m.message_index) for m in observed],
                             [(3, 0), (4, 0), (5, 0), (6, 0)])
            self.assertEqual(len({(m.flow_key, m.packet_number, m.message_index) for m in observed}),4)

    def test_multiple_messages_in_one_packet_keep_distinct_local_ordinals(self):
        first = _frame('jnj', b'one') + _frame('jvj', b'two')
        c = load_reference(ROOT)
        out = []
        inspector = ProtocolInspector(c, requested_build=c.protocol_build, on_message=out.append)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'same.pcapng'
            p.write_bytes(pcapng(server_packet(100,55001,2),server_packet(101,55001,0x18,first)))
            for s in read_pcapng_tcp_segments(p, server_ports={40400}): inspector.consume(s)
        self.assertEqual(inspector.finish().framed_messages, 2)
        self.assertEqual([(x.packet_number, x.message_index) for x in out], [(2,0),(2,1)])

    def test_both_accounts_correspond_to_same_snapshot_without_index_crosstalk(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'mixed.pcapng'
            file.write_bytes(interleaved_capture())
            source_sha=sha256(file.read_bytes()).hexdigest()
            segments=read_pcapng_tcp_segments(file,server_ports={40400})
            catalog=load_reference(ROOT)
            sources=sorted({s.flow_id for s in segments})
            self.assertEqual(len(sources),2)
            for i,flow in enumerate(sources):
                d=sha256(flow.encode()).hexdigest()
                # Packet ordinals reflect the shared capture; message index is per packet.
                pkts=(3,5) if any(s.flow_id==flow and s.packet_number==3 for s in segments) else (4,6)
                def claim(idx, name, body):
                    ref=EvidenceRef(catalog.protocol_build,catalog.adapter_id,name,pkts[idx],1,d,message_index=0)
                    return UntrustedPacketClaim(ref,'server_to_client',body,sha256(body).hexdigest(),source_sha)
                suffix=b'a' if pkts[0]==3 else b'b'
                one=claim(0,'jnj',b'world-'+suffix)
                two=claim(1,'jvj',b'turn-'+suffix)
                scope=AdmissionScope('shared','account'+str(i),1,'fight'+str(i),catalog.protocol_build,
                          catalog.adapter_id,d,1,4,5,source_sha)
                char=UntrustedCharacterClaim(one.evidence,41,sha256(b'name'+suffix).hexdigest())
                fact=CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',41,two.evidence,resource='AP',value=11)
                review=review_capture_bound_admission(AdmissionRehearsal(scope,char,(one,two),(fact,)),
                               capture_path=file,root=ROOT,ports=(40400,))
                self.assertEqual(review.status,'FILE_WIRE_MATCH_UNTRUSTED',review.to_dict())
                self.assertEqual(review.matching_messages,2)
                self.assertFalse(review.actionable)

    def test_an_unrelated_extra_packet_cannot_relabel_selected_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'capture.pcapng'
            unrelated=_frame('jsq',b'x')
            own=_frame('jnj',b'world')
            f.write_bytes(pcapng(
                server_packet(400, 55002, 2),server_packet(100, 55001, 2),
                server_packet(401, 55002, 0x18, unrelated),
                server_packet(101, 55001, 0x18, own)))
            observed=[]
            catalog=load_reference(ROOT)
            decoder=ProtocolInspector(catalog,requested_build=catalog.protocol_build,on_message=observed.append)
            for s in read_pcapng_tcp_segments(f,server_ports={40400}): decoder.consume(s)
            self.assertEqual(decoder.finish().framed_messages,2)
            self.assertEqual([(x.packet_number,x.message_index) for x in observed],[(3,0),(4,0)])

if __name__ == '__main__': unittest.main()
