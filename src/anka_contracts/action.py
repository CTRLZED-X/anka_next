"""Definitive semantic action/physical-attempt/outcome contracts."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Literal

ActionKind = Literal["CAST", "MOVE", "READY", "END_TURN", "JOIN_FIGHT", "WORLD_MOVE", "START_FIGHT"]
SendState = Literal["NOT_SENT", "SEND_STARTED", "SENT", "MAY_HAVE_SENT"]
OutcomeStatus = Literal[
    "REJECTED_NOT_SENT", "PENDING", "CONFIRMED_UNSETTLED", "SETTLED_SUCCESS",
    "PROVEN_FAILURE", "UNCERTAIN", "TERMINAL_UNRESOLVED",
]


def _token(value: str, prefix: str | None = None) -> bool:
    return type(value) is str and 1 <= len(value) <= 128 and (prefix is None or value.startswith(prefix))


@dataclass(frozen=True, slots=True)
class ActionCommand:
    action_id: str
    run_id: str
    account_id: str
    client_instance_id: str
    fight_epoch: int
    turn_epoch: int
    action_key: str
    kind: ActionKind
    basis_canonical_cursor: int
    semantic_target: tuple[tuple[str, str], ...]
    expected_outcome_proofs: tuple[str, ...]
    deadline_monotonic_ns: int | None = None
    basis_snapshot_id: str | None = None
    party_id: str | None = None
    basis_party_generation: int | None = None
    basis_permit_generation: int | None = None
    actor_id: int | None = None
    validity_constraints: tuple[str, ...] = ()
    authority_scope: str = "TURN"
    trace_id: str | None = None

    def __post_init__(self):
        if not (_token(self.action_id,"action-") and _token(self.run_id,"run-") and _token(self.account_id,"acct-") and _token(self.client_instance_id,"client-")):
            raise ValueError("INVALID_ACTION_IDENTITY")
        if type(self.fight_epoch) is not int or self.fight_epoch < 0 or type(self.turn_epoch) is not int or self.turn_epoch < 0:
            raise ValueError("INVALID_ACTION_EPOCH")
        if type(self.action_key) is not str or len(self.action_key) != 64 or any(c not in "0123456789abcdef" for c in self.action_key):
            raise ValueError("INVALID_ACTION_KEY")
        if self.kind not in ("CAST","MOVE","READY","END_TURN","JOIN_FIGHT","WORLD_MOVE","START_FIGHT"):
            raise ValueError("INVALID_ACTION_KIND")
        if type(self.basis_canonical_cursor) is not int or self.basis_canonical_cursor < 0:
            raise ValueError("INVALID_ACTION_CURSOR")
        if type(self.semantic_target) is not tuple or any(type(k) is not str or type(v) is not str for k,v in self.semantic_target):
            raise ValueError("INVALID_SEMANTIC_TARGET")
        if not self.expected_outcome_proofs:
            raise ValueError("OUTCOME_PROOF_REQUIRED")
        if self.deadline_monotonic_ns is not None and (type(self.deadline_monotonic_ns) is not int or self.deadline_monotonic_ns < 0):
            raise ValueError("INVALID_ACTION_DEADLINE")
        if self.basis_snapshot_id is not None and not _token(self.basis_snapshot_id,"snap-"):
            raise ValueError("INVALID_ACTION_BASIS_SNAPSHOT")
        if self.party_id is not None and not _token(self.party_id,"party-"):
            raise ValueError("INVALID_ACTION_PARTY")
        for value in (self.basis_party_generation,self.basis_permit_generation):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("INVALID_ACTION_PERMIT_GENERATION")
        if (self.basis_party_generation is None) != (self.basis_permit_generation is None):
            raise ValueError("INCOMPLETE_ACTION_PERMIT_BASIS")
        if self.party_id is None and self.basis_party_generation is not None:
            raise ValueError("ACTION_PERMIT_REQUIRES_PARTY")
        if self.actor_id is not None and (type(self.actor_id) is not int or self.actor_id == 0):
            raise ValueError("INVALID_ACTION_ACTOR")
        if len(set(self.validity_constraints)) != len(self.validity_constraints) or any(type(x) is not str or not x for x in self.validity_constraints):
            raise ValueError("INVALID_ACTION_VALIDITY_CONSTRAINTS")
        if self.authority_scope not in ("TURN","PLACEMENT","READY","JOIN","WORLD","FIGHT_ENTRY"):
            raise ValueError("INVALID_ACTION_AUTHORITY_SCOPE")
        allowed_scopes={
            "CAST": {"TURN"}, "END_TURN": {"TURN"}, "MOVE": {"TURN","PLACEMENT"},
            "READY": {"READY"}, "JOIN_FIGHT": {"JOIN"}, "WORLD_MOVE": {"WORLD"}, "START_FIGHT": {"FIGHT_ENTRY"},
        }
        if self.authority_scope not in allowed_scopes[self.kind]:
            raise ValueError("ACTION_KIND_AUTHORITY_SCOPE_MISMATCH")
        if self.trace_id is not None and not _token(self.trace_id,"trace-"):
            raise ValueError("INVALID_ACTION_TRACE_ID")

    def to_dict(self) -> dict:
        d=asdict(self); d["semantic_target"]=[list(x) for x in self.semantic_target]; d["expected_outcome_proofs"]=list(self.expected_outcome_proofs); return d


@dataclass(frozen=True, slots=True)
class PhysicalAttempt:
    attempt_id: str
    action_id: str
    input_lease_epoch: int
    client_instance_id: str
    window_generation: int
    projection_generation: int
    prepared_reference: str
    send_state: SendState
    prepared_monotonic_ns: int
    send_monotonic_ns: int | None = None

    def __post_init__(self):
        if not (_token(self.attempt_id,"attempt-") and _token(self.action_id,"action-") and _token(self.client_instance_id,"client-") and _token(self.prepared_reference)):
            raise ValueError("INVALID_ATTEMPT_IDENTITY")
        for value in (self.input_lease_epoch,self.window_generation,self.projection_generation,self.prepared_monotonic_ns):
            if type(value) is not int or value < 0: raise ValueError("INVALID_ATTEMPT_GENERATION")
        if self.send_state not in ("NOT_SENT","SEND_STARTED","SENT","MAY_HAVE_SENT"):
            raise ValueError("INVALID_SEND_STATE")
        if self.send_monotonic_ns is not None and (type(self.send_monotonic_ns) is not int or self.send_monotonic_ns < self.prepared_monotonic_ns):
            raise ValueError("INVALID_SEND_TIME")


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    action_id: str
    attempt_id: str | None
    status: OutcomeStatus
    evidence_ids: tuple[str, ...]
    retry_eligible: bool
    unresolved_obligations: tuple[str, ...] = ()
    reason: str = ''

    def __post_init__(self):
        if not _token(self.action_id,"action-") or (self.attempt_id is not None and not _token(self.attempt_id,"attempt-")):
            raise ValueError("INVALID_OUTCOME_IDENTITY")
        if self.status not in ("REJECTED_NOT_SENT","PENDING","CONFIRMED_UNSETTLED","SETTLED_SUCCESS","PROVEN_FAILURE","UNCERTAIN","TERMINAL_UNRESOLVED"):
            raise ValueError("INVALID_OUTCOME_STATUS")
        if type(self.retry_eligible) is not bool:
            raise ValueError("INVALID_RETRY_FLAG")
        if self.status in ("UNCERTAIN","TERMINAL_UNRESOLVED") and self.retry_eligible:
            raise ValueError("BLIND_RETRY_FORBIDDEN")
        if self.status not in ("REJECTED_NOT_SENT",) and not self.evidence_ids:
            raise ValueError("OUTCOME_EVIDENCE_REQUIRED")
        if type(self.reason) is not str: raise ValueError("INVALID_OUTCOME_REASON")
