"""Read-only Windows ownership proof for the local Unity bridge listener.

The Unity bridge health payload is self-reported. Before treating it as
process-scoped evidence, independently prove through the Windows TCP table that
127.0.0.1:<port> is listening in the claimed Dofus process.
"""
from __future__ import annotations

import ctypes
import os
import socket


_MAX_TCP_TABLE_BYTES = 4 * 1024 * 1024
_ERROR_INSUFFICIENT_BUFFER = 122
_AF_INET = 2
_TCP_TABLE_OWNER_PID_LISTENER = 3
_MIB_TCP_STATE_LISTEN = 2


class _MibTcpRowOwnerPid(ctypes.Structure):
    _fields_ = [
        ('dwState', ctypes.c_uint32),
        ('dwLocalAddr', ctypes.c_uint32),
        ('dwLocalPort', ctypes.c_uint32),
        ('dwRemoteAddr', ctypes.c_uint32),
        ('dwRemotePort', ctypes.c_uint32),
        ('dwOwningPid', ctypes.c_uint32),
    ]


class _MibTcpTableOwnerPidHead(ctypes.Structure):
    _fields_ = [
        ('dwNumEntries', ctypes.c_uint32),
        ('table', _MibTcpRowOwnerPid * 1),
    ]


_TCP_ROW_OFFSET = _MibTcpTableOwnerPidHead.table.offset
_TCP_ROW_SIZE = ctypes.sizeof(_MibTcpRowOwnerPid)


def _loopback_listener_owners(raw: bytes, port: int) -> set[int]:
    """Parse a MIB_TCPTABLE_OWNER_PID blob using native structure alignment."""
    if type(port) is not int or not (1 <= port <= 65535):
        raise ValueError('INVALID_BRIDGE_PORT')
    if type(raw) is not bytes or len(raw) < _TCP_ROW_OFFSET or len(raw) > _MAX_TCP_TABLE_BYTES:
        raise OSError('TCP_LISTENER_TABLE_SIZE_INVALID')
    count = ctypes.c_uint32.from_buffer_copy(raw, 0).value
    if count > (_MAX_TCP_TABLE_BYTES - _TCP_ROW_OFFSET) // _TCP_ROW_SIZE:
        raise OSError('TCP_LISTENER_TABLE_TRUNCATED')
    required = _TCP_ROW_OFFSET + count * _TCP_ROW_SIZE
    if required > len(raw):
        raise OSError('TCP_LISTENER_TABLE_TRUNCATED')

    owners = set()
    for index in range(count):
        row = _MibTcpRowOwnerPid.from_buffer_copy(raw, _TCP_ROW_OFFSET + index * _TCP_ROW_SIZE)
        if row.dwState != _MIB_TCP_STATE_LISTEN:
            continue
        if socket.ntohs(row.dwLocalPort & 0xFFFF) != port:
            continue
        address_bytes = int(row.dwLocalAddr).to_bytes(4, byteorder='little', signed=False)
        if socket.inet_ntoa(address_bytes) != '127.0.0.1':
            continue
        if row.dwOwningPid <= 0:
            raise OSError('TCP_LISTENER_OWNER_INVALID')
        owners.add(int(row.dwOwningPid))
    return owners


def loopback_listener_owner_generation(port: int) -> tuple[int, int] | None:
    """Return exact (PID, process creation FILETIME) for a loopback listener.

    No process is started and no socket is modified. None means there is no
    matching loopback listener. Ambiguous/corrupt Windows evidence, PID reuse,
    or an unavailable process generation is rejected rather than guessed.
    """
    if os.name != 'nt':
        raise RuntimeError('WINDOWS_BRIDGE_OWNERSHIP_REQUIRES_WINDOWS')
    if type(port) is not int or not (1 <= port <= 65535):
        raise ValueError('INVALID_BRIDGE_PORT')

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

    raw = None
    for _attempt in range(3):
        if size.value < _TCP_ROW_OFFSET or size.value > _MAX_TCP_TABLE_BYTES:
            raise OSError('TCP_LISTENER_TABLE_SIZE_INVALID')
        buffer = ctypes.create_string_buffer(size.value)
        result = int(get_table(
            buffer, ctypes.byref(size), False, _AF_INET,
            _TCP_TABLE_OWNER_PID_LISTENER, 0,
        ))
        if result == 0:
            raw = buffer.raw[:size.value]
            break
        if result != _ERROR_INSUFFICIENT_BUFFER:
            raise OSError('TCP_LISTENER_TABLE_READ_FAILED')
    if raw is None:
        raise OSError('TCP_LISTENER_TABLE_UNSTABLE')

    owners = _loopback_listener_owners(raw, port)
    if len(owners) > 1:
        raise OSError('TCP_LISTENER_OWNER_AMBIGUOUS')
    if not owners:
        return None

    pid = next(iter(owners))
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes=[wt.DWORD,wt.BOOL,wt.DWORD]
    kernel.OpenProcess.restype=wt.HANDLE
    kernel.CloseHandle.argtypes=[wt.HANDLE]
    kernel.CloseHandle.restype=wt.BOOL
    kernel.GetProcessTimes.argtypes=[
        wt.HANDLE,ctypes.POINTER(wt.FILETIME),ctypes.POINTER(wt.FILETIME),
        ctypes.POINTER(wt.FILETIME),ctypes.POINTER(wt.FILETIME)
    ]
    kernel.GetProcessTimes.restype=wt.BOOL
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:
        raise OSError('TCP_LISTENER_PROCESS_OPEN_FAILED')
    try:
        times=[wt.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle,*(ctypes.byref(item) for item in times)):
            raise OSError('TCP_LISTENER_PROCESS_GENERATION_UNAVAILABLE')
        created=(int(times[0].dwHighDateTime)<<32)|int(times[0].dwLowDateTime)
        if created <= 0:
            raise OSError('TCP_LISTENER_PROCESS_GENERATION_INVALID')
    finally:
        kernel.CloseHandle(handle)
    return pid,created


def loopback_listener_owner_pid(port: int) -> int | None:
    """Compatibility diagnostic returning only the independently verified PID."""
    generation=loopback_listener_owner_generation(port)
    return generation[0] if generation is not None else None
