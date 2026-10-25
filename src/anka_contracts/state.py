"""P8 synthetic state-event contract; no production/live admission authority.

Real protocol observations must undergo independent current-build certification in a
future milestone. This class is deliberately NOT an adapter for CanonicalDraft.
"""
from __future__ import annotations
from dataclasses import dataclass,field
from typing import Literal

StateKind=Literal['FIGHT_STARTED','ACTOR_SEEN','ACTOR_RESOURCE_SET','ACTOR_HP_SET',
                  'ACTOR_POSITION_SET','ACTOR_COOLDOWNS_SET','TURN_STARTED','TURN_ENDED','FIGHT_ENDED']
KINDS=frozenset({'FIGHT_STARTED','ACTOR_SEEN','ACTOR_RESOURCE_SET','ACTOR_HP_SET',
 'ACTOR_POSITION_SET','ACTOR_COOLDOWNS_SET','TURN_STARTED','TURN_ENDED','FIGHT_ENDED'})

@dataclass(frozen=True,slots=True)
class OfflineStateEvent:
    """Typed synthetic event for exercising the journal/reducer, NEVER live input."""
    event_id:str
    session_id:str
    account_id:str
    account_generation:int
    fight_id:str
    sequence:int
    kind:StateKind
    actor_id:int|None=None
    resource:str|None=None
    value:int|None=None
    maximum:int|None=None
    cooldowns:tuple[tuple[int,int],...]=()
    origin: str=field(default='SYNTHETIC_FIXTURE_ONLY',init=False)

    def __post_init__(self):
        def token(value,max_len=100):
            return isinstance(value,str) and 0<len(value)<=max_len and all(c.isascii() and (c.isalnum() or c in '_-.') for c in value)
        if not all(token(x) for x in (self.event_id,self.session_id,self.account_id,self.fight_id)):
            raise ValueError('STATE_EVENT_IDENTITY_INVALID')
        if type(self.account_generation) is not int or self.account_generation<0 or type(self.sequence) is not int or self.sequence<=0:
            raise ValueError('STATE_EVENT_ORDER_INVALID')
        if self.kind not in KINDS:raise ValueError('STATE_EVENT_KIND_INVALID')
        needs_actor=self.kind in {'ACTOR_SEEN','ACTOR_RESOURCE_SET','ACTOR_HP_SET','ACTOR_POSITION_SET','ACTOR_COOLDOWNS_SET','TURN_STARTED','TURN_ENDED'}
        if needs_actor!=(self.actor_id is not None):raise ValueError('STATE_EVENT_ACTOR_INVALID')
        if self.actor_id is not None and (type(self.actor_id) is not int or self.actor_id==0 or abs(self.actor_id)>=2**63):
            raise ValueError('STATE_EVENT_ACTOR_INVALID')
        if self.kind=='ACTOR_RESOURCE_SET':
            if self.resource not in ('AP','MP','RANGE') or type(self.value) is not int or not 0<=self.value<=200:
                raise ValueError('STATE_EVENT_RESOURCE_INVALID')
        elif self.kind=='ACTOR_HP_SET':
            if type(self.value) is not int or type(self.maximum) is not int or not 0<=self.value<=self.maximum<=1_000_000_000:
                raise ValueError('STATE_EVENT_HP_INVALID')
        elif self.kind=='ACTOR_POSITION_SET':
            if type(self.value) is not int or not 0<=self.value<=100000:
                raise ValueError('STATE_EVENT_CELL_INVALID')
        elif self.kind=='ACTOR_COOLDOWNS_SET':
            if len(self.cooldowns)>200 or len(set(s for s,_ in self.cooldowns))!=len(self.cooldowns) or any(type(s) is not int or s<=0 or type(n) is not int or not 0<=n<=1000 for s,n in self.cooldowns):
                raise ValueError('STATE_EVENT_COOLDOWNS_INVALID')
        if self.kind not in ('ACTOR_RESOURCE_SET','ACTOR_HP_SET','ACTOR_POSITION_SET') and self.value is not None:
            raise ValueError('STATE_EVENT_EXTRANEOUS_VALUE')
        if self.kind!='ACTOR_RESOURCE_SET' and self.resource is not None:raise ValueError('STATE_EVENT_EXTRANEOUS_RESOURCE')
        if self.kind!='ACTOR_HP_SET' and self.maximum is not None:raise ValueError('STATE_EVENT_EXTRANEOUS_MAXIMUM')
        if self.kind!='ACTOR_COOLDOWNS_SET' and self.cooldowns:raise ValueError('STATE_EVENT_EXTRANEOUS_COOLDOWNS')


