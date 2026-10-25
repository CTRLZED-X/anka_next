"""P58 input contracts for an UNTRUSTED, read-only admission rehearsal.

Neither a self-declared protocol version nor caller-provided bytes establish
current-client certification. These objects cannot become durable events.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from hashlib import sha256
from anka_contracts.canonical import CanonicalDraft, EvidenceRef


def _digest(value: str) -> bool:
    return type(value) is str and len(value)==64 and all(c in '0123456789abcdef' for c in value)

def _build(value: str) -> bool:
    return type(value) is str and 1<=len(value)<=96 and all(
        c.isascii() and (c.isalnum() or c in '._- +') for c in value)

def _token(value: str) -> bool:
    return type(value) is str and 1<=len(value)<=100 and all(
        c.isascii() and (c.isalnum() or c in '._-') for c in value)

@dataclass(frozen=True, slots=True)
class AdmissionScope:
    """Caller-provided scope, never an authenticated live-session identity."""
    session_id: str
    account_id: str
    account_generation: int
    fight_id: str
    protocol_build: str
    adapter_id: str
    flow_digest: str
    transport_generation: int
    process_generation: int
    window_generation: int
    capture_sha256: str
    authority: str = field(default='UNTRUSTED_ADMISSION_REHEARSAL', init=False)

    def __post_init__(self):
        if not all(_token(x) for x in (self.session_id,self.account_id,self.fight_id,self.adapter_id)) or not _build(self.protocol_build):
            raise ValueError('P58_SCOPE_TOKEN_INVALID')
        if not _digest(self.flow_digest) or not _digest(self.capture_sha256):
            raise ValueError('P58_SCOPE_DIGEST_INVALID')
        for value in (self.account_generation,self.transport_generation,self.process_generation,self.window_generation):
            if type(value) is not int or value<0 or value>=2**63:
                raise ValueError('P58_SCOPE_GENERATION_INVALID')

@dataclass(frozen=True, slots=True)
class UntrustedPacketClaim:
    """One captured message body, retaining exact byte hash for replay checking.

    The caller supplies these bytes and the evidence ref: a valid checksum is
    NOT proof that this packet was emitted by a game server.
    """
    evidence: EvidenceRef
    direction: str
    body: bytes
    body_sha256: str
    capture_sha256: str
    origin: str = field(default='UNTRUSTED_CAPTURE_CLAIM', init=False)

    def __post_init__(self):
        if not isinstance(self.evidence,EvidenceRef) or self.direction not in ('server_to_client','client_to_server'):
            raise ValueError('P58_PACKET_SCOPE_INVALID')
        if type(self.body) is not bytes or len(self.body)>16_384 or not _digest(self.body_sha256) or not _digest(self.capture_sha256):
            raise ValueError('P58_PACKET_BODY_INVALID')
        if sha256(self.body).hexdigest()!=self.body_sha256:
            raise ValueError('P58_PACKET_BODY_HASH_MISMATCH')

@dataclass(frozen=True, slots=True)
class UntrustedCharacterClaim:
    """A *claim* about a local actor, not verified character/breed evidence."""
    evidence: EvidenceRef
    actor_id: int
    character_name_sha256: str
    origin: str = field(default='UNTRUSTED_CHARACTER_CLAIM', init=False)

    def __post_init__(self):
        if not isinstance(self.evidence,EvidenceRef) or type(self.actor_id) is not int or self.actor_id==0 or abs(self.actor_id)>=2**63:
            raise ValueError('P58_CHARACTER_ACTOR_INVALID')
        if not _digest(self.character_name_sha256):
            raise ValueError('P58_CHARACTER_HASH_INVALID')

@dataclass(frozen=True, slots=True)
class AdmissionRehearsal:
    """Bounded inputs for auditing provenance ONLY, without a certification API."""
    scope: AdmissionScope
    character: UntrustedCharacterClaim
    packets: tuple[UntrustedPacketClaim,...]
    drafts: tuple[CanonicalDraft,...]
    authority: str = field(default='UNTRUSTED_ADMISSION_REHEARSAL', init=False)

    def __post_init__(self):
        if not isinstance(self.scope,AdmissionScope) or not isinstance(self.character,UntrustedCharacterClaim):
            raise ValueError('P58_REHEARSAL_SCOPE_INVALID')
        if type(self.packets) is not tuple or not 1<=len(self.packets)<=512 or any(type(p) is not UntrustedPacketClaim for p in self.packets):
            raise ValueError('P58_REHEARSAL_PACKET_LIMIT_OR_TYPE')
        if type(self.drafts) is not tuple or not 1<=len(self.drafts)<=2048 or any(type(d) is not CanonicalDraft for d in self.drafts):
            raise ValueError('P58_REHEARSAL_DRAFT_LIMIT_OR_TYPE')
