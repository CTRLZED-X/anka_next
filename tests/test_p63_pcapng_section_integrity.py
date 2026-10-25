"""P63: authoritative PCAPNG section boundaries shared by both research readers."""
from __future__ import annotations

import struct
import unittest
from pathlib import Path

from anka_capture.pcapng import pcapng_packet_count, read_pcapng_tcp_segments
from anka_app.pcapng_section_smoke import pcapng_section_smoke
from tests.capture_fixtures import block, packet, pcapng


def _shb(endian: str = '<', length: int = -1, major: int = 1, minor: int = 0) -> bytes:
    body = struct.pack(endian+'IHHq', 0x1a2b3c4d, major, minor, length)
    return block(0x0a0d0d0a, body, endian)


def _idb(endian: str = '<') -> bytes:
    return block(1, struct.pack(endian+'HHI', 1, 0, 65535), endian)


def _epb(endian: str = '<') -> bytes:
    p = packet(seq=100, flags=0x18, data=b'P63')
    return block(6, struct.pack(endian+'IIIII',0,0,0,len(p),len(p)) + p, endian)


def _section(endian: str = '<', length: int | None = None) -> bytes:
    content = _idb(endian) + _epb(endian)
    return _shb(endian, len(content) if length is None else length) + content


class TestP63PcapngSectionIntegrity(unittest.TestCase):
    def _both(self, raw: bytes) -> tuple[int,int]:
        return (pcapng_packet_count('unused', raw=raw),
                len(read_pcapng_tcp_segments('unused', server_ports={40400}, raw=raw)))

    def _reject_both(self, raw: bytes) -> None:
        for reader in ('count','segments'):
            with self.subTest(reader=reader):
                with self.assertRaises(ValueError):
                    if reader == 'count': pcapng_packet_count('unused', raw=raw)
                    else: read_pcapng_tcp_segments('unused', server_ports={40400}, raw=raw)

    def test_preflight_smoke(self):
        self.assertEqual(pcapng_section_smoke()['status'],'PASS_SECTION_BOUNDARIES_FAIL_CLOSED')

    def test_missing_section_header_rejected(self):
        self._reject_both(_idb()+_epb())

    def test_orphan_packet_block_rejected(self):
        self._reject_both(_epb())

    def test_empty_raw_file_rejected(self):
        self._reject_both(b'')

    def test_unsupported_section_versions_rejected(self):
        for major,minor in ((0,0),(2,0),(1,1),(0xffff,0)):
            with self.subTest(version=(major,minor)):
                self._reject_both(_shb(major=major,minor=minor)+_idb()+_epb())

    def test_valid_exact_length_little_endian(self):
        self.assertEqual(self._both(_section('<')), (1,1))

    def test_valid_exact_length_big_endian(self):
        self.assertEqual(self._both(_section('>')), (1,1))

    def test_valid_unknown_length(self):
        self.assertEqual(self._both(pcapng(packet())), (1,1))

    def test_exact_length_too_short(self):
        content_len = len(_idb())+len(_epb())
        self._reject_both(_section(length=content_len-4))

    def test_exact_length_too_long(self):
        content_len = len(_idb())+len(_epb())
        self._reject_both(_section(length=content_len+4))

    def test_exact_length_extra_packet(self):
        data=_section()+_epb()
        self._reject_both(data)  # extra block after declared end without new SHB

    def test_exact_length_early_next_section(self):
        self._reject_both(_section(length=len(_idb())+len(_epb())+len(_idb())) + _section())

    def test_malformed_negative_section_lengths_rejected(self):
        for length in (-2,-20,3,-0x7fffffffffffffff):
            with self.subTest(length=length):
                self._reject_both(_section(length=length))

    def test_multiple_sections_with_explicit_lengths(self):
        data=_section('<')+_section('>')
        self.assertEqual(self._both(data),(2,2))

    def test_mixed_explicit_and_unknown_sections(self):
        data=_section('<',-1)+_section('>')
        self.assertEqual(self._both(data),(2,2))

    def test_valid_zero_length_section(self):
        self.assertEqual(self._both(_shb(length=0)),(0,0))

    def test_first_section_exact_length_end_before_trailing_bytes(self):
        self._reject_both(_section()+b'\x00\x00\x00\x00')


if __name__=='__main__': unittest.main()
