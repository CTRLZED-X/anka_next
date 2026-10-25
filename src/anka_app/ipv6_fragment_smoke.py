"""P61 synthetic fail-closed transport-ingress smoke for normal preflight.

The IPv6 fragment has no TCP port information, so a selected capture cannot
silently treat it as absent. This is not live capture certification.
"""
from __future__ import annotations

from pathlib import Path
from struct import pack
from tempfile import TemporaryDirectory

from anka_capture.api import inspect_pcapng, CaptureRejected
from anka_app.historical_pcapng_offline import _block, _packet


def ipv6_fragment_smoke() -> dict:
    # First include valid, obviously synthetic IPv4 traffic on the configured
    # reference port. The second packet is a TCP fragment without port bytes.
    ipv4 = _packet(100, 2, b'')
    payload = b'\x11\x22\x33\x44\x55\x66\x77\x88'
    frag = pack('!BBHI', 6, 0, 3 << 3, 123) + payload
    ipv6 = (b'\x01'*12 + b'\x86\xdd' + b'\x60\x00\x00\x00' +
            pack('!HBB', len(frag), 44, 64) + b'\x20\x01'+b'\0'*14 +
            b'\x20\x02'+b'\0'*14 + frag)
    raw = (_block(0x0a0d0d0a, b'\x4d\x3c\x2b\x1a'+pack('<HHq',1,0,-1)) +
           _block(1,pack('<HHI',1,0,65535)) +
           b''.join(_block(6,pack('<IIIII',0,0,0,len(pkt),len(pkt))+pkt)
                    for pkt in (ipv4,ipv6)))
    with TemporaryDirectory(prefix='anka_p61_ipv6_fragment_') as d:
        path=Path(d)/'fixture.pcapng'
        path.write_bytes(raw)
        try:
            inspect_pcapng(path,server_ports=(40400,))
        except CaptureRejected as exc:
            if str(exc) != 'CAPTURE_CONTENT_INVALID':
                raise RuntimeError('P61_FRAGMENT_WRONG_REJECTION') from None
        else:
            raise RuntimeError('P61_FRAGMENT_SILENTLY_OMITTED')
    return {'status':'PASS_UNCLASSIFIABLE_IPV6_FRAGMENT_QUARANTINED',
            'silent_traffic_omission_prevented':True,
            'current_client_certified':False,'account_binding_verified':False,
            'canonical_commits':0,'physical_input_sent':False}
