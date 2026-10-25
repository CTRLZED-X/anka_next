"""P5 bounded, read-only live transport ingress. No game/protocol imports.

Only metadata is reportable. Payload remains in an in-memory bounded queue for
future authorized consumers; it is NEVER written to diagnostic artifacts.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from threading import Condition
from time import monotonic
from anka_contracts.capture import CapturedTcpSegment, CapturePoll
from anka_capture.transport import IncrementalTransportAuditor


@dataclass(frozen=True, slots=True)
class LiveQueueStats:
    capacity_segments: int
    capacity_bytes: int
    queued_segments: int
    queued_bytes: int
    accepted_total: int
    dropped_total: int
    invalid_total: int
    source_closed: bool


class BoundedSegmentQueue:
    def __init__(self, *, source_generation: str, max_segments: int = 1024, max_bytes: int = 4*1024*1024):
        if not source_generation or not (1 <= max_segments <= 4096) or not (1 <= max_bytes <= 16*1024*1024):
            raise ValueError('CAPTURE_QUEUE_LIMIT_INVALID')
        self._generation=source_generation
        self._max_segments=max_segments
        self._max_bytes=max_bytes
        self._queue:deque[CapturedTcpSegment]=deque()
        self._bytes=0
        self._accepted=0
        self._dropped=0
        self._unreported_drops=0
        self._invalid=0
        self._closed=False
        self._cv=Condition()

    def push(self, item: CapturedTcpSegment) -> bool:
        if not isinstance(item,CapturedTcpSegment):
            with self._cv:self._invalid+=1;self._dropped+=1;self._unreported_drops+=1
            return False
        with self._cv:
            if self._closed or len(self._queue)>=self._max_segments or self._bytes+len(item.payload)>self._max_bytes:
                self._dropped+=1;self._unreported_drops+=1
                self._cv.notify_all()
                return False
            self._queue.append(item)
            self._bytes+=len(item.payload)
            self._accepted+=1
            self._cv.notify_all()
            return True

    def poll(self, *, max_segments: int, timeout_seconds: float) -> CapturePoll:
        if type(max_segments) is not int or not (1<=max_segments<=4096) or not (isinstance(timeout_seconds,(int,float)) and 0<=timeout_seconds<=10):
            raise ValueError('CAPTURE_POLL_ARGUMENT_INVALID')
        deadline=monotonic()+timeout_seconds
        with self._cv:
            while not self._queue and not self._closed and self._unreported_drops==0:
                delay=deadline-monotonic()
                if delay<=0:break
                self._cv.wait(delay)
            chosen=[]
            while self._queue and len(chosen)<max_segments:
                item=self._queue.popleft()
                self._bytes-=len(item.payload)
                chosen.append(item)
            drops=self._unreported_drops
            self._unreported_drops=0
            # Driver statistics are not offered through Scapy's AsyncSniffer;
            # even zero queue drops MUST NOT be interpreted as lossless evidence.
            return CapturePoll(self._generation,tuple(chosen),drops,drops>0,
                               self._closed and not self._queue, 'UNKNOWN')

    def close(self) -> None:
        with self._cv:self._closed=True;self._cv.notify_all()

    def stats(self) -> LiveQueueStats:
        with self._cv:
            return LiveQueueStats(self._max_segments,self._max_bytes,len(self._queue),self._bytes,
                                  self._accepted,self._dropped,self._invalid,self._closed)


class LiveCaptureAudit:
    """Aggregate poll losses across the ENTIRE generation; never erase on reconnect."""
    def __init__(self):
        self._generation=None
        self.total_segments=0
        self.total_payload_bytes=0
        self.total_queue_drops=0
        self.polls=0
        self.driver_drop_visibility=None
        self.closed=False
        self.transport=IncrementalTransportAuditor()

    def observe(self,poll:CapturePoll)->None:
        if not isinstance(poll,CapturePoll):raise ValueError('CAPTURE_POLL_REQUIRED')
        if self._generation is None:self._generation=poll.source_generation
        elif self._generation!=poll.source_generation:raise ValueError('CAPTURE_GENERATION_CHANGED')
        if self.closed:raise ValueError('CAPTURE_AFTER_EXHAUSTION')
        self.polls+=1
        for segment in poll.segments:self.transport.feed(segment)
        self.total_segments+=len(poll.segments)
        self.total_payload_bytes+=sum(len(s.payload) for s in poll.segments)
        self.total_queue_drops+=poll.dropped
        # Aggregate the strongest loss evidence without making UNKNOWN sticky
        # before the first poll. This keeps today's Scapy backend UNKNOWN while
        # allowing a future backend with real driver counters to prove that every
        # observed poll was AVAILABLE_CLEAN. Any unknown/dropped poll dominates.
        if self.driver_drop_visibility is None:
            self.driver_drop_visibility=poll.driver_drop_visibility
        elif poll.driver_drop_visibility=='AVAILABLE_DROPPED':
            self.driver_drop_visibility='AVAILABLE_DROPPED'
        elif poll.driver_drop_visibility=='UNKNOWN' and self.driver_drop_visibility!='AVAILABLE_DROPPED':
            self.driver_drop_visibility='UNKNOWN'
        self.closed=poll.exhausted

    def receipt(self)->dict:
        # This receipt intentionally cannot certify stream completeness, even
        # if queue drops are zero: startup SYN, offloads, and driver drops may
        # be missing. Endpoints, flow IDs and payloads are omitted.
        tr=self.transport.report()
        uncertain=tr['unanchored_directions'] or tr['unresolved_gap_directions'] or tr['metadata_limit_reached'] or tr['packet_order_uncertain']
        return {'status':'LOSS_DETECTED' if self.total_queue_drops else 'TRANSPORT_UNCERTAIN' if uncertain else 'UNCERTIFIED',
                'polls':self.polls,'selected_segments':self.total_segments,
                'selected_payload_bytes':self.total_payload_bytes,
                'queue_dropped':self.total_queue_drops,
                'driver_drop_visibility':self.driver_drop_visibility or 'UNKNOWN',
                'source_exhausted':self.closed,
                'transport':tr,
                'account_binding_verified':False,'protocol_decoded':False,
                'physical_input_sent':False}
