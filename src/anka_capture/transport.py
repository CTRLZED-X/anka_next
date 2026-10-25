"""Read-only TCP transport audit. Never accepts a missing stream as complete.

A TCP sequence number alone is not sufficient to prove a contiguous byte stream.
Our P4 receipt deliberately refuses 'fully verified' without a witnessed SYN
and a complete, gap-free capture in both directions. P5 will own framing.
"""
from __future__ import annotations
from dataclasses import dataclass
from threading import RLock

from anka_contracts.capture import CapturedTcpSegment
from anka_capture.overlap import MATCH, RecentByteProof


@dataclass(frozen=True, slots=True)
class TransportHealth:
    status: str
    flows: int
    unanchored_directions: int
    unresolved_gap_directions: int
    reconnects: int
    duplicates: int
    reordered_segments: int
    selected_payload_bytes: int
    # Do not serialize network endpoints, IPs, flow identifiers or raw payload.


class _Direction:
    __slots__ = ('anchored','expected','pending','duplicates','reorders','has_gaps','finished','syn_seq','overlap_proof')

    def __init__(self):
        self.anchored = False
        self.expected: int | None = None
        self.pending: list[tuple[int,int]] = []
        self.duplicates = 0
        self.reorders = 0
        self.has_gaps = False
        self.finished = False
        self.syn_seq: int | None = None
        self.overlap_proof = RecentByteProof()

    def feed(self, segment: CapturedTcpSegment) -> None:
        if self.finished:
            # Payload after FIN/RST might be a reused tuple. Without a new SYN,
            # never certify this flow generation as continuous.
            self.has_gaps = True
        if segment.syn:
            self.syn_seq = segment.seq
            self.anchored = True
            self.expected = (segment.seq + 1) % 2**32
            self.pending.clear()
            self.has_gaps = False
            self.finished = False
            self.overlap_proof.clear()
        if segment.rst or segment.fin:
            self.finished = True
        if not segment.payload:
            return
        seq = segment.seq + (1 if segment.syn else 0)
        if seq >= 2**32 or seq + len(segment.payload) > 2**32:
            # This metadata auditor deliberately does not model wraparound.
            self.has_gaps = True
            return
        payload = segment.payload
        end = seq + len(payload)
        if self.expected is None:
            self.expected = seq
        if seq < self.expected:
            overlap_end = min(end,self.expected)
            verdict = self.overlap_proof.compare(seq,payload,overlap_end)
            if verdict != MATCH:
                self.has_gaps = True
            if end <= self.expected:
                if verdict == MATCH:
                    self.duplicates += 1
                return
            payload = payload[self.expected-seq:]
            seq = self.expected
            end = seq + len(payload)
        if seq > self.expected:
            self.reorders += 1
            self.pending.append((seq,end))
            self.pending.sort()
            if len(self.pending) > 4096:
                self.has_gaps = True
                self.pending.clear()
            return
        self.expected = end
        self.overlap_proof.remember(seq,payload)
        while self.pending and self.pending[0][0] <= self.expected:
            start, stop = self.pending.pop(0)
            if start < self.expected:
                # Pending metadata deliberately does not retain payload bytes.
                # Any overlap can therefore no longer be proved identical.
                self.has_gaps = True
            if stop > self.expected:
                self.expected = stop
                # The accepted pending range has no retained byte proof.
                self.overlap_proof.clear()

    def gap(self) -> bool:
        return self.has_gaps or bool(self.pending)


class TransportAuditor:
    def audit(self, segments: tuple[CapturedTcpSegment, ...]) -> TransportHealth:
        directions: dict[tuple[str,str], _Direction] = {}
        generations: list[_Direction] = []
        flows: set[str] = set()
        reconnects = 0
        payload_bytes = 0
        previous_packet = 0
        for seg in segments:
            if seg.packet_number <= previous_packet:
                raise ValueError('CAPTURE_PACKET_ORDER_INVALID')
            previous_packet = seg.packet_number
            flows.add(seg.flow_id)
            key = (seg.flow_id,seg.direction)
            if key not in directions:
                directions[key] = _Direction()
                generations.append(directions[key])
            current = directions[key]
            if seg.syn and current.anchored and current.syn_seq != seg.seq:
                reconnects += 1
                # Audit the previous generation too; a later clean connection
                # must NOT erase unresolved gaps from the earlier one.
                current = directions[key] = _Direction()
                generations.append(current)
            elif seg.syn and current.anchored and current.syn_seq == seg.seq:
                # Exact SYN retransmission before useful traffic does not start
                # a new connection generation.
                current.duplicates += 1
                continue
            current.feed(seg)
            payload_bytes += len(seg.payload)
        gaps = sum(s.gap() for s in generations)
        unanchored = sum(not s.anchored for s in generations)
        # Missing an initial SYN (common in truncated captures) is *not* a
        # proven transport failure; it is missing evidence.
        status = ('NO_SELECTED_TRAFFIC' if not segments else
                  'TRANSPORT_UNCERTAIN' if gaps or unanchored else
                  'OBSERVED_NO_DETECTED_GAPS')
        return TransportHealth(status,len(flows),unanchored,gaps,reconnects,
                               sum(s.duplicates for s in generations),
                               sum(s.reorders for s in generations),payload_bytes)


class IncrementalTransportAuditor:
    """Bounded live transport auditor over multiple polls.

    It retains at most the small RecentByteProof suffix per active direction so
    exact retransmission equality can be proved. Payload is never serialized or
    exposed in the report. A gap in an old generation cannot disappear later.
    """
    def __init__(self, *, max_directions: int = 8192):
        self.max_directions=max_directions
        self._directions: dict[tuple[str,str],_Direction]={}
        self._generations: list[_Direction]=[]
        self._max_reached=False
        self._last_packet=0
        self._reconnects=0
        self._unorderable=False
        self._lock=RLock()

    def feed(self, segment:CapturedTcpSegment)->None:
        with self._lock:return self._feed_unlocked(segment)

    def _feed_unlocked(self, segment:CapturedTcpSegment)->None:
        if segment.packet_number <= self._last_packet:
            self._unorderable=True
        self._last_packet=max(self._last_packet, segment.packet_number)
        key=(segment.flow_id,segment.direction)
        if key not in self._directions:
            if len(self._directions)>=self.max_directions:
                self._max_reached=True
                return
            self._directions[key]=_Direction()
            self._generations.append(self._directions[key])
        current=self._directions[key]
        if segment.syn and current.anchored and current.syn_seq != segment.seq:
            if len(self._generations)>=self.max_directions:
                self._max_reached=True
                return
            self._reconnects+=1
            current=self._directions[key]=_Direction()
            self._generations.append(current)
        elif segment.syn and current.anchored and current.syn_seq==segment.seq:
            current.duplicates+=1
            return
        current.feed(segment)

    def report(self)->dict:
        with self._lock:return self._report_unlocked()

    def _report_unlocked(self)->dict:
        return {'unanchored_directions':sum(not s.anchored for s in self._generations),
                'unresolved_gap_directions':sum(s.gap() for s in self._generations),
                'reconnections':self._reconnects,
                'duplicate_segments':sum(s.duplicates for s in self._generations),
                'reordered_segments':sum(s.reorders for s in self._generations),
                'metadata_limit_reached':self._max_reached,
                'packet_order_uncertain':self._unorderable,
                'observed_generations':len(self._generations)}
