"""Exact opaque-wire fingerprints.  Exact means exact: no prefix/name generalization."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256

@dataclass(frozen=True, slots=True)
class OpaqueFingerprint:
    direction: str
    wire_name: str
    body_length: int
    body_sha256: str
    rationale: str = 'EVIDENCE_CERTIFIED_ZERO_CANONICAL_EFFECT'
    def __post_init__(self):
        if self.direction not in ('client_to_server','server_to_client'): raise ValueError('OPAQUE_DIRECTION_INVALID')
        if type(self.wire_name) is not str or not self.wire_name.isascii() or not self.wire_name.replace('_','').isalnum(): raise ValueError('OPAQUE_WIRE_NAME_INVALID')
        if type(self.body_length) is not int or self.body_length<0: raise ValueError('OPAQUE_LENGTH_INVALID')
        if type(self.body_sha256) is not str or len(self.body_sha256)!=64 or any(c not in '0123456789abcdef' for c in self.body_sha256): raise ValueError('OPAQUE_HASH_INVALID')

    @classmethod
    def from_body(cls,direction:str,wire_name:str,body:bytes)->'OpaqueFingerprint':
        return cls(direction,wire_name,len(body),sha256(body).hexdigest())

    def matches(self,direction:str,wire_name:str,body:bytes)->bool:
        return self.direction==direction and self.wire_name==wire_name and self.body_length==len(body) and self.body_sha256==sha256(body).hexdigest()

class OpaquePolicy:
    def __init__(self, fingerprints=()):
        rows=tuple(fingerprints)
        keys={(x.direction,x.wire_name,x.body_length,x.body_sha256) for x in rows}
        if len(keys)!=len(rows): raise ValueError('OPAQUE_FINGERPRINT_DUPLICATE')
        self._rows=rows
    def accepts(self,direction:str,wire_name:str,body:bytes)->bool:
        return any(x.matches(direction,wire_name,body) for x in self._rows)
    def fingerprints(self)->tuple[OpaqueFingerprint,...]: return self._rows
