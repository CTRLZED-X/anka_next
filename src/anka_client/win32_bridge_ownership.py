"""Read-only Windows ownership proof for the local Unity bridge listener.

The Unity bridge health payload is self-reported. Before treating it as
process-scoped evidence, independently prove through the Windows TCP table that
127.0.0.1:<port> is listening in the claimed Dofus process.
"""
from __future__ import annotations

import os
import socket
import struct


_MAX_TCP_TABLE_BYTES = 4 * 1024 * 1024
_ERROR_INSUFFICIENT_BUFFER = 122
_AF_INET = 2
_TCP_TABLE_OWNER_PID_LISTENER = 3
_MIB_TCPROW_OWNER_PID_DWORDS = 6
_MIB_TCP_STATE_LISTEN = 2


def loopback_listener_owner_pid(port: int) -> int | None:
    """Return the unique PID owning an IPv4 loopback LISTEN socket on port.

    No process is started and no socket is modified. None means there is no
    matching loopback listener. Ambiguous/corrupt Windows table evidence is
    rejected rather than guessed.
    """
    if os.name != 'nt':
        raise RuntimeError('WINDOWS_BRIDGE_OWNERSHIP_REQUIRES_WINDOWS')
    if type(port) is not int or not (1 <= port <= 65535):
        raise ValueError('INVALID_BRIDGE_PORT')

    import ctypes
    from ctypes import wintypes as wt

    iphlpapi = ctypes.WinDLL('iphlpapi', use_last_error=True)
    get_table = iphlpapi.GetExtendedTcpTable
    get_table.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wt.DWORD),
        wt.BOOL,
        wt.ULONG,
        wt.ULONG,
        wt.ULONG,
    ]
    get_table.restype = wt.DWORD

    size = wt.DWORD(0)
    first = int(get_table(
        None, ctypes.byref(size), False, _AF_INET,
        _TCP_TABLE_OWNER_PID_LISTENER, 0,
    ))
    if first not in (0, _ERROR_INSUFFICIENT_BUFFER):
        raise OSError('TCP_LISTENER_TABLE_SIZE_FAILED')
    if size.value < 4 or size.value > _MAX_TCP_TABLE_BYTES:
        raise OSError('TCP_LISTENER_TABLE_SIZE_INVALID')

    buffer = ctypes.create_string_buffer(size.value)
    second = int(get_table(
        buffer, ctypes.byref(size), False, _AF_INET,
        _TCP_TABLE_OWNER_PID_LISTENER, 0,
    ))
    if second != 0:
        raise OSError('TCP_LISTENER_TABLE_READ_FAILED')

    raw = memoryview(buffer)[:size.value]
    count = struct.unpack_from('<I', raw, 0)[0]
    row_size = _MIB_TCPROW_OWNER_PID_DWORDS * 4
    if count > (_MAX_TCP_TABLE_BYTES - 4) // row_size or 4 + count * row_size > len(raw):
        raise OSError('TCP_LISTENER_TABLE_TRUNCATED')

    owners = set()
    for index in range(count):
        state, local_addr, local_port, _remote_addr, _remote_port, pid = struct.unpack_from(
            '<6I', raw, 4 + index * row_size
        )
        if state != _MIB_TCP_STATE_LISTEN:
            continue
        observed_port = socket.ntohs(local_port & 0xFFFF)
        if observed_port != port:
            continue
        address = socket.inet_ntoa(struct.pack('<I', local_addr))
        if address != '127.0.0.1':
            continue
        if pid <= 0:
            raise OSError('TCP_LISTENER_OWNER_INVALID')
        owners.add(pid)

    if len(owners) > 1:
        raise OSError('TCP_LISTENER_OWNER_AMBIGUOUS')
    return next(iter(owners)) if owners else None
