"""Independent negative/positive wire-format oracles; all captures are synthetic."""
import unittest
from anka_protocol.wire import FrameBuffer, WireRejected, extract_any,parse_fields,varint,MAX_FRAME,MAX_FRAMES_PER_FEED


def v(n):
    data=[]
    while n>=128:data.append((n&127)|128);n>>=7
    data.append(n)
    return bytes(data)

def pfield(n,b):return v((n<<3)|2)+v(len(b))+b

def any_body(name='jsq',payload=b'\x08\x01'):
    return pfield(1,b'type.ankama.com/'+name.encode())+pfield(2,payload)

def framed(body):return v(len(body))+body


class TestWire(unittest.TestCase):
    def test_split_length_and_payload(self):
        f=FrameBuffer();data=framed(any_body());out=[]
        for b in data:out+=f.feed(bytes([b]))
        self.assertEqual(out,[any_body()]);self.assertEqual(bytes(f.buffer),b'')
    def test_multiple_consecutive_frames(self):
        frames=FrameBuffer().feed(framed(any_body())+framed(any_body('jtk')))
        self.assertEqual([extract_any(x)[0][0] for x in frames],['jsq','jtk'])
    def test_partial_frame_never_emitted(self):
        f=FrameBuffer();self.assertEqual(f.feed(framed(any_body())[:-1]),());self.assertTrue(f.buffer)
    def test_invalid_length_quarantines_and_cannot_resync(self):
        f=FrameBuffer()
        with self.assertRaisesRegex(WireRejected,'FRAME_LENGTH_INVALID'):f.feed(b'\x00')
        with self.assertRaisesRegex(WireRejected,'FRAME_STREAM_QUARANTINED'):f.feed(framed(any_body()))
    def test_noncanonical_oversized_length_blocked(self):
        f=FrameBuffer()
        with self.assertRaises(WireRejected):f.feed(v(MAX_FRAME+1))
        self.assertTrue(f.failed)
    def test_invalid_buffer_size(self):
        with self.assertRaisesRegex(WireRejected,'FRAME_BUFFER_LIMIT'):FrameBuffer().feed(b'a'*(MAX_FRAME+15))
    def test_pathological_tiny_frame_fanout_is_bounded_and_quarantined(self):
        f=FrameBuffer();payload=(b'\x01x')*(MAX_FRAMES_PER_FEED+1)
        with self.assertRaisesRegex(WireRejected,'FRAME_COUNT_LIMIT'):f.feed(payload)
        self.assertTrue(f.failed);self.assertEqual(bytes(f.buffer),b'')

    def test_field_key_zero(self):
        with self.assertRaisesRegex(WireRejected,'FIELD_KEY'):parse_fields(b'\x00')
    def test_truncated_fixed_width(self):
        with self.assertRaisesRegex(WireRejected,'TRUNCATED_FIXED'):parse_fields(b'\x09\x00')
    def test_bad_varint_never_loops(self):
        with self.assertRaises(WireRejected):varint(b'\x80'*11)
    def test_missing_any_body(self):
        with self.assertRaisesRegex(WireRejected,'ANY_VALUE_ABSENT'):extract_any(pfield(1,b'type.ankama.com/jsq'))
    def test_invalid_any_name(self):
        with self.assertRaisesRegex(WireRejected,'ANY_NAME_INVALID'):extract_any(any_body('../../invalid'))
    def test_nested_envelope(self):
        self.assertEqual(extract_any(pfield(4,any_body())),(('jsq',b'\x08\x01'),))
    def test_unrelated_binary_submessage_is_skipped(self):
        self.assertEqual(extract_any(pfield(3,b'\xff\xff\xff')+any_body()),(('jsq',b'\x08\x01'),))
    def test_preserve_repeated_nested_any(self):
        self.assertEqual(extract_any(pfield(3,any_body())+pfield(4,any_body())),(('jsq',b'\x08\x01'),('jsq',b'\x08\x01')))
    def test_never_guess_semantics(self):
        self.assertEqual(extract_any(any_body('unknown_wire')),(('unknown_wire',b'\x08\x01'),))

if __name__=='__main__':unittest.main()
