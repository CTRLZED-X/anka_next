import tempfile
import unittest
from pathlib import Path
from tests.capture_fixtures import pcapng,packet,sample_capture,block
from anka_capture.api import inspect_pcapng,CaptureRejected,MAX_CAPTURE_BYTES
from anka_capture.pcapng import read_pcapng_tcp_segments


class TestPcapngEvidence(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'capture.pcapng'
    def inspect(self, data:bytes, ports=(40400,)):
        self.path.write_bytes(data)
        return inspect_pcapng(self.path,server_ports=ports)
    def test_independent_synthetic_both_directions(self):
        receipt=self.inspect(sample_capture())
        self.assertEqual(receipt.status,'OBSERVED_NO_DETECTED_GAPS')
        self.assertEqual(receipt.packet_records,4)
        self.assertEqual(receipt.selected_segments,4)
        self.assertEqual(receipt.flows,1)
        self.assertFalse(receipt.protocol_decoded)
        self.assertFalse(receipt.physical_input_sent)
        self.assertEqual(receipt.unanchored_directions,0)
        self.assertNotIn('NOT_GAME',str(receipt.to_dict()))
        self.assertNotIn('192.0.2.',str(receipt.to_dict()))
    def test_server_port_selection_not_guessed(self):
        receipt=self.inspect(sample_capture(), ports=(40500,))
        self.assertEqual(receipt.status,'NO_SELECTED_TRAFFIC')
        self.assertEqual(receipt.selected_segments,0)
    def test_reject_unconfigured_or_duplicate_ports(self):
        self.path.write_bytes(sample_capture())
        for ports in ((),(40400,40400),(True,),(0,),(65536,)):
            with self.subTest(ports=ports),self.assertRaises(CaptureRejected):
                inspect_pcapng(self.path,server_ports=ports)
    def test_little_and_big_endian(self):
        for endian in ('<','>'):
            with self.subTest(endian=endian):
                receipt=self.inspect(pcapng(packet(flags=2,data=b''),endian=endian))
                self.assertEqual(receipt.selected_segments,1)
    def test_multisection_restarts_interface_index(self):
        first=pcapng(packet(flags=2,data=b''))
        second=pcapng(packet(flags=2,data=b''),endian='>')
        receipt=self.inspect(first+second)
        self.assertEqual(receipt.packet_records,2)
    def test_selected_vlan_support(self):
        receipt=self.inspect(pcapng(packet(flags=2,data=b'',vlan=1)))
        self.assertEqual(receipt.selected_segments,1)
    def test_truncated_packet_record_rejected(self):
        bad=sample_capture()[:-2]
        with self.assertRaisesRegex(CaptureRejected,'CAPTURE_CONTENT_INVALID'):self.inspect(bad)
    def test_length_trailer_mismatch_rejected(self):
        raw=bytearray(sample_capture());raw[-1]=3
        with self.assertRaisesRegex(CaptureRejected,'CAPTURE_CONTENT_INVALID'):self.inspect(bytes(raw))
    def test_snaplen_truncation_not_silent(self):
        import struct
        raw=bytearray(pcapng(packet()))
        epb_offset=len(pcapng())
        # builder pcapng() ends after the interface block
        struct.pack_into('<I',raw,epb_offset+8+16,999)
        with self.assertRaisesRegex(CaptureRejected,'CAPTURE_CONTENT_INVALID'):self.inspect(bytes(raw))
    def test_unknown_linktype_rejected(self):
        with self.assertRaisesRegex(CaptureRejected,'CAPTURE_CONTENT_INVALID'):
            self.inspect(pcapng(packet(),linktype=113))
    def test_unsupported_raw_pcap(self):
        with self.assertRaisesRegex(CaptureRejected,'CAPTURE_FORMAT_NOT_PCAPNG'):
            self.inspect(b'\xd4\xc3\xb2\xa1'+b'\x00'*40)
    def test_missing_file_no_path_exposure(self):
        with self.assertRaisesRegex(CaptureRejected,'CAPTURE_FILE_UNREADABLE'):
            inspect_pcapng(self.path,server_ports=(40400,))
    def test_size_cap(self):
        self.path.write_bytes(b'\0'*(MAX_CAPTURE_BYTES+1))
        with self.assertRaisesRegex(CaptureRejected,'CAPTURE_FILE_SIZE_UNSUPPORTED'):
            inspect_pcapng(self.path,server_ports=(40400,))
    def test_fragmented_selected_packet_rejected(self):
        raw=bytearray(packet());raw[14+6]=0x20
        with self.assertRaisesRegex(CaptureRejected,'CAPTURE_CONTENT_INVALID'):
            self.inspect(pcapng(bytes(raw)))

class TestMalformedEvidence(unittest.TestCase):
    def test_mutations_do_not_crash_with_unclassified_exception(self):
        # A corrupted packet can legitimately parse as some other *valid* data.
        # Either valid metadata or an explicit rejection is acceptable; raw
        # IndexError/struct.error/EOFError must never reach an operator.
        baseline=sample_capture()
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'mutated.pcapng'
            for pos in range(0,len(baseline),max(1,len(baseline)//40)):
                altered=bytearray(baseline);altered[pos] ^= 0xff
                p.write_bytes(altered)
                try:inspect_pcapng(p,server_ports=(40400,))
                except CaptureRejected:pass
    def test_truncated_ethernet_fails_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'tiny.pcapng'
            p.write_bytes(pcapng(b'\x00'*8))
            with self.assertRaisesRegex(CaptureRejected,'CAPTURE_CONTENT_INVALID'):
                inspect_pcapng(p,server_ports=(40400,))
