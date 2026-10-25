"""Bounded, defensive protobuf framing and Ankama Any-envelope discovery.

Adapted from R5.198's pure `protocol/protobuf.py`, `capture/framing.py`,
`capture/envelope.py`; deliberately no imports from the old project. This is
wire-format inspection only, NOT a verified game-state decoder.
"""
from __future__ import annotations
import re

MAX_FRAME=2_000_000
MAX_BUFFER=2_000_010
MAX_FIELDS=4096
MAX_DEPTH=6
MAX_MESSAGES=256
MAX_FRAMES_PER_FEED=4096
PREFIX=b'type.ankama.com/'
NAME=re.compile(rb'[A-Za-z0-9_]{1,96}\Z')

class WireRejected(ValueError):
    pass


def varint(buf:bytes|bytearray, pos:int=0)->tuple[int|None,int]:
    start=pos
    value=0
    for shift in range(0,70,7):
        if pos>=len(buf):return None,start
        c=buf[pos];pos+=1
        if shift==63 and c>1:raise WireRejected('VARINT_OVERFLOW')
        value|=(c&127)<<shift
        if not c&128:return value,pos
    raise WireRejected('VARINT_TOO_LONG')


def parse_fields(buf:bytes)->dict[int,list[int|bytes]]:
    if len(buf)>MAX_FRAME:raise WireRejected('PROTOBUF_TOO_LARGE')
    pos=0; fields={}; count=0
    while pos<len(buf):
        count+=1
        if count>MAX_FIELDS:raise WireRejected('PROTOBUF_FIELD_LIMIT')
        key,pos2=varint(buf,pos)
        if key is None or key==0:raise WireRejected('PROTOBUF_FIELD_KEY')
        pos=pos2
        number,kind=key>>3,key&7
        if not 0<number<2**29:raise WireRejected('PROTOBUF_FIELD_NUMBER')
        if kind==0:
            value,pos2=varint(buf,pos)
            if value is None:raise WireRejected('PROTOBUF_TRUNCATED_VARINT')
            pos=pos2
        elif kind in (1,5):
            size=8 if kind==1 else 4
            if pos+size>len(buf):raise WireRejected('PROTOBUF_TRUNCATED_FIXED')
            value=buf[pos:pos+size];pos+=size
        elif kind==2:
            size,pos2=varint(buf,pos)
            if size is None or size>MAX_FRAME or pos2+size>len(buf):raise WireRejected('PROTOBUF_INVALID_LENGTH')
            value=buf[pos2:pos2+size];pos=pos2+size
        else: raise WireRejected('PROTOBUF_UNSUPPORTED_WIRE_TYPE')
        fields.setdefault(number,[]).append(value)
    return fields


def extract_any(frame:bytes)->tuple[tuple[str,bytes],...]:
    """Identify Any messages from observed envelopes, bounded and deduplicated.

Nested protobuf messages that are not proto messages are ignored; malformed root
frames quarantine the stream (never silently resync and mutate gameplay state).
    """
    root=parse_fields(frame)
    found=[]; nodes=0
    def walk(fields:dict[int,list[int|bytes]],depth:int):
        nonlocal nodes
        nodes+=1
        if nodes>MAX_FIELDS:raise WireRejected('ANY_NODE_LIMIT')
        candidate=next((x for x in fields.get(1,()) if isinstance(x,bytes) and x.startswith(PREFIX)),None)
        if candidate is not None:
            token=candidate[len(PREFIX):]
            if not NAME.fullmatch(token):raise WireRejected('ANY_NAME_INVALID')
            vals=[x for x in fields.get(2,()) if isinstance(x,bytes)]
            if not vals:raise WireRejected('ANY_VALUE_ABSENT')
            for body in vals:
                # Preserve repeated occurrences. Deduplicating equivalent wire
                # bodies can discard two legitimate, separate server events.
                # Idempotency is enforced later using source identity/ordinal.
                if len(found)>=MAX_MESSAGES:raise WireRejected('ANY_MESSAGE_LIMIT')
                found.append((token.decode('ascii'),body))
        if depth>=MAX_DEPTH:return
        for contents in fields.values():
            for item in contents:
                if isinstance(item,bytes) and item and item[:1]!=b'\x00':
                    try:child=parse_fields(item)
                    except WireRejected:continue
                    walk(child,depth+1)
    walk(root,0)
    return tuple(found)


class FrameBuffer:
    def __init__(self):
        self.buffer=bytearray()
        self.failed=False

    def feed(self,data:bytes)->tuple[bytes,...]:
        if self.failed:raise WireRejected('FRAME_STREAM_QUARANTINED')
        if not isinstance(data,bytes):self.failed=True;raise WireRejected('FRAME_INPUT_INVALID')
        if len(data)+len(self.buffer)>MAX_BUFFER:
            self.failed=True;self.buffer.clear();raise WireRejected('FRAME_BUFFER_LIMIT')
        self.buffer.extend(data)
        frames=[]
        try:
            while self.buffer:
                length,pos=varint(self.buffer)
                if length is None:break
                if not 0<length<=MAX_FRAME:raise WireRejected('FRAME_LENGTH_INVALID')
                end=pos+length
                if end>len(self.buffer):break
                if len(frames)>=MAX_FRAMES_PER_FEED:
                    raise WireRejected('FRAME_COUNT_LIMIT')
                frames.append(bytes(self.buffer[pos:end]))
                del self.buffer[:end]
        except WireRejected:
            self.failed=True;self.buffer.clear();raise
        return tuple(frames)
