"""Read-only Windows top-level window discovery; NO keyboard/mouse/control.

Uses stdlib Win32 ctypes with explicit pointer signatures for x64 correctness.
Do not invoke on non-Windows systems. Per-window errors are explicit and result
in a fail-closed inventory, never silent skipping of a configured client.
"""
from __future__ import annotations
import os
import ntpath
from time import monotonic_ns
import re
from anka_client.discovery import SUPPORTED_EXECUTABLES
from anka_contracts.client import WindowObservation, WindowScan


def _candidate_observation(observation: WindowObservation, *, hinted: bool=False) -> bool:
    """Pure keep/discard rule: executable identity outranks title hints."""
    return (ntpath.basename(observation.executable_name).casefold() in SUPPORTED_EXECUTABLES
            or bool(hinted))


class NativeWindowsInventory:
    def __init__(self, character_names: tuple[str,...] = ()):
        if os.name != 'nt':
            raise RuntimeError('WINDOW_DISCOVERY_REQUIRES_WINDOWS')
        self.character_names=tuple(character_names)
        import ctypes
        from ctypes import wintypes as wt
        self.c=ctypes;self.wt=wt
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.version=ctypes.WinDLL('version',use_last_error=True)
        self.user.EnumWindows.argtypes=[ctypes.WINFUNCTYPE(wt.BOOL,wt.HWND,wt.LPARAM),wt.LPARAM]
        self.user.EnumWindows.restype=wt.BOOL
        self.user.IsWindowVisible.argtypes=[wt.HWND];self.user.IsWindowVisible.restype=wt.BOOL
        self.user.GetWindowTextLengthW.argtypes=[wt.HWND];self.user.GetWindowTextLengthW.restype=ctypes.c_int
        self.user.GetWindowTextW.argtypes=[wt.HWND,wt.LPWSTR,ctypes.c_int];self.user.GetWindowTextW.restype=ctypes.c_int
        self.user.IsIconic.argtypes=[wt.HWND];self.user.IsIconic.restype=wt.BOOL
        self.user.GetForegroundWindow.argtypes=[];self.user.GetForegroundWindow.restype=wt.HWND
        self.user.GetWindowThreadProcessId.argtypes=[wt.HWND,ctypes.POINTER(wt.DWORD)];self.user.GetWindowThreadProcessId.restype=wt.DWORD
        self.user.GetClientRect.argtypes=[wt.HWND,ctypes.POINTER(wt.RECT)];self.user.GetClientRect.restype=wt.BOOL
        self.kernel.OpenProcess.argtypes=[wt.DWORD,wt.BOOL,wt.DWORD];self.kernel.OpenProcess.restype=wt.HANDLE
        self.kernel.CloseHandle.argtypes=[wt.HANDLE];self.kernel.CloseHandle.restype=wt.BOOL
        self.kernel.GetProcessTimes.argtypes=[wt.HANDLE,ctypes.POINTER(wt.FILETIME),ctypes.POINTER(wt.FILETIME),ctypes.POINTER(wt.FILETIME),ctypes.POINTER(wt.FILETIME)]
        self.kernel.GetProcessTimes.restype=wt.BOOL
        self.kernel.QueryFullProcessImageNameW.argtypes=[wt.HANDLE,wt.DWORD,wt.LPWSTR,ctypes.POINTER(wt.DWORD)]
        self.kernel.QueryFullProcessImageNameW.restype=wt.BOOL
        self.version.GetFileVersionInfoSizeW.argtypes=[wt.LPCWSTR,ctypes.POINTER(wt.DWORD)]
        self.version.GetFileVersionInfoSizeW.restype=wt.DWORD
        self.version.GetFileVersionInfoW.argtypes=[wt.LPCWSTR,wt.DWORD,wt.DWORD,ctypes.c_void_p]
        self.version.GetFileVersionInfoW.restype=wt.BOOL
        self.version.VerQueryValueW.argtypes=[ctypes.c_void_p,wt.LPCWSTR,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(wt.UINT)]
        self.version.VerQueryValueW.restype=wt.BOOL
        self.get_dpi=getattr(self.user,'GetDpiForWindow',None)
        if self.get_dpi is not None:
            self.get_dpi.argtypes=[wt.HWND];self.get_dpi.restype=wt.UINT

    def _product_version(self,path:str)->str|None:
        """Return a numeric executable ProductVersion without exporting its path."""
        c=self.c;wt=self.wt
        class VS_FIXEDFILEINFO(c.Structure):
            _fields_=[('dwSignature',wt.DWORD),('dwStrucVersion',wt.DWORD),
                      ('dwFileVersionMS',wt.DWORD),('dwFileVersionLS',wt.DWORD),
                      ('dwProductVersionMS',wt.DWORD),('dwProductVersionLS',wt.DWORD),
                      ('dwFileFlagsMask',wt.DWORD),('dwFileFlags',wt.DWORD),
                      ('dwFileOS',wt.DWORD),('dwFileType',wt.DWORD),
                      ('dwFileSubtype',wt.DWORD),('dwFileDateMS',wt.DWORD),('dwFileDateLS',wt.DWORD)]
        dummy=wt.DWORD(0)
        size=int(self.version.GetFileVersionInfoSizeW(path,c.byref(dummy)) or 0)
        if size<=0 or size>4*1024*1024:return None
        buf=c.create_string_buffer(size)
        if not self.version.GetFileVersionInfoW(path,0,size,buf):return None
        ptr=c.c_void_p(); length=wt.UINT(0)
        if not self.version.VerQueryValueW(buf,'\\',c.byref(ptr),c.byref(length)) or length.value < c.sizeof(VS_FIXEDFILEINFO):return None
        info=c.cast(ptr,c.POINTER(VS_FIXEDFILEINFO)).contents
        if int(info.dwSignature)!=0xFEEF04BD:return None
        ms=int(info.dwProductVersionMS);ls=int(info.dwProductVersionLS)
        version=f'{(ms>>16)&0xffff}.{ms&0xffff}.{(ls>>16)&0xffff}.{ls&0xffff}'
        return version if version!='0.0.0.0' else None

    def _inspect(self,hwnd:int,title:str)->WindowObservation:
        c=self.c;wt=self.wt
        pid=wt.DWORD(0)
        if not self.user.GetWindowThreadProcessId(hwnd,c.byref(pid)) or not pid.value:
            raise OSError('PROCESS_ID_UNAVAILABLE')
        h=self.kernel.OpenProcess(0x1000,False,pid.value)
        if not h:raise OSError('PROCESS_OPEN_FAILED')
        try:
            buf=c.create_unicode_buffer(4096); length=wt.DWORD(len(buf))
            if not self.kernel.QueryFullProcessImageNameW(h,0,buf,c.byref(length)):
                raise OSError('PROCESS_IMAGE_UNAVAILABLE')
            ft=[wt.FILETIME() for _ in range(4)]
            if not self.kernel.GetProcessTimes(h,*(c.byref(x) for x in ft)):
                raise OSError('PROCESS_GENERATION_UNAVAILABLE')
            created=(int(ft[0].dwHighDateTime)<<32)|int(ft[0].dwLowDateTime)
            image_path=buf.value
            try:build_version=self._product_version(image_path)
            except Exception:build_version=None
            rect=wt.RECT()
            if not self.user.GetClientRect(hwnd,c.byref(rect)):
                raise OSError('CLIENT_RECT_UNAVAILABLE')
            dpi=int(self.get_dpi(hwnd)) if self.get_dpi else None
            minimized=bool(self.user.IsIconic(hwnd))
            foreground=int(self.user.GetForegroundWindow() or 0)==int(hwnd)
            # Hold the process handle until every HWND-derived field is observed,
            # then prove that the HWND still belongs to the same PID. Keeping the
            # handle open also prevents the old process object from disappearing
            # and its PID being recycled during this snapshot.
            final_pid=wt.DWORD(0)
            if not self.user.GetWindowThreadProcessId(hwnd,c.byref(final_pid)) or final_pid.value!=pid.value:
                raise OSError('WINDOW_PROCESS_CHANGED_DURING_INSPECTION')
            width=int(rect.right-rect.left);height=int(rect.bottom-rect.top)
        finally:
            self.kernel.CloseHandle(h)
        return WindowObservation(int(hwnd),int(pid.value),created,ntpath.basename(image_path),title,
                                 width,height,dpi if dpi and dpi>0 else None,
                                 minimized,foreground,None,build_version)

    def scan(self)->WindowScan:
        c=self.c;wt=self.wt
        results=[];errors=[]
        cb_type=c.WINFUNCTYPE(wt.BOOL,wt.HWND,wt.LPARAM)
        @cb_type
        def visit(hwnd,_):
            try:
                if not self.user.IsWindowVisible(hwnd):return True
                n=self.user.GetWindowTextLengthW(hwnd)
                if n<=0 or n>2048:return True
                buf=c.create_unicode_buffer(n+1)
                self.user.GetWindowTextW(hwnd,buf,n+1)
                title=buf.value.strip()
                if not title:
                    return True
                # Title text is only a discovery hint. A current client may omit
                # both "Dofus" and the character name, so inspect visible titled
                # windows far enough to verify their executable image. Unrelated
                # process-access failures are ignored; a hinted Dofus failure is
                # retained because otherwise we could silently omit a candidate.
                hinted = ('dofus' in title.casefold() or any(
                    re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',title,re.IGNORECASE)
                    for name in self.character_names))
                try:
                    observation=self._inspect(int(hwnd),title)
                except Exception as exc:
                    if hinted:
                        errors.append('WINDOW_INSPECTION_FAILED:'+type(exc).__name__)
                    return True
                if _candidate_observation(observation,hinted=hinted):
                    results.append(observation)
            except Exception as exc:
                errors.append('WINDOW_ENUM_CALLBACK_FAILED:'+type(exc).__name__)
            return True
        ok=self.user.EnumWindows(visit,0)
        if not ok:errors.append('ENUM_WINDOWS_FAILED')
        return WindowScan(monotonic_ns(),tuple(sorted(results,key=lambda w:(w.pid,w.hwnd))),tuple(errors))
