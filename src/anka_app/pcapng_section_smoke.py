"""P63 offline-only section framing proof for normal preflight."""
from __future__ import annotations

from struct import pack
from anka_capture.pcapng import pcapng_packet_count, read_pcapng_tcp_segments


def _block(kind: int, body: bytes) -> bytes:
    body += b'\0' * ((-len(body)) % 4)
    total = 12 + len(body)
    return pack('<II', kind, total) + body + pack('<I', total)


def pcapng_section_smoke() -> dict:
    idb = _block(1, pack('<HHI', 1, 0, 65535))
    shb = lambda size: _block(0x0a0d0d0a, pack('<IHHq', 0x1a2b3c4d, 1, 0, size))
    cases = ((idb, 'MISSING_SHB'),
             (shb(len(idb) + 4) + idb, 'TRUNCATED_SECTION'),
             (shb(0) + idb, 'SECTION_OVERRUN'))
    for capture, description in cases:
        for reader in ('count', 'segments'):
            try:
                if reader == 'count': pcapng_packet_count('unused', raw=capture)
                else: read_pcapng_tcp_segments('unused', server_ports={40400}, raw=capture)
            except ValueError: pass
            else: raise RuntimeError('P63_SECTION_INTEGRITY_SILENTLY_ACCEPTED_'+description+'_'+reader)
    if pcapng_packet_count('unused', raw=shb(len(idb))+idb) != 0:
        raise RuntimeError('P63_VALID_EXPLICIT_SECTION_REJECTED')
    return {'status':'PASS_SECTION_BOUNDARIES_FAIL_CLOSED',
            'cases_rejected':len(cases)*2, 'canonical_commits':0,
            'current_client_certified':False,'physical_input_sent':False}
