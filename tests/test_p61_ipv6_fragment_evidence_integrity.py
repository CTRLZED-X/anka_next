"""P61: unsupported IPv6 TCP fragments must never be silently omitted."""
from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from anka_capture.api import CaptureRejected, inspect_pcapng
from anka_capture.pcapng import read_pcapng_tcp_segments
from anka_app.historical_pcapng_inventory import inspect_pcapng_flow_inventory
from anka_app.ipv6_fragment_smoke import ipv6_fragment_smoke
from tests.capture_fixtures import pcapng, packet


_PORT = 40400


def ipv6_tcp_frame(*, offset: int = 0, more: bool = False, fragment: bool = True,
                   port: int = _PORT, extension: bool = False, partial: bool = False) -> bytes:
    """An Ethernet/IPv6 frame. Non-initial fragments contain *no* TCP header."""
    tcp = struct.pack('!HHII', port, 55000, 101, 0) + bytes((0x50, 0x18)) + b'\0'*6
    body = b'\x11\x22\x33\x44\x55\x66\x77\x88' if offset else tcp
    if partial:
        body = body[:3]
    next_header = 6
    if fragment:
        flags = (offset << 3) | (1 if more else 0)
        body = struct.pack('!BBHI', 6, 0, flags, 123) + body
        next_header = 44
    if extension:
        body = bytes((next_header,0)) + b'\0'*6 + body
        next_header = 60
    ip = bytes((0x60,0,0,0)) + struct.pack('!HBB',len(body),next_header,64) + b'\x20\x01' + b'\0'*14 + b'\x20\x02' + b'\0'*14 + body
    return b'\x01'*12 + b'\x86\xdd' + ip


class TestP61Ipv6FragmentEvidenceIntegrity(unittest.TestCase):
    def test_normal_preflight_fragment_smoke(self):
        report=ipv6_fragment_smoke()
        self.assertEqual(report['status'],'PASS_UNCLASSIFIABLE_IPV6_FRAGMENT_QUARANTINED')
        self.assertFalse(report['current_client_certified'])
        self.assertEqual(report['canonical_commits'],0)

    def _inspect(self, *frames):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'fixture.pcapng'
            path.write_bytes(pcapng(*frames))
            return inspect_pcapng(path, server_ports=(_PORT,))

    def test_non_initial_tcp_fragment_without_ports_blocks_capture(self):
        with self.assertRaisesRegex(CaptureRejected,'CAPTURE_CONTENT_INVALID'):
            self._inspect(packet(100,flags=2,data=b'',reverse=True),
                          ipv6_tcp_frame(offset=3))

    def test_non_initial_tcp_fragment_with_destination_extension_blocks(self):
        with self.assertRaises(CaptureRejected):
            self._inspect(ipv6_tcp_frame(offset=2,extension=True))

    def test_non_initial_tcp_fragment_short_body_blocks(self):
        with self.assertRaises(CaptureRejected):
            self._inspect(ipv6_tcp_frame(offset=1,partial=True))

    def test_first_fragment_with_more_flag_blocks_even_if_port_not_selected(self):
        # No transport completeness can be established for this fragmented TCP flow.
        with self.assertRaises(CaptureRejected):
            self._inspect(ipv6_tcp_frame(offset=0,more=True,port=55555))

    def test_non_initial_fragment_blocks_flow_inventory(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'cap.pcapng'
            p.write_bytes(pcapng(packet(100,flags=2,data=b'',reverse=True),ipv6_tcp_frame(offset=2)))
            report=inspect_pcapng_flow_inventory(p,ports=(_PORT,))
            self.assertEqual(report.status,'BLOCKED_EVIDENCE')
            self.assertEqual(report.flows,())

    def test_unfragmented_selected_ipv6_tcp_stays_unsupported(self):
        with self.assertRaises(CaptureRejected):
            self._inspect(ipv6_tcp_frame(fragment=False))

    def test_atomic_fragment_selected_port_stays_unsupported(self):
        with self.assertRaises(CaptureRejected):
            self._inspect(ipv6_tcp_frame(offset=0,more=False))

    def test_unfragmented_unselected_ipv6_does_not_falsely_block_ipv4_research(self):
        receipt=self._inspect(packet(100,flags=2,data=b'',reverse=True),
                              ipv6_tcp_frame(fragment=False,port=55022))
        self.assertEqual(receipt.selected_segments,1)

    def test_atomic_unselected_ipv6_fragment_permitted(self):
        receipt=self._inspect(packet(100,flags=2,data=b'',reverse=True),
                              ipv6_tcp_frame(offset=0,more=False,port=55022))
        self.assertEqual(receipt.selected_segments,1)

    def test_selected_tcp_ipv6_with_extension_stays_unsupported(self):
        with self.assertRaises(CaptureRejected):
            self._inspect(ipv6_tcp_frame(fragment=False,extension=True))

    def test_noninitial_udp_fragment_does_not_falsely_imply_tcp(self):
        p = bytearray(ipv6_tcp_frame(offset=1))
        # IPv6 fragment Next Header is byte 54 (14 Ethernet + 40 IPv6).
        p[54] = 17
        receipt = self._inspect(packet(100,flags=2,data=b'',reverse=True),bytes(p))
        self.assertEqual(receipt.selected_segments,1)

    def test_reserved_fragment_flags_are_invalid(self):
        p=bytearray(ipv6_tcp_frame(offset=0))
        p[57] |= 0x02  # low reserved flag bit
        with self.assertRaises(CaptureRejected):
            self._inspect(bytes(p))

    def test_fragment_failure_is_not_a_source_of_character_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'cap.pcapng'
            p.write_bytes(pcapng(ipv6_tcp_frame(offset=7)))
            with self.assertRaises(ValueError):
                read_pcapng_tcp_segments(p,server_ports={_PORT})


if __name__=='__main__': unittest.main()
