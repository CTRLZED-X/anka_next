"""Small P49 end-to-end PCAPNG fixture for automatic read-only setup preflight.

This is an intentionally synthetic packet builder, not a decoder oracle or a
certified capture. Its sole purpose is to ensure the PCAPNG integration path
remains wired and retains mandatory source-uncertainty blockers.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from struct import pack
from hashlib import sha256

from anka_app.historical_pcapng_bridge import inspect_historical_pcapng
from anka_capture.pcapng import read_pcapng_tcp_segments
from anka_contracts.historical_lifecycle import LegacyFightScope
from anka_protocol.adapters.historical_lifecycle import BUILD


def _var(n: int) -> bytes:
    result=[]
    while n >= 128:
        result.append((n & 127) | 128)
        n >>= 7
    return bytes(result + [n])


def _field(number: int, value: bytes) -> bytes:
    return _var((number << 3) | 2) + _var(len(value)) + value


def _frame(name: str, payload: bytes) -> bytes:
    body = _field(1, ('type.ankama.com/' + name).encode('ascii')) + _field(2, payload)
    return _var(len(body)) + body


def _block(kind: int, payload: bytes) -> bytes:
    payload += bytes((-len(payload)) % 4)
    total = 12 + len(payload)
    return pack('<II', kind, total) + payload + pack('<I', total)


def _packet(seq: int, flags: int, body: bytes) -> bytes:
    tcp = pack('!HHII', 40400, 55000, seq, 0) + bytes((0x50, flags)) + bytes(6)
    ip = bytes((0x45, 0)) + pack('!H',20 + len(tcp) + len(body)) + b'\x00\x01\x00\x00' + bytes((64,6,0,0))
    ip += bytes((192,0,2,2,192,0,2,1))
    return bytes(12) + b'\x08\x00' + ip + tcp + body


def _synthetic_pcap(wire: bytes) -> bytes:
    packets = (_packet(100, 2, b''), _packet(101, 0x18, wire))
    section = _block(0x0a0d0d0a, b'\x4d\x3c\x2b\x1a' + pack('<HHq',1,0,-1))
    interface = _block(1, pack('<HHI',1,0,65535))
    return section + interface + b''.join(
        _block(6, pack('<IIIII',0,0,0,len(pkt),len(pkt)) + pkt) for pkt in packets)


def historical_pcapng_smoke(root: Path) -> dict:
    wire = (_frame('jvj', _var(3<<3)+_var(33)) +
            _frame('jup', _var(2<<3)+_var(33)) + _frame('jwp', b''))
    with TemporaryDirectory(prefix='anka_p49_fixture_') as directory:
        capture=Path(directory)/'fixture.pcapng'
        capture.write_bytes(_synthetic_pcap(wire))
        segment=read_pcapng_tcp_segments(capture, server_ports={40400})[0]
        scope=LegacyFightScope(37,sha256(segment.flow_id.encode()).hexdigest(),1,BUILD)
        report=inspect_historical_pcapng(capture, root=root, ports=(40400,), scope=scope)
    if not (report.reason=='P49_DRIVER_LOSS_AND_ACCOUNT_PROOF_MISSING' and
            report.status=='BLOCKED_EVIDENCE' and report.observed_historical_events==3 and
            report.transport_research is not None and
            report.transport_research.protocol_status=='INCOMPLETE_EVIDENCE_OBSERVATION_ONLY' and
            not report.actionable and not report.current_client_certified and
            not report.account_binding_verified and report.canonical_commits==0 and
            not report.physical_input_sent):
        raise RuntimeError('P49_OFFLINE_PCAPNG_SMOKE_FAILED')
    return {'status':'PASS_UNCERTIFIED_HISTORICAL_PCAPNG',
        'observed_research_messages': report.observed_historical_events,
        'capture_driver_proof':False,'account_binding_verified':False,
        'live_ready':False,'canonical_commits':0,'physical_input_sent':False}
