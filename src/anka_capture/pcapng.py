from __future__ import annotations

import ipaddress
import struct
from pathlib import Path

from anka_contracts.capture import CapturedTcpSegment


def _reject_selected_ipv6_tcp(packet: bytes, offset: int, server_ports: set[int]) -> None:
    """Fail closed when evidence contains selected-port IPv6 TCP traffic.

    The current Windows live capture backend only admits Scapy IPv4 ``IP/TCP``
    packets into ANKA. Treating IPv6 game traffic as absent during offline replay
    would therefore certify a transport path production cannot consume.
    """
    if len(packet) < offset + 40:
        raise ValueError("invalid/truncated IPv6 packet in certification capture")
    ip = packet[offset:]
    if ip[0] >> 4 != 6:
        raise ValueError("invalid IPv6 version in certification capture")
    payload_len = int.from_bytes(ip[4:6], "big")
    end = 40 + payload_len if payload_len else len(ip)
    if len(ip) < end:
        raise ValueError("truncated IPv6 payload in certification capture")
    ip = ip[:end]
    next_header = int(ip[6])
    cursor = 40
    # Common IPv6 extension headers. Parsing them here is only for determining
    # whether a selected TCP port is present; live runtime support remains absent.
    while next_header in {0, 43, 44, 51, 60}:
        if next_header == 44:  # Fragment header
            if len(ip) < cursor + 8:
                raise ValueError("truncated IPv6 fragment header in certification capture")
            following = int(ip[cursor])
            fragment_field = int.from_bytes(ip[cursor + 2:cursor + 4], "big")
            # The fragment offset occupies bits 3..15 and M occupies bit 0.
            # Non-initial fragments have NO TCP ports. Treating their first
            # payload bytes as ports silently omits potentially selected game
            # traffic. Likewise the first fragment with M=1 cannot establish
            # a complete transport payload without reassembly.
            # Explicit UDP/ICMP fragments cannot contain TCP; those remain
            # outside the selected TCP evidence scope.
            if fragment_field & 0x0006:
                raise ValueError("invalid reserved IPv6 fragment flag bits in certification capture")
            if fragment_field & 0xFFF9 and following not in (17, 58):
                raise ValueError("fragmented IPv6 TCP or opaque upper-layer traffic unsupported in certification capture")
            next_header = following
            cursor += 8
            continue
        if len(ip) < cursor + 2:
            raise ValueError("truncated IPv6 extension header in certification capture")
        following = int(ip[cursor])
        if next_header == 51:  # Authentication Header: (Hdr Ext Len + 2) * 4
            size = (int(ip[cursor + 1]) + 2) * 4
        else:
            size = (int(ip[cursor + 1]) + 1) * 8
        if size <= 0 or len(ip) < cursor + size:
            raise ValueError("truncated IPv6 extension payload in certification capture")
        next_header = following
        cursor += size
    if next_header != 6:
        return
    if len(ip) < cursor + 4:
        raise ValueError("truncated IPv6 TCP header in certification capture")
    sport = int.from_bytes(ip[cursor:cursor + 2], "big")
    dport = int.from_bytes(ip[cursor + 2:cursor + 4], "big")
    if sport in server_ports or dport in server_ports:
        raise ValueError(
            "selected-port IPv6 TCP traffic is unsupported by the current live capture runtime; "
            "do not certify this evidence as equivalent to the production transport path"
        )


