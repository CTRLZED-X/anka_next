"""Independent, obviously synthetic packet captures; no real game traffic."""
from __future__ import annotations
import ipaddress
import struct

def block(kind:int, body:bytes, endian:str='<') -> bytes:
    padded=body+b'\x00'*((-len(body))%4)
    total=12+len(padded)
    return struct.pack(endian+'II',kind,total)+padded+struct.pack(endian+'I',total)

def pcapng(*packets:bytes, endian:str='<', linktype:int=1)->bytes:
    bom=struct.pack(endian+'I',0x1a2b3c4d)
    shb=block(0x0a0d0d0a,bom+struct.pack(endian+'HHq',1,0,-1),endian)
    idb=block(1,struct.pack(endian+'HHI',linktype,0,65535),endian)
    epbs=b''
    for p in packets:
        epbs+=block(6,struct.pack(endian+'IIIII',0,0,0,len(p),len(p))+p,endian)
    return shb+idb+epbs

def packet(seq:int=100,flags:int=0x18,data:bytes=b'test',sport:int=55000,dport:int=40400,reverse:bool=False,vlan:int=0)->bytes:
    if reverse:
        sport,dport=dport,sport
    tcp=struct.pack('!HHII',sport,dport,seq,0)+bytes([0x50,flags])+b'\x00\x00\x00\x00\x00\x00'
    assert len(tcp)==20
    ip_payload=tcp+data
    ip=(bytes([0x45,0])+struct.pack('!H',20+len(ip_payload))+b'\x00\x01'+b'\x00\x00'+
        bytes([64,6])+b'\x00\x00'+ipaddress.IPv4Address('192.0.2.2' if reverse else '192.0.2.1').packed+
        ipaddress.IPv4Address('192.0.2.1' if reverse else '192.0.2.2').packed)
    eth=b'\x02'*6+b'\x04'*6+b'\x08\x00'
    if vlan:eth=eth[:12]+b'\x81\x00\x00\x04\x08\x00'
    return eth+ip+ip_payload

def sample_capture()->bytes:
    return pcapng(packet(seq=100,flags=2,data=b''),
                  packet(seq=800,flags=0x12,data=b'',reverse=True),
                  packet(seq=101,flags=0x18,data=b'NOT_GAME'),
                  packet(seq=801,flags=0x18,data=b'SYNTHETIC',reverse=True))