@dataclass(frozen=True,slots=True)
class OfflineBatchEnvelope:
    """P56 synthetic-only source receipt for one logical state-event batch.

    ``source_digest`` identifies the exact upstream synthetic observation batch.
    The journal binds it atomically to the event payloads and projection update.
    This is deliberately not a current-client or live admission credential.
    """
    batch_id:str
    source_digest:str
    events:tuple[OfflineStateEvent,...]
    origin:str=field(default='SYNTHETIC_FIXTURE_ONLY',init=False)

    def __post_init__(self):
        token=lambda value: isinstance(value,str) and 0<len(value)<=120 and all(c.isascii() and (c.isalnum() or c in '_-.') for c in value)
        if not token(self.batch_id):raise ValueError('STATE_BATCH_ID_INVALID')
        if not isinstance(self.source_digest,str) or len(self.source_digest)!=64 or any(c not in '0123456789abcdef' for c in self.source_digest):
            raise ValueError('STATE_BATCH_SOURCE_DIGEST_INVALID')
        if not isinstance(self.events,tuple) or not 1<=len(self.events)<=2048 or any(not isinstance(e,OfflineStateEvent) for e in self.events):
            raise ValueError('STATE_BATCH_EVENTS_INVALID')

# --- Definitive M1 state identity/proof contracts (additive) ---
from dataclasses import asdict as _asdict
from typing import Literal as _Literal
from anka_contracts.evidence import EvidencePointer as StableEvidencePointer

ProofStatus = _Literal['PROVEN','UNKNOWN','STALE','CONFLICTING','UNSUPPORTED']

@dataclass(frozen=True, slots=True)
class FieldProof:
    field_name: str
    status: ProofStatus
    evidence: tuple[StableEvidencePointer, ...] = ()
    reason: str = ''

    def __post_init__(self):
        if type(self.field_name) is not str or not self.field_name or len(self.field_name)>96:
            raise ValueError('INVALID_FIELD_PROOF_NAME')
        if self.status not in ('PROVEN','UNKNOWN','STALE','CONFLICTING','UNSUPPORTED'):
            raise ValueError('INVALID_FIELD_PROOF_STATUS')
        if self.status == 'PROVEN' and not self.evidence:
            raise ValueError('PROVEN_FIELD_REQUIRES_EVIDENCE')
        if self.status != 'PROVEN' and not self.reason:
            raise ValueError('NONPROVEN_FIELD_REQUIRES_REASON')

@dataclass(frozen=True, slots=True)
class StateSnapshotIdentity:
    snapshot_id: str
    run_id: str
    account_id: str
    client_instance_id: str
    world_epoch: int
    fight_epoch: int
    turn_epoch: int
    canonical_cursor: int
    snapshot_revision: int
    snapshot_sha256: str
    observed_client_build: str
    protocol_adapter_release: str
    reducer_revision: str
    kernel_ruleset: str
    game_data_revision: str
    health: str
    field_proofs: tuple[FieldProof, ...]

    def __post_init__(self):
        for value,prefix in ((self.snapshot_id,'snap-'),(self.run_id,'run-'),(self.account_id,'acct-'),(self.client_instance_id,'client-')):
            if not value.startswith(prefix): raise ValueError('INVALID_SNAPSHOT_IDENTITY')
        if any(type(v) is not int or v < 0 for v in (self.world_epoch,self.fight_epoch,self.turn_epoch,self.canonical_cursor,self.snapshot_revision)):
            raise ValueError('INVALID_SNAPSHOT_REVISION')
        if len(self.snapshot_sha256)!=64 or any(c not in '0123456789abcdef' for c in self.snapshot_sha256):
            raise ValueError('INVALID_SNAPSHOT_HASH')
        if self.health not in ('HEALTHY','DEGRADED','BLOCKED','UNKNOWN'):
            raise ValueError('INVALID_SNAPSHOT_HEALTH')
        if not self.field_proofs or len({p.field_name for p in self.field_proofs})!=len(self.field_proofs):
            raise ValueError('INVALID_FIELD_PROOF_SET')

    def to_dict(self) -> dict:
        obj=_asdict(self)
        obj['field_proofs']=[{'field_name':p.field_name,'status':p.status,'evidence':[e.to_dict() for e in p.evidence],'reason':p.reason} for p in self.field_proofs]
        return obj