def _ethernet_ipv4_tcp(packet:bytes,packet_number:int,server_ports:set[int])->CapturedTcpSegment|None:
    if len(packet)<14: raise ValueError('truncated Ethernet header')
    offset=14
    ethertype=int.from_bytes(packet[12:14],'big')
    for _ in range(2):
        if ethertype not in {0x8100,0x88A8,0x9100}: break
        if len(packet)<offset+4:
            raise ValueError('truncated VLAN header')
        ethertype=int.from_bytes(packet[offset+2:offset+4],'big'); offset += 4
    if ethertype in {0x8100,0x88A8,0x9100}:
        raise ValueError('unsupported excessive VLAN stack')
    if ethertype == 0x86DD:
        _reject_selected_ipv6_tcp(packet, offset, server_ports)
        return None
    if ethertype!=0x0800: return None
    if len(packet)<offset+20:
        raise ValueError('invalid/truncated IPv4 packet in certification capture')
    captured_ip=packet[offset:]
    version_ihl=captured_ip[0]
    if version_ihl>>4 != 4: raise ValueError('invalid Ethernet IPv4 header')
    ihl=(version_ihl & 0x0F)*4
    if ihl<20 or len(captured_ip)<ihl:
        raise ValueError('invalid/truncated IPv4 header in certification capture')
    if captured_ip[9]!=6: return None

    fragment_field=int.from_bytes(captured_ip[6:8],'big')
    fragment_offset=fragment_field & 0x1FFF
    more_fragments=bool(fragment_field & 0x2000)
    if fragment_offset:
        # A non-initial TCP fragment no longer contains the ports, so offline
        # replay cannot prove whether it belongs to a selected Dofus flow.
        raise ValueError('non-initial fragmented IPv4 TCP prevents certification completeness')

    # The first fragment / normal datagram contains the TCP ports. Inspect them
    # before enforcing payload-length details so unrelated host-offload traffic
    # (for example TLS packets with IPv4 total_length=0 in Npcap captures) does
    # not invalidate Dofus evidence.
    if len(captured_ip)<ihl+4:
        raise ValueError('invalid/truncated TCP ports in certification capture')
    captured_tcp=captured_ip[ihl:]
    sport=int.from_bytes(captured_tcp[0:2],'big'); dport=int.from_bytes(captured_tcp[2:4],'big')
    if sport not in server_ports and dport not in server_ports:
        return None
    if more_fragments:
        raise ValueError('fragmented selected-port IPv4 TCP is unsupported for certification replay')

    total_len=int.from_bytes(captured_ip[2:4],'big')
    if total_len == 0:
        # Windows/Npcap may expose transmit-offload packets before the NIC fills
        # the IPv4 total-length field. The bytes are still present in the capture;
        # use the captured frame length for selected traffic rather than treating
        # this known host-offload representation as truncation.
        total_len=len(captured_ip)
    if total_len<ihl or len(captured_ip)<total_len:
        raise ValueError('invalid/truncated selected-port IPv4 payload in certification capture')
    ip=captured_ip[:total_len]  # exclude Ethernet padding: critical for byte-exact stream reconstruction
    src=str(ipaddress.IPv4Address(ip[12:16])); dst=str(ipaddress.IPv4Address(ip[16:20]))
    tcp=ip[ihl:]
    if len(tcp)<20: raise ValueError('invalid/truncated selected-port TCP header in certification capture')
    data_offset=(tcp[12]>>4)*4
    if data_offset<20 or len(tcp)<data_offset: raise ValueError('invalid selected-port TCP data offset in certification capture')
    seq=int.from_bytes(tcp[4:8],'big')
    flags=int(tcp[13])
    payload=bytes(tcp[data_offset:])
    if not payload and not (flags & (0x01 | 0x02 | 0x04)): return None
    if sport in server_ports:
        direction='server_to_client'; server=f'{src}:{sport}'; client=f'{dst}:{dport}'
    else:
        direction='client_to_server'; server=f'{dst}:{dport}'; client=f'{src}:{sport}'
    return CapturedTcpSegment(flow_id=f'{client}<->{server}',direction=direction,seq=seq,payload=payload,packet_number=packet_number,tcp_flags=flags)


def _options(buf: bytes, endian: str):
    """Read 32-bit-aligned PCAPNG options without crossing the block boundary."""
    pos=0
    while pos<len(buf):
        if pos+4>len(buf):
            raise ValueError('truncated PCAPNG option header')
        kind,length=struct.unpack_from(endian+'HH',buf,pos)
        pos+=4
        if kind==0:
            if length!=0 or pos!=len(buf):
                raise ValueError('invalid PCAPNG end-of-options marker')
            return
        padded=(length+3)&~3
        if pos+padded>len(buf):
            raise ValueError('truncated PCAPNG option contents')
        yield kind,buf[pos:pos+length]
        pos+=padded


def _reject_reported_packet_loss(kind: int, body: bytes, endian: str,
                                 linktypes: dict[int,int]) -> None:
    """Reject loss metadata relevant to capture completeness, never infer zero loss.

    EPB option 4 is the per-packet drop count. ISB options 5 and 7
    are cumulative interface/OS loss. Obsolete PB has a 16-bit counter
    (0xffff means unknown, not zero). Any positive count quarantines the
    complete capture, because missing packets cannot be assigned to a
    selected TCP flow without independent evidence.
    """
    if kind==6:
        if len(body)<20:raise ValueError('truncated PCAPNG enhanced packet for loss audit')
        caplen=struct.unpack_from(endian+'I',body,12)[0]
        options_start=20+((caplen+3)&~3)
        if options_start>len(body):
            raise ValueError('truncated PCAPNG enhanced packet option boundary')
        options=body[options_start:]
        watch={4}
    elif kind==5:
        if len(body)<12:raise ValueError('truncated PCAPNG interface statistics')
        interface_id=struct.unpack_from(endian+'I',body)[0]
        if interface_id not in linktypes:
            raise ValueError('PCAPNG statistics reference unknown interface')
        options=body[12:]
        watch={5,7}
    elif kind==2:
        if len(body)<20:raise ValueError('truncated PCAPNG legacy packet for loss audit')
        drops=struct.unpack_from(endian+'H',body,2)[0]
        if drops not in (0,0xffff):
            raise ValueError('PCAPNG reported lost packets in legacy packet block')
        return
    else:
        return
    seen=set()
    for option_code,value in _options(options,endian):
        if option_code not in watch:continue
        if option_code in seen or len(value)!=8:
            raise ValueError('invalid/duplicate PCAPNG loss metadata')
        seen.add(option_code)
        if struct.unpack(endian+'Q',value)[0]>0:
            raise ValueError('PCAPNG reported lost packets; evidence incomplete')



