"""Host-wide authority lease for the one active ANKA ``start`` process.

The lease is deliberately application/composition authority.  It owns no game
state and grants no input permission; it only prevents two ANKA processes from
simultaneously observing/controlling the same host.  Windows uses a named mutex
whose lifetime is the kernel handle, so process crashes cannot leave a stale
pidfile lock behind.
"""
from __future__ import annotations

from dataclasses import dataclass
import os

_MUTEX_NAME = r"Local\ANKA_NEXT_RUN_AUTHORITY_V1"
_ERROR_ALREADY_EXISTS = 183


class RunAuthorityRejected(RuntimeError):
    pass


@dataclass(slots=True)
class RunAuthorityLease:
    _backend: object | None = None
    _handle: object | None = None
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._backend is not None and self._handle is not None:
            self._backend.close(self._handle)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False


class _WindowsMutexBackend:
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL

    def acquire(self, name: str):
        self.ctypes.set_last_error(0)
        handle = self.kernel.CreateMutexW(None, False, name)
        if not handle:
            raise RunAuthorityRejected('START_RUN_AUTHORITY_ACQUIRE_FAILED')
        already = self.ctypes.get_last_error() == _ERROR_ALREADY_EXISTS
        if already:
            self.kernel.CloseHandle(handle)
            raise RunAuthorityRejected('START_RUN_AUTHORITY_ALREADY_HELD')
        return handle

    def close(self, handle) -> None:
        if not self.kernel.CloseHandle(handle):
            # Shutdown must remain fail-safe. The OS releases this handle on
            # process exit; surfacing a cleanup exception could hide the real
            # startup result and cannot make a second process safer.
            return


def acquire_start_authority(*, backend=None, require_windows: bool = True) -> RunAuthorityLease:
    """Acquire the one-per-host start authority.

    A backend argument exists only for deterministic tests. Production Windows
    uses a named mutex. Non-Windows callers may request a no-op lease because
    the normal start path already fails closed at the platform boundary.
    """
    if backend is None:
        if os.name != 'nt':
            if require_windows:
                raise RunAuthorityRejected('START_WINDOWS_REQUIRED')
            return RunAuthorityLease()
        backend = _WindowsMutexBackend()
    handle = backend.acquire(_MUTEX_NAME)
    return RunAuthorityLease(backend, handle)
