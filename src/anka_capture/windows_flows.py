"""Windows TCP endpoint->PID snapshot (read only, IPv4 + IPv6).

Uses GetExtendedTcpTable owner-PID connection tables. A snapshot is a process
hint only, never account/character authority. Both address families are queried
so an IPv6 Dofus connection cannot silently disappear from auto capture scope.
"""
from __future__ import annotations
import os
import socket
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TcpEndpoint:
    local_ip: str
    local_port: int
    remote_ip: str
    remote_port: int
    pid: int
    state: int
    family: str = 'IPv4'


class WindowsTcpOwnership:
    @staticmethod
    def _port(value:int)->int:
        return int.from_bytes(int(value).to_bytes(4,'little')[:2],'big')

    def snapshot(self)->tuple[TcpEndpoint,...]:
        if os.name!='nt': raise RuntimeError('TCP_OWNER_TABLE_WINDOWS_ONLY')
        import ctypes
        from ctypes import wintypes
        lib=ctypes.WinDLL('iphlpapi',use_last_error=True)
        get=lib.GetExtendedTcpTable
        get.argtypes=[ctypes.c_void_p,ctypes.POINTER(wintypes.DWORD),wintypes.BOOL,
                      wintypes.ULONG,ctypes.c_int,wintypes.ULONG]
        get.restype=wintypes.DWORD

        class Row4(ctypes.Structure):
            _fields_=[('state',wintypes.DWORD),('local_addr',wintypes.DWORD),
                      ('local_port',wintypes.DWORD),('remote_addr',wintypes.DWORD),
                      ('remote_port',wintypes.DWORD),('pid',wintypes.DWORD)]
        class Row6(ctypes.Structure):
            _fields_=[('local_addr',ctypes.c_ubyte*16),('local_scope',wintypes.DWORD),
                      ('local_port',wintypes.DWORD),('remote_addr',ctypes.c_ubyte*16),
                      ('remote_scope',wintypes.DWORD),('remote_port',wintypes.DWORD),
                      ('state',wintypes.DWORD),('pid',wintypes.DWORD)]

        def query(af:int,row_type,parse):
            size=wintypes.DWORD(0)
            first=get(None,ctypes.byref(size),False,af,4,0) # OWNER_PID_CONNECTIONS
            if first not in (0,122): raise RuntimeError('TCP_OWNER_TABLE_QUERY_FAILED')
            if not 4<=size.value<=8*1024*1024: raise RuntimeError('TCP_OWNER_TABLE_SIZE_INVALID')
            buf=ctypes.create_string_buffer(size.value)
            ret=get(buf,ctypes.byref(size),False,af,4,0)
            if ret: raise RuntimeError('TCP_OWNER_TABLE_QUERY_FAILED')
            count=ctypes.c_uint32.from_buffer_copy(buf.raw[:4]).value
            row_size=ctypes.sizeof(row_type)
            if count>100000 or 4+count*row_size>size.value: raise RuntimeError('TCP_OWNER_TABLE_CORRUPT')
            return [parse(row_type.from_buffer_copy(buf.raw,4+i*row_size)) for i in range(count)]

        def p4(r):
            ip=lambda v:socket.inet_ntoa(int(v).to_bytes(4,'little'))
            return TcpEndpoint(ip(r.local_addr),self._port(r.local_port),ip(r.remote_addr),
                               self._port(r.remote_port),int(r.pid),int(r.state),'IPv4')
        def p6(r):
            return TcpEndpoint(socket.inet_ntop(socket.AF_INET6,bytes(r.local_addr)),self._port(r.local_port),
                               socket.inet_ntop(socket.AF_INET6,bytes(r.remote_addr)),self._port(r.remote_port),
                               int(r.pid),int(r.state),'IPv6')
        rows=query(socket.AF_INET,Row4,p4)
        rows.extend(query(socket.AF_INET6,Row6,p6))
        return tuple(rows)


def correlate_flows(flows:dict[str,tuple[str,int,str,int]],
                    endpoints:tuple[TcpEndpoint,...],window_pids:dict[int,str])->dict:
    """Metadata-only, conservative attribution for read-only diagnostics."""
    counts={'PROVISIONAL':0,'AMBIGUOUS':0,'UNMATCHED':0}
    candidates={}
    for token,key in flows.items():
        matches=[row for row in endpoints if (row.local_ip,row.local_port,row.remote_ip,row.remote_port)==key
                 and row.pid in window_pids and row.state==5]
        matched={(row.pid,window_pids[row.pid]) for row in matches}
        status='PROVISIONAL' if len(matched)==1 else 'AMBIGUOUS' if len(matched)>1 else 'UNMATCHED'
        counts[status]+=1
        candidates[token]={'status':status,'candidate_count':len(matched)}
    return {'status':'NOT_ATTESTED','counts':counts,'candidates':candidates,'account_binding_verified':False}
