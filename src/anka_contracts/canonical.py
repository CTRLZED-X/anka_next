"""Stable Canonical v1 draft contracts. Historical candidates have NO mutation authority.

A draft represents evidence with explicit provenance, not an authoritative fact.  Its
immutable shape deliberately does not depend on any protocol version or parser.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

FactKind = Literal['ACTOR_RESOURCE_ABSOLUTE','ACTOR_HP_ABSOLUTE','ACTOR_COOLDOWN_SNAPSHOT']
_ALLOWED_KINDS = frozenset({'ACTOR_RESOURCE_ABSOLUTE','ACTOR_HP_ABSOLUTE','ACTOR_COOLDOWN_SNAPSHOT'})
_ALLOWED_RESOURCES = frozenset({'AP','MP','RANGE'})
_MAX_RESOURCE = {'AP':200,'MP':200,'RANGE':200}

@dataclass(frozen=True,slots=True)
class EvidenceRef:
    protocol_build: str
    adapter_id: str
    wire_name: str
    packet_number: int
    transport_generation: int
    flow_digest: str
    schema_revision: int = 1
    message_index: int = 0

    def __post_init__(self):
        if not self.protocol_build or len(self.protocol_build)>80:raise ValueError('CANONICAL_BUILD_INVALID')
        if not self.adapter_id or len(self.adapter_id)>96:raise ValueError('CANONICAL_ADAPTER_INVALID')
        if not self.wire_name.isascii() or not self.wire_name.replace("_", "").isalnum() or not 1<=len(self.wire_name)<=96:raise ValueError('CANONICAL_WIRE_INVALID')
        if type(self.packet_number) is not int or self.packet_number<0:raise ValueError('CANONICAL_PACKET_INVALID')
        if type(self.transport_generation) is not int or self.transport_generation<0:raise ValueError('CANONICAL_GENERATION_INVALID')
        if len(self.flow_digest)!=64 or any(c not in '0123456789abcdef' for c in self.flow_digest):raise ValueError('CANONICAL_FLOW_DIGEST_INVALID')
        if type(self.message_index) is not int or self.message_index<0:raise ValueError('CANONICAL_MESSAGE_INDEX_INVALID')
        if self.schema_revision!=1:raise ValueError('CANONICAL_SCHEMA_UNSUPPORTED')

@dataclass(frozen=True,slots=True)
class CanonicalDraft:
    """Immutable evidence draft. Every field is explicit, including missing context.

    No game state code is allowed to treat this as an admitted canonical event.
    """
    kind: FactKind
    actor_id: int
    evidence: EvidenceRef
    resource: str|None = None
    value: int|None = None
    maximum: int|None = None
    cooldowns: tuple[tuple[int,int], ...] = ()
    authority: str = field(default='HISTORICAL_CANDIDATE_ONLY',init=False)

    def __post_init__(self):
        if self.kind not in _ALLOWED_KINDS:raise ValueError('CANONICAL_KIND_UNSUPPORTED')
        if type(self.actor_id) is not int or self.actor_id==0 or not -(2**63)<self.actor_id<2**63:raise ValueError('CANONICAL_ACTOR_INVALID')
        if self.kind=='ACTOR_RESOURCE_ABSOLUTE':
            if self.resource not in _ALLOWED_RESOURCES or type(self.value) is not int or not 0<=self.value<=_MAX_RESOURCE[self.resource] or self.maximum is not None or self.cooldowns:
                raise ValueError('CANONICAL_RESOURCE_INVALID')
        elif self.kind=='ACTOR_HP_ABSOLUTE':
            if self.resource is not None or type(self.value) is not int or type(self.maximum) is not int or not 0<=self.value<=self.maximum<=1_000_000_000 or self.cooldowns:
                raise ValueError('CANONICAL_HP_INVALID')
        elif self.kind=='ACTOR_COOLDOWN_SNAPSHOT':
            if self.resource is not None or self.value is not None or self.maximum is not None or len(self.cooldowns)>200:
                raise ValueError('CANONICAL_COOLDOWN_INVALID')
            ids=set()
            for spell,remaining in self.cooldowns:
                if type(spell) is not int or spell<=0 or type(remaining) is not int or not 0<=remaining<=1000 or spell in ids:
                    raise ValueError('CANONICAL_COOLDOWN_INVALID')
                ids.add(spell)

@dataclass(frozen=True,slots=True)
class CanonicalAdmission:
    """Quarantine decision; no flag in this type permits changing live state."""
    status: str
    accepted_for_research: tuple[CanonicalDraft,...]
    reasons: tuple[str,...]
    committed_events: int = 0
    live_state_revision: int|None = None

    def __post_init__(self):
        if self.status not in ('STAGED_UNCERTIFIED','QUARANTINED','EMPTY') or self.committed_events!=0 or self.live_state_revision is not None:
            raise ValueError('CANONICAL_ADMISSION_AUTHORITY_FORBIDDEN')

# --- Definitive M1 boundary contract (additive to historical research DTOs) ---
from dataclasses import asdict as _asdict
from anka_contracts.evidence import EvidencePointer as StableEvidencePointer

@dataclass(frozen=True, slots=True)
class CanonicalEventEnvelope:
    event_id: str
    schema_major: int
    schema_minor: int
    semantic_kind: str
    account_id: str
    client_instance_id: str
    canonical_cursor: int
    source_adapter_release: str
    observed_client_build: str
    evidence: tuple[StableEvidencePointer, ...]
    payload: tuple[tuple[str, str], ...] = ()
    world_epoch: int | None = None
    fight_epoch: int | None = None
    turn_epoch: int | None = None

    def __post_init__(self):
        if not self.event_id.startswith('canonical-') or not self.account_id.startswith('acct-') or not self.client_instance_id.startswith('client-'):
            raise ValueError('INVALID_CANONICAL_IDENTITY')
        if type(self.schema_major) is not int or self.schema_major < 1 or type(self.schema_minor) is not int or self.schema_minor < 0:
            raise ValueError('INVALID_CANONICAL_SCHEMA')
        if type(self.semantic_kind) is not str or not self.semantic_kind or len(self.semantic_kind) > 96:
            raise ValueError('INVALID_CANONICAL_KIND')
        if type(self.canonical_cursor) is not int or self.canonical_cursor < 0:
            raise ValueError('INVALID_CANONICAL_CURSOR')
        if not self.source_adapter_release or not self.observed_client_build:
            raise ValueError('INVALID_CANONICAL_SOURCE')
        if not self.evidence or any(not isinstance(x, StableEvidencePointer) for x in self.evidence):
            raise ValueError('CANONICAL_EVIDENCE_REQUIRED')
        for value in (self.world_epoch,self.fight_epoch,self.turn_epoch):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError('INVALID_CANONICAL_EPOCH')
        if any(type(k) is not str or type(v) is not str for k,v in self.payload):
            raise ValueError('INVALID_CANONICAL_PAYLOAD')

    def to_dict(self) -> dict:
        obj=_asdict(self)
        obj['evidence']=[x.to_dict() for x in self.evidence]
        obj['payload']=[list(x) for x in self.payload]
        return obj


# --- Definitive M5 candidate semantic contract ---

@dataclass(frozen=True, slots=True)
class CanonicalCandidate:
    """Stable semantic candidate before durable Canonical authority.

    Protocol may propose this object, but only Canonical may assign a durable
    cursor and turn it into ``CanonicalEventEnvelope``.  No raw/obfuscated wire
    identifiers are part of this public DTO.
    """
    candidate_id: str
    semantic_kind: str
    account_id: str
    client_instance_id: str
    evidence: tuple[StableEvidencePointer, ...]
    payload: tuple[tuple[str, str], ...] = ()
    world_epoch: int | None = None
    fight_epoch: int | None = None
    turn_epoch: int | None = None

    def __post_init__(self):
        if type(self.candidate_id) is not str or not self.candidate_id.startswith('candidate-') or len(self.candidate_id) > 128:
            raise ValueError('INVALID_CANDIDATE_ID')
        if type(self.semantic_kind) is not str or not 1 <= len(self.semantic_kind) <= 96:
            raise ValueError('INVALID_CANDIDATE_KIND')
        if type(self.account_id) is not str or not self.account_id.startswith('acct-'):
            raise ValueError('INVALID_CANDIDATE_ACCOUNT')
        if type(self.client_instance_id) is not str or not self.client_instance_id.startswith('client-'):
            raise ValueError('INVALID_CANDIDATE_CLIENT')
        if not self.evidence or any(not isinstance(x, StableEvidencePointer) for x in self.evidence):
            raise ValueError('CANDIDATE_EVIDENCE_REQUIRED')
        if any(type(k) is not str or type(v) is not str for k,v in self.payload):
            raise ValueError('INVALID_CANDIDATE_PAYLOAD')
        for value in (self.world_epoch,self.fight_epoch,self.turn_epoch):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError('INVALID_CANDIDATE_EPOCH')

    def to_dict(self) -> dict:
        return {
            'candidate_id':self.candidate_id,'semantic_kind':self.semantic_kind,
            'account_id':self.account_id,'client_instance_id':self.client_instance_id,
            'evidence':[x.to_dict() for x in self.evidence],
            'payload':[list(x) for x in self.payload],
            'world_epoch':self.world_epoch,'fight_epoch':self.fight_epoch,'turn_epoch':self.turn_epoch,
        }


# --- Definitive M6 durable Canonical contracts ---
@dataclass(frozen=True, slots=True)
class CanonicalCommitReceipt:
    status: str
    batch_id: str
    event_count: int
    first_cursor: int | None
    last_cursor: int
    committed: bool
    decoder_checkpoint_sha256: str
    reason_code: str | None = None
    def __post_init__(self):
        if self.status not in ('COMMITTED','IDEMPOTENT_DUPLICATE','REJECTED','COMMIT_UNCERTAIN'):raise ValueError('INVALID_CANONICAL_COMMIT_STATUS')
        if not self.batch_id.startswith('batch-'):raise ValueError('INVALID_CANONICAL_COMMIT_BATCH')
        if type(self.event_count) is not int or self.event_count<0 or type(self.last_cursor) is not int or self.last_cursor<0:raise ValueError('INVALID_CANONICAL_COMMIT_CURSOR')
        if self.event_count==0 and self.first_cursor is not None:raise ValueError('INVALID_CANONICAL_EMPTY_FIRST_CURSOR')
        if self.event_count>0 and (type(self.first_cursor) is not int or self.first_cursor<=0 or self.first_cursor>self.last_cursor):raise ValueError('INVALID_CANONICAL_FIRST_CURSOR')
        if type(self.decoder_checkpoint_sha256) is not str or len(self.decoder_checkpoint_sha256)!=64:raise ValueError('INVALID_CANONICAL_DECODER_CHECKPOINT')
        if self.status in ('REJECTED','COMMIT_UNCERTAIN') and not self.reason_code:raise ValueError('CANONICAL_FAILURE_REASON_REQUIRED')

@dataclass(frozen=True, slots=True)
class CommittedBatch:
    events: tuple[CanonicalEventEnvelope,...]
    from_cursor: int
    through_cursor: int
    def __post_init__(self):
        if type(self.from_cursor) is not int or self.from_cursor<0 or type(self.through_cursor) is not int or self.through_cursor<self.from_cursor:raise ValueError('INVALID_COMMITTED_BATCH_RANGE')
        if self.events and tuple(e.canonical_cursor for e in self.events)!=tuple(range(self.events[0].canonical_cursor,self.events[0].canonical_cursor+len(self.events))):raise ValueError('NONCONTIGUOUS_COMMITTED_BATCH')
