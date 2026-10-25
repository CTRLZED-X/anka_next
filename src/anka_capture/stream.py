"""Definitive M4 ordered transport-envelope assembler.

This is deliberately transport-only. It knows TCP sequence continuity and exact
flow→client binding supplied by the composition root, but no Dofus message names,
opcodes, fields, actors, fights or semantic events.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Mapping
from threading import RLock
from anka_contracts.capture import CapturedTcpSegment, CaptureHealthSnapshot, CapturePoll
from anka_contracts.wire import WireEnvelope

_MOD=2**32

@dataclass
class _Dir:
    syn_seq:int|None=None
    expected:int|None=None
    stream_offset:int=0
    pending:list[CapturedTcpSegment]=field(default_factory=list)
    emitted:int=0
    duplicates:int=0
    reordered:int=0
    unresolved_gaps:int=0
    loss_epoch_seen:int=0
    reconnected_pending:bool=False
    fin_seq:int|None=None

@dataclass
class _Flow:
    generation:int=1
    dirs:dict[str,_Dir]=field(default_factory=dict)
    active:bool=False
    reset_seen:bool=False

class TransportEnvelopeAssembler:
    def __init__(self, *, capture_session_id:str, flow_clients:Mapping[str,str], max_pending_segments:int=1024):
        if not capture_session_id.startswith('capture-'): raise ValueError('INVALID_CAPTURE_SESSION')
        if type(max_pending_segments) is not int or not 1<=max_pending_segments<=8192: raise ValueError('INVALID_PENDING_BOUND')
        bindings=dict(flow_clients)
        if any(not isinstance(f,str) or not f or not isinstance(c,str) or not c.startswith('client-') for f,c in bindings.items()):
            raise ValueError('INVALID_FLOW_CLIENT_BINDING')
        self.capture_session_id=capture_session_id;self.flow_clients=bindings;self.max_pending=max_pending_segments
        self._flows:dict[str,_Flow]={};self._producer_sequence=0;self._loss_epoch=0;self._lock=RLock()
        self._emitted=0;self._bytes=0;self._ambiguous=0;self._reconnects=0;self._overflow=0;self._loss_fences=0
        self._retired_uncertainty=0;self._retired_duplicates=0;self._retired_reordered=0

    def _connection_id(self,flow_id:str,generation:int)->str:
        digest=sha256(f'{self.capture_session_id}|{flow_id}|{generation}'.encode()).hexdigest()[:24]
        return 'conn-'+digest

    def _times(self,s:CapturedTcpSegment)->tuple[str,int,str]:
        if s.observed_utc is not None and s.observed_monotonic_ns is not None:
            return s.observed_utc,s.observed_monotonic_ns,s.timestamp_provenance
        # Explicit deterministic replay fallback; never claim it is a live clock.
        return '1970-01-01T00:00:00+00:00',s.packet_number,'REPLAY_ORDINAL'

    def _emit(self, flow_id:str, flow:_Flow, state:_Dir, seg:CapturedTcpSegment, payload:bytes, seq:int, continuity:str)->WireEnvelope:
        # A capture-level loss fence outranks otherwise contiguous TCP sequence evidence.
        if state.loss_epoch_seen < self._loss_epoch:
            continuity='GAP_INSIDE';state.loss_epoch_seen=self._loss_epoch
        elif state.reconnected_pending:
            continuity='RECONNECTED';state.reconnected_pending=False
        self._producer_sequence+=1
        utc,mono,provenance=self._times(seg)
        start=state.stream_offset;end=start+len(payload)
        env=WireEnvelope(self.capture_session_id,self.flow_clients[flow_id],self._connection_id(flow_id,flow.generation),
            seg.direction,start,self._producer_sequence,utc,mono,payload,continuity,end,flow.generation,seg.packet_number,provenance)
        state.stream_offset=end;state.emitted+=1;self._emitted+=1;self._bytes+=len(payload)
        return env

    @staticmethod
    def _payload_seq(seg:CapturedTcpSegment)->int:
        return seg.seq + (1 if seg.syn else 0)

    def _retire_generation(self,flow:_Flow)->None:
        # Health is capture-session evidence, not merely the current TCP generation.
        # A reconnect must never erase an unresolved old gap or old duplicate/reorder
        # counters simply because the active direction state is replaced.
        for old in flow.dirs.values():
            self._retired_uncertainty+=old.unresolved_gaps+(1 if old.pending else 0)
            self._retired_duplicates+=old.duplicates
            self._retired_reordered+=old.reordered

    def _start_or_reconnect(self,flow_id:str,flow:_Flow,seg:CapturedTcpSegment)->_Dir:
        state=flow.dirs.setdefault(seg.direction,_Dir())
        if not seg.syn: return state
        terminal_restart=flow.reset_seen or any(d.fin_seq is not None for d in flow.dirs.values())
        if not terminal_restart and state.syn_seq is not None and state.syn_seq==seg.seq:
            state.duplicates+=1;return state
        if terminal_restart or (state.syn_seq is not None and state.syn_seq!=seg.seq):
            # A SYN after terminal evidence, or a different SYN on an already
            # anchored tuple, starts a fresh connection generation.
            self._retire_generation(flow)
            flow.generation+=1;self._reconnects+=1;flow.dirs={};flow.reset_seen=False
            state=_Dir(reconnected_pending=True,loss_epoch_seen=self._loss_epoch);flow.dirs[seg.direction]=state
        state.syn_seq=seg.seq;state.expected=(seg.seq+1)%_MOD;state.loss_epoch_seen=self._loss_epoch;flow.active=True
        return state

    def feed(self,seg:CapturedTcpSegment)->tuple[WireEnvelope,...]:
        with self._lock:return self._feed_unlocked(seg)

    def _feed_unlocked(self,seg:CapturedTcpSegment)->tuple[WireEnvelope,...]:
        if seg.flow_id not in self.flow_clients:
            self._ambiguous+=1;return ()
        flow=self._flows.setdefault(seg.flow_id,_Flow())
        state=self._start_or_reconnect(seg.flow_id,flow,seg)
        seq=self._payload_seq(seg)

        # RST terminates the whole TCP connection. Preserve any payload as
        # explicitly untrusted RESET evidence and fence all later non-SYN bytes.
        if seg.rst:
            flow.reset_seen=True
            if not seg.payload:return ()
            state.unresolved_gaps+=1
            return (self._emit(seg.flow_id,flow,state,seg,seg.payload,seq,'RESET'),)
        if flow.reset_seen and not seg.syn:
            if not seg.payload:return ()
            state.unresolved_gaps+=1
            return (self._emit(seg.flow_id,flow,state,seg,seg.payload,seq,'RESET'),)

        # FIN is half-close evidence. Its sequence position is the first byte
        # that may no longer begin new payload in this direction. Retransmitted
        # pre-FIN bytes remain admissible, but bytes at/after the FIN boundary
        # are preserved only behind an explicit continuity fence.
        if seg.fin:
            fin_seq=seq+len(seg.payload)
            if fin_seq>_MOD:
                state.unresolved_gaps+=1
            elif state.fin_seq is None:
                state.fin_seq=fin_seq
            elif state.fin_seq!=fin_seq:
                state.unresolved_gaps+=1
        if not seg.payload:return ()
        if seq>=_MOD or seq+len(seg.payload)>_MOD:
            state.unresolved_gaps+=1;return ()
        end=seq+len(seg.payload)
        if state.fin_seq is not None and (seq>=state.fin_seq or end>state.fin_seq):
            state.unresolved_gaps+=1
            return (self._emit(seg.flow_id,flow,state,seg,seg.payload,seq,'GAP_INSIDE'),)
        if state.expected is None:
            # Midstream capture: preserve bytes but explicitly fence missing prefix.
            state.expected=seq;state.unresolved_gaps+=1
            env=self._emit(seg.flow_id,flow,state,seg,seg.payload,seq,'GAP_BEFORE')
            state.expected=seq+len(seg.payload)
            return (env,)
        if end<=state.expected:
            state.duplicates+=1;return ()
        if seq<state.expected:
            trim=state.expected-seq;payload=seg.payload[trim:];seq=state.expected
            end=seq+len(payload)
        if seq>state.expected:
            state.reordered+=1;state.pending.append(seg);state.pending.sort(key=self._payload_seq)
            if len(state.pending)>self.max_pending:
                # Never silently discard selected bytes. Clear bounded memory but
                # permanently mark this direction uncertain and force a gap fence.
                state.pending.clear();state.unresolved_gaps+=1;self._overflow+=1;self._loss_epoch+=1
            return ()
        out=[self._emit(seg.flow_id,flow,state,seg,seg.payload[-(end-seq):] if len(seg.payload)!=(end-seq) else seg.payload,seq,'COMPLETE')]
        state.expected=end
        out.extend(self._drain_contiguous(seg.flow_id,flow,state))
        return tuple(out)

    def _drain_contiguous(self,flow_id:str,flow:_Flow,state:_Dir)->list[WireEnvelope]:
        out=[]
        while state.pending:
            seg=state.pending[0];seq=self._payload_seq(seg);end=seq+len(seg.payload)
            if end<=state.expected:
                state.pending.pop(0);state.duplicates+=1;continue
            if seq>state.expected:break
            state.pending.pop(0);trim=max(0,state.expected-seq);payload=seg.payload[trim:]
            out.append(self._emit(flow_id,flow,state,seg,payload,state.expected,'COMPLETE'))
            state.expected+=len(payload)
        return out

    def consume_poll(self,poll:CapturePoll)->tuple[WireEnvelope,...]:
        with self._lock:
            if poll.dropped or poll.overflowed or poll.driver_drop_visibility=='AVAILABLE_DROPPED':
                self._loss_epoch+=1;self._loss_fences+=1
            out=[]
            for seg in poll.segments:out.extend(self._feed_unlocked(seg))
            return tuple(out)

    def finish(self)->tuple[WireEnvelope,...]:
        """Flush later bytes across unresolved sequence gaps with explicit fences."""
        with self._lock:
            return self._finish_unlocked()

    def _finish_unlocked(self)->tuple[WireEnvelope,...]:
        out=[]
        for flow_id,flow in sorted(self._flows.items()):
            for direction,state in sorted(flow.dirs.items()):
                while state.pending:
                    seg=state.pending.pop(0);seq=self._payload_seq(seg);end=seq+len(seg.payload)
                    if state.expected is None:state.expected=seq
                    if end<=state.expected:state.duplicates+=1;continue
                    trim=max(0,state.expected-seq) if seq<state.expected else 0
                    if seq>state.expected:
                        state.stream_offset+=seq-state.expected;state.unresolved_gaps+=1
                        continuity='GAP_BEFORE';state.expected=seq
                    else: continuity='COMPLETE'
                    payload=seg.payload[trim:]
                    out.append(self._emit(flow_id,flow,state,seg,payload,state.expected,continuity))
                    state.expected+=len(payload)
        return tuple(out)

    def health(self)->CaptureHealthSnapshot:
        with self._lock:return self._health_unlocked()

    def _health_unlocked(self)->CaptureHealthSnapshot:
        dirs=[d for f in self._flows.values() for d in f.dirs.values()]
        gaps=self._retired_uncertainty+sum(d.unresolved_gaps+(1 if d.pending else 0) for d in dirs)
        uncertain=bool(gaps or self._ambiguous or self._overflow or self._loss_fences)
        status='NO_TRAFFIC' if self._emitted==0 and not uncertain else ('UNCERTAIN' if uncertain else 'CLEAN')
        return CaptureHealthSnapshot(status,self._emitted,self._bytes,gaps,self._reconnects,
            self._retired_duplicates+sum(d.duplicates for d in dirs),
            self._retired_reordered+sum(d.reordered for d in dirs),
            self._ambiguous,self._loss_fences,self._overflow)