def _pcapng_blocks(raw: bytes):
    """Iterate whole, correctly bounded PCAPNG sections for BOTH readers.

    A Section Header Block declares the byte order, format revision, and
    optionally the exact length of the following section (excluding the SHB).
    Refuse orphan packet records, unsupported versions and silently truncated
    or overlong declared sections, even if individual packet bytes look valid.
    """
    pos = 0
    endian = '<'
    saw_section = False
    declared_end: int | None = None
    magic = b'\x0a\x0d\x0d\x0a'
    if not raw or raw[:4] != magic:
        raise ValueError('PCAPNG first block must be a section header')
    while pos < len(raw):
        if pos + 12 > len(raw):
            raise ValueError('invalid/truncated PCAPNG trailing bytes')
        section_header = raw[pos:pos+4] == magic
        if declared_end is not None:
            if pos > declared_end or (pos == declared_end and not section_header):
                raise ValueError('PCAPNG blocks after declared section end')
            if pos < declared_end and section_header:
                raise ValueError('PCAPNG section ended earlier than declared')
        if section_header:
            if pos + 28 > len(raw):
                raise ValueError('invalid/truncated PCAPNG section header')
            bom = raw[pos+8:pos+12]
            if bom == b'\x4d\x3c\x2b\x1a': endian = '<'
            elif bom == b'\x1a\x2b\x3c\x4d': endian = '>'
            else: raise ValueError('invalid PCAPNG byte-order magic')
        elif not saw_section:
            raise ValueError('PCAPNG packet before section header')
        block_type = (0x0a0d0d0a if section_header else
                      struct.unpack_from(endian+'I', raw, pos)[0])
        total = struct.unpack_from(endian+'I', raw, pos+4)[0]
        if total < 12 or total % 4 != 0 or pos + total > len(raw):
            raise ValueError('invalid/truncated PCAPNG block')
        if struct.unpack_from(endian+'I', raw, pos+total-4)[0] != total:
            raise ValueError('PCAPNG block length trailer mismatch')
        if section_header:
            if total < 28:
                raise ValueError('invalid/truncated PCAPNG section header')
            major, minor, section_length = struct.unpack_from(endian+'HHq', raw, pos+12)
            if (major, minor) != (1, 0):
                raise ValueError('unsupported PCAPNG section version')
            if section_length < -1 or (section_length >= 0 and section_length % 4):
                raise ValueError('invalid PCAPNG section length')
            declared_end = (None if section_length == -1 else
                            pos + total + section_length)
            if declared_end is not None and declared_end > len(raw):
                raise ValueError('PCAPNG declared section exceeds capture length')
            saw_section = True
        elif declared_end is not None and pos + total > declared_end:
            raise ValueError('PCAPNG block crosses declared section boundary')
        yield block_type, raw[pos+8:pos+total-4], endian
        pos += total
    if not saw_section or (declared_end is not None and pos != declared_end):
        raise ValueError('PCAPNG declared section length mismatch')

