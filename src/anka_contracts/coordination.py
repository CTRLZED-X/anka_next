"""Definitive cross-account coherence/turn permit contracts."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemberCursor:
    account_id: str
    client_instance_id: str
    canonical_cursor: int
    snapshot_revision: int
    fight_epoch: int
    turn_epoch: int
    healthy: bool

    def __post_init__(self):
        if not self.account_id.startswith("acct-") or not self.client_instance_id.startswith("client-"):
            raise ValueError("INVALID_MEMBER_IDENTITY")
        if any(type(v) is not int or v < 0 for v in (self.canonical_cursor,self.snapshot_revision,self.fight_epoch,self.turn_epoch)):
            raise ValueError("INVALID_MEMBER_CURSOR")
        if type(self.healthy) is not bool: raise ValueError("INVALID_MEMBER_HEALTH")


@dataclass(frozen=True, slots=True)
class PartyCoherenceFrame:
    party_id: str
    fight_epoch: int
    members: tuple[MemberCursor, ...]
    same_fight_proven: bool
    phase: str
    turn_owner_account_id: str | None
    permit_generation: int
    missing_evidence: tuple[str, ...] = ()
    conflicting_evidence: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.party_id.startswith("party-") or type(self.fight_epoch) is not int or self.fight_epoch < 0:
            raise ValueError("INVALID_PARTY_FRAME_IDENTITY")
        if not self.members or len({m.account_id for m in self.members}) != len(self.members):
            raise ValueError("INVALID_PARTY_MEMBERS")
        if type(self.same_fight_proven) is not bool or type(self.permit_generation) is not int or self.permit_generation < 0:
            raise ValueError("INVALID_PARTY_FRAME")
        if self.turn_owner_account_id is not None and self.turn_owner_account_id not in {m.account_id for m in self.members}:
            raise ValueError("TURN_OWNER_NOT_MEMBER")


@dataclass(frozen=True, slots=True)
class TurnPermit:
    party_id: str
    account_id: str
    fight_epoch: int
    turn_epoch: int
    permit_generation: int
    allowed: bool
    reason: str
    party_generation: int = 0

    def __post_init__(self):
        if not self.party_id.startswith("party-") or not self.account_id.startswith("acct-"):
            raise ValueError("INVALID_TURN_PERMIT_IDENTITY")
        if any(type(v) is not int or v < 0 for v in (self.fight_epoch,self.turn_epoch,self.permit_generation,self.party_generation)):
            raise ValueError("INVALID_TURN_PERMIT_GENERATION")
        if type(self.allowed) is not bool or type(self.reason) is not str or not self.reason:
            raise ValueError("INVALID_TURN_PERMIT")

@dataclass(frozen=True, slots=True)
class ActionPermit:
    """Phase-aware coordination authorization.

    TURN remains the strict combat authority.  The pre-turn scopes exist so
    actions needed to *reach* the first turn do not depend on a turn permit.
    WORLD is intentionally representable but Coordination does not grant it;
    world navigation belongs to Workflow/composition authority.
    """
    party_id: str
    account_id: str
    scope: str
    fight_epoch: int
    turn_epoch: int
    permit_generation: int
    allowed: bool
    reason: str
    party_generation: int = 0
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.party_id.startswith("party-") or not self.account_id.startswith("acct-"):
            raise ValueError("INVALID_ACTION_PERMIT_IDENTITY")
        if self.scope not in ("TURN","PLACEMENT","READY","JOIN","WORLD","FIGHT_ENTRY"):
            raise ValueError("INVALID_ACTION_PERMIT_SCOPE")
        if any(type(v) is not int or v < 0 for v in (self.fight_epoch,self.turn_epoch,self.permit_generation,self.party_generation)):
            raise ValueError("INVALID_ACTION_PERMIT_GENERATION")
        if type(self.allowed) is not bool or type(self.reason) is not str or not self.reason:
            raise ValueError("INVALID_ACTION_PERMIT")
        if len(set(self.evidence_ids)) != len(self.evidence_ids) or any(type(x) is not str or not x for x in self.evidence_ids):
            raise ValueError("INVALID_ACTION_PERMIT_EVIDENCE")


# --- Definitive M9 coordination contracts ---
from hashlib import sha256 as _sha256
import json as _json
from typing import Literal as _Literal

MemberHealth = _Literal['HEALTHY','DEGRADED','BLOCKED','UNKNOWN']
BarrierName = _Literal['JOIN','PLACEMENT','READY']

@dataclass(frozen=True, slots=True)
class PartyRosterMember:
    account_id: str
    client_instance_id: str
    actor_id: int
    role: str
    required: bool = True

    def __post_init__(self):
        if not self.account_id.startswith('acct-') or not self.client_instance_id.startswith('client-'):
            raise ValueError('INVALID_ROSTER_MEMBER_IDENTITY')
        if type(self.actor_id) is not int or self.actor_id == 0:
            raise ValueError('INVALID_ROSTER_ACTOR')
        if self.role not in ('leader','follower') or type(self.required) is not bool:
            raise ValueError('INVALID_ROSTER_ROLE')


@dataclass(frozen=True, slots=True)
class MemberPartyObservation:
    observation_id: str
    account_id: str
    client_instance_id: str
    actor_id: int
    canonical_cursor: int
    snapshot_revision: int
    fight_epoch: int
    turn_epoch: int
    fight_id: str | None
    map_id: int | None
    fight_phase: str
    turn_owner_actor_id: int | None
    joined: bool | None
    placed: bool | None
    ready: bool | None
    health: MemberHealth
    evidence_ids: tuple[str, ...] = ()
    capture_gap: bool = False

    def __post_init__(self):
        if not self.observation_id.startswith('coordobs-'):
            raise ValueError('INVALID_COORDINATION_OBSERVATION_ID')
        if not self.account_id.startswith('acct-') or not self.client_instance_id.startswith('client-'):
            raise ValueError('INVALID_COORDINATION_MEMBER_IDENTITY')
        if type(self.actor_id) is not int or self.actor_id == 0:
            raise ValueError('INVALID_COORDINATION_ACTOR')
        if any(type(v) is not int or v < 0 for v in (self.canonical_cursor,self.snapshot_revision,self.fight_epoch,self.turn_epoch)):
            raise ValueError('INVALID_COORDINATION_CURSOR')
        if self.fight_id is not None and (type(self.fight_id) is not str or not self.fight_id):
            raise ValueError('INVALID_COORDINATION_FIGHT_ID')
        if self.map_id is not None and (type(self.map_id) is not int or self.map_id <= 0):
            raise ValueError('INVALID_COORDINATION_MAP_ID')
        if type(self.fight_phase) is not str or not self.fight_phase:
            raise ValueError('INVALID_COORDINATION_FIGHT_PHASE')
        if self.turn_owner_actor_id is not None and (type(self.turn_owner_actor_id) is not int or self.turn_owner_actor_id == 0):
            raise ValueError('INVALID_COORDINATION_TURN_OWNER')
        if any(v is not None and type(v) is not bool for v in (self.joined,self.placed,self.ready)):
            raise ValueError('INVALID_COORDINATION_BARRIER_VALUE')
        if self.health not in ('HEALTHY','DEGRADED','BLOCKED','UNKNOWN'):
            raise ValueError('INVALID_COORDINATION_HEALTH')
        if type(self.capture_gap) is not bool:
            raise ValueError('INVALID_COORDINATION_GAP')
        if len(set(self.evidence_ids)) != len(self.evidence_ids) or any(type(x) is not str or not x for x in self.evidence_ids):
            raise ValueError('INVALID_COORDINATION_EVIDENCE')

    def semantic_tuple(self) -> tuple:
        """Fields that represent gameplay/coherence progress, excluding heartbeat cursors."""
        return (self.account_id,self.client_instance_id,self.actor_id,self.fight_epoch,self.turn_epoch,
                self.fight_id,self.map_id,self.fight_phase,self.turn_owner_actor_id,self.joined,self.placed,self.ready,
                self.health,self.capture_gap)


@dataclass(frozen=True, slots=True)
class PartyBarrier:
    name: BarrierName
    party_id: str
    fight_epoch: int
    permit_generation: int
    satisfied: bool
    required_accounts: tuple[str, ...]
    confirmed_accounts: tuple[str, ...]
    missing_accounts: tuple[str, ...]
    conflicting_accounts: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if self.name not in ('JOIN','PLACEMENT','READY') or not self.party_id.startswith('party-'):
            raise ValueError('INVALID_PARTY_BARRIER')
        if any(type(v) is not int or v < 0 for v in (self.fight_epoch,self.permit_generation)):
            raise ValueError('INVALID_PARTY_BARRIER_GENERATION')
        required=set(self.required_accounts)
        if not required or len(required)!=len(self.required_accounts):
            raise ValueError('INVALID_PARTY_BARRIER_ROSTER')
        if any(not x.startswith('acct-') for x in required):
            raise ValueError('INVALID_PARTY_BARRIER_ACCOUNT')
        if not set(self.confirmed_accounts).issubset(required) or not set(self.missing_accounts).issubset(required) or not set(self.conflicting_accounts).issubset(required):
            raise ValueError('INVALID_PARTY_BARRIER_SET')
        if self.satisfied != (set(self.confirmed_accounts)==required and not self.missing_accounts and not self.conflicting_accounts):
            raise ValueError('INCONSISTENT_PARTY_BARRIER')


@dataclass(frozen=True, slots=True)
class DefinitivePartySnapshot:
    party_id: str
    party_generation: int
    permit_generation: int
    fight_epoch: int
    fight_id: str | None
    phase: str
    members: tuple[MemberPartyObservation, ...]
    same_fight_proven: bool
    turn_owner_account_id: str | None
    join_barrier: PartyBarrier
    placement_barrier: PartyBarrier
    ready_barrier: PartyBarrier
    missing_evidence: tuple[str, ...]
    conflicting_evidence: tuple[str, ...]
    semantic_progress_token: str

    def __post_init__(self):
        if not self.party_id.startswith('party-'):
            raise ValueError('INVALID_DEFINITIVE_PARTY_ID')
        if any(type(v) is not int or v < 0 for v in (self.party_generation,self.permit_generation,self.fight_epoch)):
            raise ValueError('INVALID_DEFINITIVE_PARTY_GENERATION')
        if len({m.account_id for m in self.members}) != len(self.members):
            raise ValueError('DUPLICATE_DEFINITIVE_PARTY_MEMBER')
        if type(self.same_fight_proven) is not bool or type(self.phase) is not str or not self.phase:
            raise ValueError('INVALID_DEFINITIVE_PARTY_STATE')
        if self.turn_owner_account_id is not None and self.turn_owner_account_id not in {m.account_id for m in self.members}:
            raise ValueError('INVALID_DEFINITIVE_TURN_OWNER')
        if len(self.semantic_progress_token)!=64 or any(c not in '0123456789abcdef' for c in self.semantic_progress_token):
            raise ValueError('INVALID_COORDINATION_PROGRESS_TOKEN')


@dataclass(frozen=True, slots=True)
class CoordinationUpdate:
    status: str
    changed: bool
    semantic_progress: bool
    reason: str
    snapshot: DefinitivePartySnapshot

    def __post_init__(self):
        if self.status not in ('APPLIED','DUPLICATE','REJECTED'):
            raise ValueError('INVALID_COORDINATION_UPDATE_STATUS')
        if type(self.changed) is not bool or type(self.semantic_progress) is not bool or not self.reason:
            raise ValueError('INVALID_COORDINATION_UPDATE')
