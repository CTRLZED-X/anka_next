"""Application-only composition: Capture -> independent Protocol input contracts.

This adapter is the sole code allowed to depend on both packages. It keeps
protocol internals testable without importing the capture implementation.
"""
from __future__ import annotations
from pathlib import Path
from hashlib import sha256
from anka_capture.api import inspect_pcapng, MAX_CAPTURE_BYTES, validate_ports, CaptureRejected
from anka_capture.pcapng import read_pcapng_tcp_segments
from anka_protocol.api import ProtocolInspector
from anka_protocol.adapters.historical import load_reference

def inspect_protocol_pcapng(path:Path,*,root:Path,ports:tuple[int,...],build:str,observer=None)->dict:
    """Offline bridge; evidence checked before observation. No raw packet is logged."""
    validate_ports(ports)
    capture=inspect_pcapng(path,server_ports=ports,observer=observer)
    # Reject changed evidence across the two pass approach; no TOCTOU result is certified.
    file=Path(path)
    if file.stat().st_size>MAX_CAPTURE_BYTES:raise CaptureRejected('CAPTURE_FILE_SIZE_UNSUPPORTED')
    raw=file.read_bytes()
    if sha256(raw).hexdigest()!=capture.source_sha256:raise CaptureRejected('CAPTURE_SOURCE_CHANGED_DURING_READ')
    segments=read_pcapng_tcp_segments(file,server_ports=set(ports),raw=raw)
    inspector=ProtocolInspector(load_reference(root),requested_build=build,observer=observer)
    for s in segments:inspector.consume(s)
    report=inspector.finish()
    # Historical observations never certify the capture, the protocol, or account binding.
    return {'operation':'protocol-audit','capture':capture.to_dict(),'protocol':report.to_dict(),
            'live_ready':False,'physical_input_sent':False}


