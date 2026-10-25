"""P6 protocol observation facade: no Canonical writes, no input, no shared decoder context.

Capture evidence is *not* trusted merely because parsing succeeds. Safety authority
remains disabled until exact-build semantics, account attribution and end-to-end
consumer state replay have separate certification.
"""
from __future__ import annotations
from dataclasses import dataclass,field
from pathlib import Path
from collections import Counter
from threading import RLock
from anka_contracts.capture import CapturedTcpSegment, CapturePoll
from anka_contracts.protocol import ProtocolReceipt, ProtocolFinding, WireMessage
from anka_protocol.wire import FrameBuffer, extract_any, WireRejected
from anka_protocol.adapters.historical import HistoricalCatalog,load_reference

MAX_STREAMS=64
MAX_CAPTURE_SEGMENTS=100_000
MAX_FINDINGS=120

@dataclass(slots=True)
class _Stream:
    anchored:bool=False
    seq:int|None=None
    previous:tuple[int,bytes]|None=field(default=None,repr=False)
    frames:FrameBuffer=field(default_factory=FrameBuffer)
    invalid:bool=False
    generation:int=0


class ProtocolInspector:
    """Admission and observation only; never a live semantic adapter."""
    def __init__(self,catalog:HistoricalCatalog,*,requested_build:str,observer=None,on_message=None):
        if not isinstance(requested_build,str) or not requested_build.strip() or len(requested_build)>80:
            raise ValueError('PROTOCOL_BUILD_REQUIRED')
        self.catalog=catalog
        self.build=requested_build.strip()
        self.observer=observer
        self.on_message=on_message
        self.streams:dict[tuple[str,str],_Stream]={}
        self.selected=0;self.messages=0;self.counts=Counter()
        self.violations=0;self.quarantined=0;self.unanchored=0
        self.loss=False;self.source_generation:str|None=None;self.findings:list[ProtocolFinding]=[]
        self._quarantined_keys:set[tuple[str,str,int]]=set()
        self._unanchored_keys:set[tuple[str,str]]=set()
        self._lock=RLock()
        self._finished_receipt:ProtocolReceipt|None=None

    def _bad(self,key:tuple[str,str],s:_Stream,code:str)->None:
        if not s.invalid:
            s.invalid=True
            self._quarantined_keys.add((key[0],key[1],s.generation))
            self.quarantined+=1;self.violations+=1
        self.counts[code]+=1
        if self.observer is not None:
            try:
                self.observer.record('protocol.stream_quarantined',severity='WARNING',boundary='protocol.transport_to_wire',
                  failure_code=code,payload={'packet_count':self.selected,'quarantined_stream_generations':self.quarantined})
            except Exception:
                # Diagnostics are best-effort evidence. A broken sink must never
                # turn an already-quarantined wire stream into a different
                # Protocol/Capture failure or change admission authority.
                pass

    def consume(self,segment:CapturedTcpSegment)->None:
        with self._lock:
            if self._finished_receipt is not None:raise RuntimeError('PROTOCOL_INSPECTOR_FINISHED')
            return self._consume_unlocked(segment)

    def _consume_unlocked(self,segment:CapturedTcpSegment)->None:
        if self.selected>=MAX_CAPTURE_SEGMENTS:raise ValueError('PROTOCOL_SEGMENT_LIMIT')
        self.selected+=1
        key=(segment.flow_id,segment.direction)
        if key not in self.streams and len(self.streams)>=MAX_STREAMS:
            raise ValueError('PROTOCOL_FLOW_LIMIT')
        stream=self.streams.setdefault(key,_Stream())
        if segment.syn:
            # A new TCP generation does not silently erase incomplete framing.
            if stream.anchored and stream.frames.buffer and not stream.invalid:
                self._bad(key,stream,'INCOMPLETE_FRAME_BEFORE_RECONNECT')
            # New TCP generation never repairs a prior quarantined generation.
            stream.generation+=1
            stream.anchored=True;stream.invalid=False;stream.seq=(segment.seq+1)%2**32
            stream.previous=None;stream.frames=FrameBuffer()
        if not stream.anchored:
            self._unanchored_keys.add(key)
            self.unanchored=len(self._unanchored_keys)
            return
        if stream.invalid:return
        if segment.rst:
            self._bad(key,stream,'TCP_RESET');return
        if not segment.payload:
            if segment.fin:
                if stream.frames.buffer:self._bad(key,stream,'INCOMPLETE_FRAME_AT_FIN')
                stream.anchored=False
            return
        seq=segment.seq+(1 if segment.syn else 0)
        seq%=2**32
        if seq!=stream.seq:
            if stream.previous==(seq,segment.payload):
                self.counts['RETRANSMISSION_IDENTICAL']+=1
                return
            self._bad(key,stream,'TCP_GAP_OR_UNVERIFIED_OVERLAP')
            return
        stream.seq=(seq+len(segment.payload))%2**32
        stream.previous=(seq,segment.payload)
        try:
            # A provenance selector is (flow, generation, capture packet, message_index).
            # This ordinal belongs to the capture packet that COMPLETED the frame;
            # it must not depend on messages observed on another TCP connection.
            # self.messages remains the aggregate count for reporting/limits.
            packet_message_index = 0
            frames=stream.frames.feed(segment.payload)
            for frame in frames:
                pairs=extract_any(frame)
                if not pairs:
                    self.counts['FRAME_WITHOUT_RECOGNIZED_ENVELOPE']+=1
                    continue
                for name,body in pairs:
                    msg=WireMessage(segment.direction,name,body,segment.packet_number,segment.flow_id,
                                    stream.generation,packet_message_index)
                    packet_message_index += 1
                    finding=self.catalog.classify(msg)
                    self.messages+=1
                    if self.on_message is not None:
                        try:self.on_message(msg)
                        except Exception:
                            self._bad(key,stream,'MESSAGE_OBSERVER_FAILED')
                            return
                    self.counts[finding.category]+=1
                    if len(self.findings)<MAX_FINDINGS:self.findings.append(finding)
        except WireRejected:
            self._bad(key,stream,'WIRE_FRAME_MALFORMED')
        if segment.fin:
            if stream.frames.buffer:self._bad(key,stream,'INCOMPLETE_FRAME_AT_FIN')
            stream.anchored=False

    def consume_poll(self,poll:CapturePoll)->None:
        with self._lock:
            if self._finished_receipt is not None:raise RuntimeError('PROTOCOL_INSPECTOR_FINISHED')
            return self._consume_poll_unlocked(poll)

    def _consume_poll_unlocked(self,poll:CapturePoll)->None:
        if self.source_generation is None:
            self.source_generation=poll.source_generation
        elif poll.source_generation!=self.source_generation:
            # A restarted capture invalidates existing transport continuity.
            for key,stream in self.streams.items():
                if stream.anchored and not stream.invalid:
                    self._bad(key,stream,'CAPTURE_SOURCE_CHANGED')
            self.streams.clear()
            self.loss=True
            self.counts['CAPTURE_SOURCE_GENERATION_CHANGED']+=1
            self.source_generation=poll.source_generation
        if poll.dropped or poll.overflowed or poll.driver_drop_visibility!='AVAILABLE_CLEAN':
            self.loss=True
            self.counts['CAPTURE_LOSS_OR_INCOMPLETE_VISIBILITY']+=1
        for segment in poll.segments:self.consume(segment)

    def finish(self)->ProtocolReceipt:
        # finish reads and may quarantine mutable stream state. Serialize it with
        # consume/consume_poll so a diagnostic or future caller cannot finalize a
        # half-mutated transport generation.
        with self._lock:
            if self._finished_receipt is not None:
                return self._finished_receipt
            # Partial frames at capture end are not treated as complete messages.
            for key,s in self.streams.items():
                if s.anchored and s.frames.buffer and not s.invalid:
                    self._bad(key,s,'INCOMPLETE_FRAME_AT_CAPTURE_END')
            matched=self.build==self.catalog.protocol_build
            if not matched:status='UNSUPPORTED_BUILD_OBSERVATION_ONLY'
            elif self.loss or self.quarantined or self.unanchored:status='INCOMPLETE_EVIDENCE_OBSERVATION_ONLY'
            elif self.catalog.evidence_source=='P30_LOCAL_RESEARCH_RECIPE_ONLY':status='RESEARCH_WIRE_OBSERVATION_ONLY'
            else:status='HISTORICAL_WIRE_OBSERVATION_ONLY'
            report=ProtocolReceipt(1,self.catalog.adapter_id,self.build,self.catalog.protocol_build,
                status,self.selected,self.messages,self.counts['CATALOG_OBSERVED_ONLY'],
                self.counts['UNKNOWN_WIRE'],self.counts['DIRECTION_MISMATCH'],
                self.violations,self.quarantined,self.unanchored,self.loss,findings=tuple(self.findings))
            if self.observer is not None:
                try:
                    self.observer.record('protocol.inspection_completed',boundary='protocol.read_only_classification',
                      payload={'status':report.status,'selected_segments':report.selected_segments,'framed_messages':report.framed_messages,
                               'unknown':report.unknown_messages,'direction_mismatches':report.direction_mismatches,
                               'invalid_frames':report.invalid_frames,'canonical_events_emitted':0,'gameplay_capabilities_certified':False})
                except Exception:
                    # Finalization is a Protocol state boundary, not a diagnostic
                    # sink transaction. Preserve the immutable receipt.
                    pass
            self._finished_receipt=report
            return report


