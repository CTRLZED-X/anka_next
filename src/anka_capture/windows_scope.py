"""Internal Windows capture-scope derivation from process ownership evidence.

The Capture system receives only primitive candidate PIDs plus TCP owner rows;
it does not import Client. Selecting which process generations are eligible is
an application/client composition responsibility. Endpoint values remain in
memory; only aggregate receipts may enter diagnostics.
"""
from __future__ import annotations
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Callable, Iterable
from anka_capture.windows_flows import TcpEndpoint

FlowKey = tuple[str,int,str,int]  # client_ip, client_port, server_ip, server_port


def _ip(value:str) -> str:
    """Canonical textual IP form so Windows and Scapy agree on IPv6 keys."""
    if not isinstance(value,str):
        raise ValueError('INVALID_CAPTURE_ENDPOINT_IP')
    try:
        return ip_address(value.split('%',1)[0]).compressed
    except ValueError as exc:
        raise ValueError('INVALID_CAPTURE_ENDPOINT_IP') from exc


def _externally_scopable(remote:str) -> bool:
    """Reject endpoint classes that should never widen automatic game capture."""
    try:
        value=ip_address(remote.split('%',1)[0])
    except (ValueError,AttributeError):
        return False
    return not (value.is_unspecified or value.is_multicast or value.is_loopback)


@dataclass(frozen=True, slots=True)
class WindowsCaptureScope:
    server_ports: tuple[int, ...]
    local_ips: tuple[str, ...]
    allowed_flows: tuple[FlowKey, ...]
    interface: str | None
    mode: str
    stable_processes: int

    def safe_receipt(self) -> dict:
        return {
            'status':'READY' if self.server_ports and self.allowed_flows else 'NO_TCP_SCOPE',
            'mode':self.mode,'server_port_count':len(self.server_ports),
            'endpoint_selector_count':len(self.allowed_flows),
            'local_ip_count':len(self.local_ips),'stable_processes':self.stable_processes,
            'interface_mode':'EXPLICIT_OVERRIDE' if self.interface else 'AUTO_RESOLUTION_REQUIRED',
            'endpoint_values_exposed':False,
        }


def derive_windows_capture_scope(candidate_pids: set[int] | frozenset[int],
                                 rows: Iterable[TcpEndpoint], *,
                                 override_ports: tuple[int,...]=(),
                                 override_interface: str|None=None) -> WindowsCaptureScope:
    if not isinstance(candidate_pids,(set,frozenset)) or any(type(x) is not int or x <= 0 for x in candidate_pids):
        raise ValueError('INVALID_CAPTURE_CANDIDATE_PIDS')
    if not isinstance(override_ports,tuple) or len(override_ports)>32 or any(type(p) is not int or not 1<=p<=65535 for p in override_ports):
        raise ValueError('INVALID_CAPTURE_OVERRIDE_PORTS')
    if override_interface is not None and (not isinstance(override_interface,str) or not override_interface.strip()):
        raise ValueError('INVALID_CAPTURE_OVERRIDE_INTERFACE')
    port_filter=set(override_ports)
    normalized=[]
    for row in rows:
        if not isinstance(row,TcpEndpoint) or row.state != 5 or row.pid not in candidate_pids:
            continue
        if not (1<=row.local_port<=65535 and 1<=row.remote_port<=65535):
            continue
        if port_filter and row.remote_port not in port_filter:
            continue
        if not _externally_scopable(row.remote_ip):
            continue
        try:
            local=_ip(row.local_ip); remote=_ip(row.remote_ip)
        except ValueError:
            continue
        normalized.append((local,row.local_port,remote,row.remote_port,row.pid))
    flows=tuple(sorted({(local,lport,remote,rport) for local,lport,remote,rport,_pid in normalized}))
    ports=tuple(sorted(port_filter or {rport for _local,_lport,_remote,rport,_pid in normalized}))
    processes=len({_pid for *_prefix,_pid in normalized})
    if len(ports)>32:
        return WindowsCaptureScope((),(),(),override_interface,'TOO_MANY_SERVER_PORTS',processes)
    if len(flows)>64:
        return WindowsCaptureScope((),(),(),override_interface,'TOO_MANY_ENDPOINT_SELECTORS',processes)
    ips=tuple(sorted({local for local,_lport,_remote,_rport,_pid in normalized}))
    mode='EXPLICIT_OVERRIDE' if override_ports or override_interface else 'AUTO_PROCESS_TCP'
    return WindowsCaptureScope(ports,ips,flows,override_interface,mode,processes)


def resolve_scapy_interface(local_ips: tuple[str,...], explicit: str|None=None, *,
                            ipv4_inventory: Callable[[],Iterable[tuple[str,str]]]|None=None,
                            ipv6_inventory: Callable[[],Iterable[tuple[str,str]]]|None=None) -> str|None:
    """Resolve all observed local addresses to one Scapy interface.

    A default-interface guess is deliberately not returned. If the candidate
    flows span multiple adapters or Scapy cannot prove the mapping, callers
    must block the sample instead of producing misleading empty evidence.

    Inventory rows are ``(canonical_ip, interface_name)``. Injectable providers
    keep the rule fully testable without Windows/Scapy.
    """
    if explicit:
        return explicit
    if not isinstance(local_ips,tuple) or not local_ips:
        return None
    try:
        wanted={_ip(value) for value in local_ips}
    except ValueError:
        return None
    rows=[]
    try:
        if ipv4_inventory is None:
            from scapy.all import get_if_list, get_if_addr
            def ipv4_inventory():
                out=[]
                for iface in get_if_list():
                    try:
                        address=get_if_addr(iface)
                        if address and address!='0.0.0.0': out.append((address,str(iface)))
                    except Exception:
                        continue
                return out
        if ipv6_inventory is None:
            try:
                from scapy.arch import in6_getifaddr
                def ipv6_inventory():
                    out=[]
                    for address,_scope,iface in in6_getifaddr():
                        name=getattr(iface,'name',None) or str(iface)
                        if address: out.append((str(address).split('%',1)[0],str(name)))
                    return out
            except Exception:
                ipv6_inventory=lambda:()
        rows.extend(ipv4_inventory())
        rows.extend(ipv6_inventory())
    except Exception:
        return None
    by_ip={}
    for address,iface in rows:
        try: canonical=_ip(address)
        except ValueError: continue
        if not isinstance(iface,str) or not iface.strip(): continue
        by_ip.setdefault(canonical,set()).add(iface.strip())
    # Every observed local address must map uniquely and all must resolve to the
    # same interface. Otherwise one exact-flow BPF would be incomplete.
    matches=[]
    for address in wanted:
        names=by_ip.get(address,set())
        if len(names)!=1:return None
        matches.append(next(iter(names)))
    return matches[0] if len(set(matches))==1 else None
