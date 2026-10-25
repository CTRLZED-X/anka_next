"""Bounded exact byte proof for TCP retransmission overlap.

Capture may prove that a retransmitted overlap is identical only while the
previously accepted bytes are still retained in this small in-memory window.
Older overlap is deliberately unverifiable and must fail closed upstream.

This module owns no flow, Protocol, or game semantics and never serializes the
retained bytes.
"""
from __future__ import annotations

DEFAULT_OVERLAP_PROOF_BYTES = 4096
MAX_OVERLAP_PROOF_BYTES = 65536

MATCH = "MATCH"
CONFLICT = "CONFLICT"
UNVERIFIABLE = "UNVERIFIABLE"


class RecentByteProof:
    """Exact bounded suffix of one accepted TCP half-stream.

    Memory is capped at max_bytes. The proof is a contiguous recent suffix;
    any discontinuous acceptance resets it rather than pretending the missing
    range can be verified later.
    """

    __slots__ = ("max_bytes", "_start", "_data")

    def __init__(self, max_bytes: int = DEFAULT_OVERLAP_PROOF_BYTES):
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_OVERLAP_PROOF_BYTES:
            raise ValueError("INVALID_OVERLAP_PROOF_BOUND")
        self.max_bytes = max_bytes
        self._start: int | None = None
        self._data = b""

    @property
    def start(self) -> int | None:
        return self._start

    @property
    def end(self) -> int | None:
        return None if self._start is None else self._start + len(self._data)

    @property
    def retained_bytes(self) -> int:
        return len(self._data)

    def clear(self) -> None:
        self._start = None
        self._data = b""

    def remember(self, seq: int, payload: bytes) -> None:
        """Retain only the newest exact bytes, never more than the configured cap."""
        if type(seq) is not int or seq < 0 or not isinstance(payload, bytes):
            raise ValueError("INVALID_OVERLAP_PROOF_INPUT")
        if not payload:
            return
        previous_end = self.end
        if previous_end is not None and seq == previous_end:
            combined = self._data + payload
            start = self._start
        else:
            # A gap, rewind, or independently accepted range is not one
            # contiguous proof window. Start a new exact suffix at this range.
            combined = payload
            start = seq
        if len(combined) > self.max_bytes:
            trim = len(combined) - self.max_bytes
            combined = combined[trim:]
            start = int(start) + trim
        self._start = int(start)
        self._data = combined

    def compare(self, seq: int, payload: bytes, overlap_end: int) -> str:
        """Compare an incoming overlap against retained accepted bytes.

        payload begins at seq. Only bytes in [seq, overlap_end) are compared.
        If any required byte lies outside the retained proof window, the result
        is UNVERIFIABLE rather than an assumed duplicate.
        """
        if (type(seq) is not int or type(overlap_end) is not int or seq < 0
                or overlap_end < seq or not isinstance(payload, bytes)
                or overlap_end - seq > len(payload)):
            raise ValueError("INVALID_OVERLAP_PROOF_INPUT")
        if overlap_end == seq:
            return MATCH
        proof_end = self.end
        if self._start is None or proof_end is None:
            return UNVERIFIABLE
        if seq < self._start or overlap_end > proof_end:
            return UNVERIFIABLE
        offset = seq - self._start
        length = overlap_end - seq
        expected = self._data[offset:offset + length]
        observed = payload[:length]
        return MATCH if observed == expected else CONFLICT