def synthetic_wire_demo(*,root:Path,observer=None)->dict:
    """Generate a wire-shape demonstration, not an observed Dofus semantic fixture."""
    from anka_protocol.wire import FrameBuffer
    def var(v):
        out=[]
        while v>=128:out.append((v&127)|128);v>>=7
        out.append(v);return bytes(out)
    def field(n,val):return var((n<<3)|2)+var(len(val))+val
    envelope=field(1,b'type.ankama.com/jsq')+field(2,b'\x08\x01')
    encoded=var(len(envelope))+envelope
    decoder=FrameBuffer()
    frames=decoder.feed(encoded[:5])+decoder.feed(encoded[5:])
    inspector=ProtocolInspector(load_reference(root),requested_build='Dofus 3.7.10.10',observer=observer)
    from anka_protocol.wire import extract_any
    messages=[name for frame in frames for name,_ in extract_any(frame)]
    # Intentionally separate wire framing demo from real TCP capture assurance.
    return {'operation':'protocol-demo','status':'SYNTHETIC_WIRE_ONLY','framed_messages':len(frames),
      'observed_names':messages,'historical_catalog_keys':len(inspector.catalog.known_keys),
      'canonical_events_emitted':0,'gameplay_capabilities_certified':False,'live_ready':False,'physical_input_sent':False}