# --- Definitive M7 immutable live-state contracts ---
from hashlib import sha256 as _sha256
import json as _json

LiveProofStatus = _Literal['KNOWN','UNKNOWN','STALE','CONFLICTING','NOT_OBSERVED']

@dataclass(frozen=True, slots=True)
class FieldValueProof:
    field_name: str
    value: str | int | bool | None
    status: LiveProofStatus
    source_event_ids: tuple[str,...]
    canonical_cursor: int
    fight_epoch: int | None = None
    turn_epoch: int | None = None
    authority: str = 'CANONICAL_COMMITTED'
    invalidation_reason: str | None = None

    def __post_init__(self):
        if type(self.field_name) is not str or not 1<=len(self.field_name)<=96: raise ValueError('INVALID_LIVE_FIELD_NAME')
        if self.status not in ('KNOWN','UNKNOWN','STALE','CONFLICTING','NOT_OBSERVED'): raise ValueError('INVALID_LIVE_FIELD_STATUS')
        if self.status=='KNOWN' and (self.value is None or not self.source_event_ids): raise ValueError('KNOWN_LIVE_FIELD_REQUIRES_VALUE_AND_SOURCE')
        if self.status!='KNOWN' and self.invalidation_reason is None: raise ValueError('NONKNOWN_LIVE_FIELD_REQUIRES_REASON')
        if type(self.canonical_cursor) is not int or self.canonical_cursor<0: raise ValueError('INVALID_LIVE_FIELD_CURSOR')
        if any(type(x) is not str or not x.startswith('canonical-') for x in self.source_event_ids): raise ValueError('INVALID_LIVE_FIELD_SOURCE')
        for e in (self.fight_epoch,self.turn_epoch):
            if e is not None and (type(e) is not int or e<0):raise ValueError('INVALID_LIVE_FIELD_EPOCH')
        if self.authority!='CANONICAL_COMMITTED':raise ValueError('INVALID_LIVE_FIELD_AUTHORITY')

@dataclass(frozen=True, slots=True)
class ActorLiveSnapshot:
    actor_id: int
    cell: FieldValueProof
    hp: FieldValueProof
    max_hp: FieldValueProof
    ap: FieldValueProof
    mp: FieldValueProof
    range: FieldValueProof
    cooldowns: FieldValueProof
    ready: FieldValueProof
    def __post_init__(self):
        if type(self.actor_id) is not int or self.actor_id==0:raise ValueError('INVALID_LIVE_ACTOR')

@dataclass(frozen=True, slots=True)
class LiveStateSnapshot:
    snapshot_id: str
    account_id: str
    client_instance_id: str
    canonical_cursor: int
    snapshot_revision: int
    world_epoch: int
    fight_epoch: int
    turn_epoch: int
    world_map: FieldValueProof
    fight_id: FieldValueProof
    fight_phase: FieldValueProof
    turn_owner: FieldValueProof
    fight_map: FieldValueProof
    actors: tuple[ActorLiveSnapshot,...]
    semantic_sha256: str

    def __post_init__(self):
        if not self.snapshot_id.startswith('snap-') or not self.account_id.startswith('acct-') or not self.client_instance_id.startswith('client-'):
            raise ValueError('INVALID_LIVE_SNAPSHOT_IDENTITY')
        if any(type(x) is not int or x<0 for x in (self.canonical_cursor,self.snapshot_revision,self.world_epoch,self.fight_epoch,self.turn_epoch)):
            raise ValueError('INVALID_LIVE_SNAPSHOT_REVISION')
        if len({a.actor_id for a in self.actors})!=len(self.actors):raise ValueError('DUPLICATE_LIVE_ACTOR')
        if type(self.semantic_sha256) is not str or len(self.semantic_sha256)!=64 or any(c not in '0123456789abcdef' for c in self.semantic_sha256):raise ValueError('INVALID_LIVE_SNAPSHOT_HASH')

    def to_dict(self)->dict:
        return _asdict(self)
