"""Deterministic replay backend using the same M4 envelope assembler as live polls."""
from __future__ import annotations
from collections.abc import Iterable,Mapping
from anka_contracts.capture import CapturedTcpSegment
from anka_contracts.wire import WireEnvelope
from anka_capture.stream import TransportEnvelopeAssembler

def replay_segments(segments:Iterable[CapturedTcpSegment], *, capture_session_id:str,
                    flow_clients:Mapping[str,str])->tuple[WireEnvelope,...]:
    assembler=TransportEnvelopeAssembler(capture_session_id=capture_session_id,flow_clients=flow_clients)
    out=[]
    for seg in segments:out.extend(assembler.feed(seg))
    out.extend(assembler.finish())
    return tuple(out)
