"""P64 explicit-consent, bounded PCAPNG *research evidence* from passive TCP.

Only Windows passive Npcap capture should feed this writer. It creates a private
runtime artifact, not a Canonical observation or a complete-capture receipt.
All methods are synchronous/thread-safe and never send network or input data.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from secrets import token_hex
from threading import Lock
from time import time_ns
import json
import os
import struct

MAX_EVIDENCE_BYTES = 8 * 1024 * 1024
MAX_EVIDENCE_FRAMES = 5000
MAX_FRAME_BYTES = 65535


def _block(kind: int, body: bytes) -> bytes:
    pad = b'\x00' * ((-len(body)) % 4)
    length = 12 + len(body) + len(pad)
    return struct.pack('<II', kind, length) + body + pad + struct.pack('<I', length)


def _selected_ipv4_tcp(frame: bytes, ports: tuple[int, ...]) -> bool:
    """Only real selected-port, unfragmented IPv4 TCP frames can be persisted."""
    if not isinstance(frame, bytes) or not 14 <= len(frame) <= MAX_FRAME_BYTES:
        return False
    if frame[12:14] != b'\x08\x00':  # P64 deliberately refuses VLAN/IPv6/offload ambiguity
        return False
    ip = frame[14:]
    if len(ip) < 40 or ip[0] >> 4 != 4 or ip[9] != 6:
        return False
    ihl = (ip[0] & 15) * 4
    if ihl < 20 or len(ip) < ihl + 20:
        return False
    if int.from_bytes(ip[6:8], 'big') & 0x3FFF:  # fragmented
        return False
    length = int.from_bytes(ip[2:4], 'big')
    if length and (length < ihl + 20 or len(ip) < length):
        return False
    tcp = ip[ihl:]
    doff = (tcp[12] >> 4) * 4
    if doff < 20 or len(tcp) < doff:
        return False
    sport, dport = struct.unpack_from('!HH', tcp)
    return (sport in ports) != (dport in ports)


class ConsentedPcapngRecorder:
    """Creates one bounded local artifact when explicitly enabled by JSON config.

    File names are random and never enter diagnostics. A positive loss counter
    is written to the PCAPNG itself if any callback/frame/size was rejected,
    so the existing research parser MUST reject incomplete evidence.
    """
    def __init__(self, directory: Path, *, server_ports: tuple[int, ...]):
        if not isinstance(server_ports, tuple) or not server_ports or not all(
                type(p) is int and 1 <= p <= 65535 for p in server_ports):
            raise ValueError('EVIDENCE_PORT_SCOPE_INVALID')
        self._ports = server_ports
        self._lock = Lock()
        folder = Path(directory)
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        name = 'passive_' + token_hex(12) + '.pcapng'
        self._final_path = folder / name
        self._partial_path = folder / (name + '.partial')
        self._file = self._partial_path.open('xb')
        if os.name != 'nt':
            os.chmod(self._partial_path, 0o600)
        self._frames = 0
        self._failures = 0
        self._length = 0
        self._closed = False
        self._digest = ''
        try:
            # Unknown SHB section length, IDB linktype 1 (Ethernet), snaplen=65535.
            self._write(_block(0x0A0D0D0A, struct.pack('<IHHq', 0x1A2B3C4D, 1, 0, -1)))
            self._write(_block(1, struct.pack('<HHI', 1, 0, MAX_FRAME_BYTES)))
        except BaseException:
            self._file.close()
            self._partial_path.unlink(missing_ok=True)
            raise

    def _write(self, data: bytes) -> None:
        self._file.write(data)
        self._length += len(data)

    def record(self, frame: bytes, *, captured_ns: int | None = None) -> bool:
        with self._lock:
            if self._closed:
                return False
            if not _selected_ipv4_tcp(frame, self._ports):
                self._failures += 1
                return False
            if captured_ns is None:
                captured_ns = time_ns()
            if type(captured_ns) is not int or not 0 <= captured_ns < 2**64:
                self._failures += 1
                return False
            stamp_us = captured_ns // 1000  # PCAPNG default timestamp resolution
            body = struct.pack('<IIIII', 0, stamp_us >> 32, stamp_us & 0xFFFFFFFF,
                               len(frame), len(frame)) + frame
            record = _block(6, body)
            # Reserve margin for close and loss metadata.
            if (self._frames >= MAX_EVIDENCE_FRAMES or
                    self._length + len(record) + 128 > MAX_EVIDENCE_BYTES):
                self._failures += 1
                return False
            try:
                self._write(record)
            except OSError:
                self._failures += 1
                return False
            self._frames += 1
            return True

    def mark_incomplete(self) -> None:
        with self._lock:
            if not self._closed:
                self._failures += 1

    def close(self) -> dict:
        with self._lock:
            if not self._closed:
                try:
                    if self._failures:
                        # ISB ifdrop (option 5): cap no greater than 64-bit range.
                        opt = struct.pack('<HHQ', 5, 8, min(self._failures, 2**64-1))
                        opt += struct.pack('<HH', 0, 0)
                        self._write(_block(5, struct.pack('<IQ', 0, 0) + opt))
                    self._file.flush()
                    os.fsync(self._file.fileno())
                    self._file.close()
                    os.replace(self._partial_path, self._final_path)
                    self._digest = sha256(self._final_path.read_bytes()).hexdigest()
                except BaseException:
                    self._closed = True
                    try:
                        self._file.close()
                    finally:
                        # A failed recording remains visibly .partial, never a
                        # trusted or seemingly finalized capture.
                        pass
                    raise
                self._closed = True
            return {'status': 'RECORDED_UNCERTIFIED' if not self._failures else 'INCOMPLETE_RECORDED',
                    'frames': self._frames, 'known_recording_gaps': self._failures,
                    'sha256': self._digest, 'driver_loss_visibility': 'UNKNOWN',
                    'live_certified': False, 'account_binding_verified': False,
                    'canonical_commits': 0, 'physical_input_sent': False}

    @property
    def final_path(self) -> Path:
        return self._final_path
