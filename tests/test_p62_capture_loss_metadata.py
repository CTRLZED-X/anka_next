"""P62: reported capture losses must not disappear from PCAPNG research."""
from __future__ import annotations
import struct
import tempfile
import unittest
from pathlib import Path
from tests.capture_fixtures import block, packet, pcapng
from anka_capture.api import CaptureRejected, inspect_pcapng
from anka_capture.pcapng import pcapng_packet_count, read_pcapng_tcp_segments
from anka_app.capture_loss_smoke import capture_loss_metadata_smoke


def option(code: int, value: bytes, endian: str='<') -> bytes:
    return struct.pack(endian+'HH',code,len(value))+value+b'\x00'*((-len(value))%4)


def epb(frame: bytes, *, options: bytes=b'', endian: str='<', iid: int=0) -> bytes:
    return block(6,struct.pack(endian+'IIIII',iid,0,0,len(frame),len(frame))+frame+
                 b'\x00'*((-len(frame))%4)+options,endian)


def fixture(*blocks: bytes, endian: str='<', extra_idb: bool=False) -> bytes:
    prefix=pcapng(endian=endian)
    if extra_idb:
        prefix += block(1,struct.pack(endian+'HHI',1,0,65535),endian)
    return prefix+b''.join(blocks)


def isb(*, options: bytes=b'', endian: str='<', iid: int=0) -> bytes:
    return block(5,struct.pack(endian+'III',iid,0,0)+options,endian)


def old_pb(*,drops: int=0, endian: str='<') -> bytes:
    frame=packet()
    return block(2,struct.pack(endian+'HHIIII',0,drops,0,0,len(frame),len(frame))+frame,endian)


class TestP62CaptureLossMetadata(unittest.TestCase):
    def _run(self, data: bytes):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'synthetic.pcapng'; path.write_bytes(data)
            return inspect_pcapng(path,server_ports=(40400,))

    def test_preflight_smoke(self):
        result=capture_loss_metadata_smoke()
        self.assertEqual(result['status'],'PASS_REPORTED_CAPTURE_LOSS_QUARANTINED')
        self.assertEqual(result['canonical_commits'],0)

    def test_epb_positive_loss_rejected_even_if_other_packets_coherent(self):
        data=fixture(epb(packet(),options=option(4,struct.pack('<Q',2))))
        with self.assertRaisesRegex(CaptureRejected,'CAPTURE_CONTENT_INVALID'):self._run(data)

    def test_epb_positive_loss_after_valid_packet_rejected(self):
        data=fixture(epb(packet()),epb(packet(seq=104),options=option(4,struct.pack('<Q',1))))
        with self.assertRaises(CaptureRejected):self._run(data)

    def test_interface_drop_and_os_drop_rejected_even_at_end(self):
        for code in (5,7):
            with self.subTest(code=code):
                data=fixture(epb(packet()),isb(options=option(code,struct.pack('<Q',3))))
                with self.assertRaises(CaptureRejected):self._run(data)

    def test_legacy_packet_block_drop_rejected(self):
        with self.assertRaises(CaptureRejected):self._run(fixture(old_pb(drops=5)))

    def test_big_endian_all_three(self):
        for kind in ('epb','isb','pb'):
            with self.subTest(kind=kind):
                if kind=='epb': v=epb(packet(),endian='>',options=option(4,struct.pack('>Q',2),'>'))
                elif kind=='isb':v=epb(packet(),endian='>')+isb(endian='>',options=option(7,struct.pack('>Q',1),'>'))
                else:v=old_pb(drops=4,endian='>')
                with self.assertRaises(CaptureRejected):self._run(fixture(v,endian='>'))

    def test_loss_on_other_interface_still_blocks_unsound_completeness(self):
        data=fixture(epb(packet()),isb(iid=1,options=option(5,struct.pack('<Q',1))),extra_idb=True)
        with self.assertRaises(CaptureRejected):self._run(data)

    def test_missing_statistics_and_explicit_zero_do_not_claim_authority(self):
        for data in (fixture(epb(packet())),
                     fixture(epb(packet(),options=option(4,struct.pack('<Q',0)))),
                     fixture(epb(packet()),isb(options=option(5,struct.pack('<Q',0))+option(7,struct.pack('<Q',0)))),
                     fixture(old_pb(drops=0xffff))):
            with self.subTest(length=len(data)):
                result=self._run(data)
                self.assertEqual(result.selected_segments,1)
                self.assertFalse(result.protocol_decoded)

    def test_unknown_options_ignored_if_well_formed(self):
        data=fixture(epb(packet(),options=option(100,b'abc')+option(4,struct.pack('<Q',0))))
        self.assertEqual(self._run(data).selected_segments,1)

    def test_malformed_loss_option_length_rejected(self):
        for code,value in ((4,b'\0'*4),(4,b'\0'*12)):
            with self.subTest(code=code):
                with self.assertRaises(CaptureRejected):
                    self._run(fixture(epb(packet(),options=option(code,value))))
        with self.assertRaises(CaptureRejected):
            self._run(fixture(epb(packet()),isb(options=option(5,b'\0'*4))))

    def test_duplicate_loss_metadata_rejected(self):
        bad=option(4,struct.pack('<Q',0))*2
        with self.assertRaises(CaptureRejected):self._run(fixture(epb(packet(),options=bad)))

    def test_malformed_option_overrun_rejected(self):
        data=fixture(epb(packet(),options=struct.pack('<HH',4,32)+b'\0'*4))
        with self.assertRaises(CaptureRejected):self._run(data)

    def test_invalid_interface_statistics_identity_rejected(self):
        with self.assertRaises(CaptureRejected):
            self._run(fixture(epb(packet()),isb(iid=99,options=option(5,struct.pack('<Q',0)))))

    def test_trailing_end_marker_malformed_rejected(self):
        data=fixture(epb(packet(),options=struct.pack('<HH',0,4)+b'\0'*4))
        with self.assertRaises(CaptureRejected):self._run(data)

    def test_multisection_statistics_scoped(self):
        data=fixture(epb(packet()))+fixture(epb(packet()),isb(options=option(5,struct.pack('<Q',1))))
        with self.assertRaises(CaptureRejected):self._run(data)

    def test_packet_count_metadata_rejection_consistent(self):
        data=fixture(epb(packet()),isb(options=option(7,struct.pack('<Q',1))))
        with self.assertRaises(ValueError):pcapng_packet_count('ignored',raw=data)
        with self.assertRaises(ValueError):read_pcapng_tcp_segments('ignored',raw=data,server_ports={40400})

    def test_no_loss_packet_count(self):
        data=fixture(epb(packet()),isb(options=option(5,struct.pack('<Q',0))))
        self.assertEqual(pcapng_packet_count('ignored',raw=data),1)

if __name__=='__main__': unittest.main()