def read_pcapng_tcp_segments(path:str|Path,*,server_ports:set[int],raw:bytes|None=None)->list[CapturedTcpSegment]:
    raw=Path(path).read_bytes() if raw is None else raw
    linktypes: dict[int, int] = {}
    segments = []
    packet_number = 0
    for block_type, body, endian in _pcapng_blocks(raw):
        if block_type == 0x0A0D0D0A:
            # Interfaces are section-local. Even different-endian sections
            # can reuse identifier zero with an unrelated linktype.
            linktypes.clear()
        _reject_reported_packet_loss(block_type,body,endian,linktypes)
        if block_type == 1:
            if len(body) < 8:
                raise ValueError('invalid/truncated PCAPNG interface description')
            interface_id=len(linktypes); linktypes[interface_id]=struct.unpack_from(endian+'H',body,0)[0]
        elif block_type == 6:
            # Packet numbers in oracle evidence are capture-wide frame numbers.
            # Advance for every packet record. Packet-bearing link types that the
            # production-equivalent replay cannot parse are rejected below rather
            # than silently omitted from certification evidence.
            if len(body) < 20:
                raise ValueError('invalid/truncated PCAPNG enhanced packet block')
            packet_number += 1
            interface_id=struct.unpack_from(endian+'I',body,0)[0]
            if interface_id not in linktypes:
                raise ValueError('PCAPNG enhanced packet references unknown interface')
            cap_len=struct.unpack_from(endian+'I',body,12)[0]
            original_len=struct.unpack_from(endian+'I',body,16)[0]
            if cap_len != original_len or cap_len > len(body)-20:
                raise ValueError('invalid/truncated PCAPNG enhanced packet data')
            packet=body[20:20+cap_len]
            linktype = linktypes.get(interface_id)
            if linktype != 1:
                raise ValueError(f'unsupported PCAPNG linktype {linktype} on packet record; certification completeness cannot be proven')
            segment=_ethernet_ipv4_tcp(packet,packet_number,server_ports)
            if segment is not None: segments.append(segment)
        elif block_type == 3:
            if len(body) < 4:
                raise ValueError('invalid/truncated PCAPNG simple packet block')
            packet_number += 1
            if 0 not in linktypes:
                raise ValueError('PCAPNG simple packet requires interface 0')
            linktype = linktypes.get(0)
            if linktype != 1:
                raise ValueError(f'unsupported PCAPNG linktype {linktype} on simple packet record; certification completeness cannot be proven')
            original_len=struct.unpack_from(endian+'I',body,0)[0]
            if original_len > len(body)-4 or len(body)-4 - original_len > 3:
                raise ValueError('invalid/truncated PCAPNG simple packet data')
            packet=body[4:4+original_len]
            segment=_ethernet_ipv4_tcp(packet,packet_number,server_ports)
            if segment is not None: segments.append(segment)
        elif block_type == 2:
            # Obsolete Packet Block is still legal PCAPNG and may be emitted by
            # conversion tools. It must participate in capture-wide numbering.
            if len(body) < 20:
                raise ValueError('invalid/truncated PCAPNG packet block')
            packet_number += 1
            interface_id=struct.unpack_from(endian+'H',body,0)[0]
            if interface_id not in linktypes:
                raise ValueError('PCAPNG packet references unknown interface')
            cap_len=struct.unpack_from(endian+'I',body,12)[0]
            original_len=struct.unpack_from(endian+'I',body,16)[0]
            if cap_len != original_len or cap_len > len(body)-20:
                raise ValueError('invalid/truncated PCAPNG packet data')
            packet=body[20:20+cap_len]
            linktype = linktypes.get(interface_id)
            if linktype != 1:
                raise ValueError(f'unsupported PCAPNG linktype {linktype} on packet record; certification completeness cannot be proven')
            segment=_ethernet_ipv4_tcp(packet,packet_number,server_ports)
            if segment is not None: segments.append(segment)
    return segments


def pcapng_packet_count(path: str | Path, *, raw: bytes | None = None) -> int:
    """Return the number of packet records in a PCAPNG file.

    Packet numbering in the evidence/oracle contract is the capture-wide packet
    index, not merely the index of packets that happened to decode as Dofus TCP.
    Keeping this parser here ensures oracle alignment is checked against the same
    PCAPNG block semantics as live-decoding replay.
    """
    raw = Path(path).read_bytes() if raw is None else raw
    packet_count = 0
    linktypes: dict[int, int] = {}
    for block_type, body, endian in _pcapng_blocks(raw):
        if block_type == 0x0A0D0D0A:
            linktypes.clear()
        if block_type == 1 and len(body) < 8:
            raise ValueError("invalid/truncated PCAPNG interface description")
        if block_type == 1:
            linktypes[len(linktypes)]=struct.unpack_from(endian+'H',body)[0]
        _reject_reported_packet_loss(block_type,body,endian,linktypes)
        if block_type == 6:
            if len(body) < 20:
                raise ValueError("invalid/truncated PCAPNG enhanced packet block")
            cap_len = struct.unpack_from(endian + "I", body, 12)[0]
            original_len = struct.unpack_from(endian + "I", body, 16)[0]
            if cap_len != original_len or cap_len > len(body) - 20:
                raise ValueError("invalid/truncated PCAPNG enhanced packet data")
            packet_count += 1
        elif block_type == 3:
            if len(body) < 4:
                raise ValueError("invalid/truncated PCAPNG simple packet block")
            packet_count += 1
        elif block_type == 2:
            if len(body) < 20:
                raise ValueError("invalid/truncated PCAPNG packet block")
            cap_len = struct.unpack_from(endian + "I", body, 12)[0]
            original_len = struct.unpack_from(endian + "I", body, 16)[0]
            if cap_len != original_len or cap_len > len(body) - 20:
                raise ValueError("invalid/truncated PCAPNG packet data")
            packet_count += 1
    return packet_count


