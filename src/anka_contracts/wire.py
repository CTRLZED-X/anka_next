"""Transport-only wire envelope between Capture and Protocol."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

Direction = Literal["client_to_server", "server_to_client"]
Continuity = Literal["COMPLETE", "GAP_BEFORE", "GAP_INSIDE", "RECONNECTED", "CONTIGUOUS", "RESET", "UNKNOWN"]


@dataclass(frozen=True, slots=True)
class WireEnvelope:
    capture_session_id: str
    client_instance_id: str
    connection_id: str
    direction: Direction
    stream_offset: int
    producer_sequence: int
    observed_utc: str
    observed_monotonic_ns: int
    payload: bytes = field(repr=False)
    continuity: Continuity = "CONTIGUOUS"
    transport_end_offset: int | None = None
    connection_generation: int = 1
    source_packet_number: int | None = None
    timestamp_provenance: str = 'UNKNOWN'

    @property
    def transport_start_offset(self) -> int:
        return self.stream_offset

    @property
    def effective_transport_end_offset(self) -> int:
        return self.transport_end_offset if self.transport_end_offset is not None else self.stream_offset + len(self.payload)

    def __post_init__(self):
        for value, prefix, code in (
            (self.capture_session_id, "capture-", "INVALID_CAPTURE_SESSION"),
            (self.client_instance_id, "client-", "INVALID_CLIENT_INSTANCE"),
            (self.connection_id, "conn-", "INVALID_CONNECTION_ID"),
        ):
            if type(value) is not str or not value.startswith(prefix) or len(value) > 128:
                raise ValueError(code)
        if self.direction not in ("client_to_server", "server_to_client"):
            raise ValueError("INVALID_WIRE_DIRECTION")
        if type(self.stream_offset) is not int or self.stream_offset < 0:
            raise ValueError("INVALID_STREAM_OFFSET")
        if type(self.producer_sequence) is not int or self.producer_sequence < 0:
            raise ValueError("INVALID_PRODUCER_SEQUENCE")
        if type(self.observed_monotonic_ns) is not int or self.observed_monotonic_ns < 0:
            raise ValueError("INVALID_OBSERVED_MONOTONIC")
        if type(self.payload) is not bytes or len(self.payload) > 4 * 1024 * 1024:
            raise ValueError("INVALID_WIRE_PAYLOAD")
        if self.continuity not in ("COMPLETE","GAP_BEFORE","GAP_INSIDE","RECONNECTED","CONTIGUOUS","RESET","UNKNOWN"):
            raise ValueError("INVALID_CONTINUITY")
        end=self.effective_transport_end_offset
        if type(end) is not int or end < self.stream_offset or end-self.stream_offset != len(self.payload):
            raise ValueError('INVALID_TRANSPORT_END_OFFSET')
        if type(self.connection_generation) is not int or self.connection_generation <= 0:
            raise ValueError('INVALID_CONNECTION_GENERATION')
        if self.source_packet_number is not None and (type(self.source_packet_number) is not int or self.source_packet_number<=0):
            raise ValueError('INVALID_SOURCE_PACKET_NUMBER')
        if self.timestamp_provenance not in ('UNKNOWN','LIVE_CALLBACK','PCAP_WALL_CLOCK','REPLAY_ORDINAL','TEST_FIXTURE'):
            raise ValueError('INVALID_WIRE_TIMESTAMP_PROVENANCE')
