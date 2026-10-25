"""Definitive M11 execution admission/driver/outcome contracts.

These types describe proof and external-boundary state. They do not grant physical
input authority by themselves; only the concrete Execution service may do that.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

AdmissionStatus=Literal['ADMITTED','REJECTED']
DriverDelivery=Literal['NOT_SENT','SENT','MAY_HAVE_SENT']
OutcomeObservationKind=Literal['CONFIRMATION','FAILURE','INCONCLUSIVE']


def _token(v:str,prefix:str|None=None)->bool:
    return type(v) is str and 1<=len(v)<=160 and (prefix is None or v.startswith(prefix))

@dataclass(frozen=True,slots=True)
class ExecutionStateView:
    snapshot_id:str
    snapshot_sha256:str
    account_id:str
    client_instance_id:str
    fight_epoch:int
    turn_epoch:int
    canonical_cursor:int
    actor_id:int|None
    turn_owner_actor_id:int|None
    health:str
    required_proofs:tuple[tuple[str,str],...]
    invalidating_change_since_basis:bool=False

    def __post_init__(self):
        if not (_token(self.snapshot_id,'snap-') and _token(self.account_id,'acct-') and _token(self.client_instance_id,'client-')):raise ValueError('INVALID_EXECUTION_STATE_IDENTITY')
        if len(self.snapshot_sha256)!=64 or any(c not in '0123456789abcdef' for c in self.snapshot_sha256):raise ValueError('INVALID_EXECUTION_STATE_HASH')
        if any(type(x) is not int or x<0 for x in (self.fight_epoch,self.turn_epoch,self.canonical_cursor)):raise ValueError('INVALID_EXECUTION_STATE_EPOCH')
        if self.actor_id is not None and (type(self.actor_id) is not int or self.actor_id==0):raise ValueError('INVALID_EXECUTION_ACTOR')
        if self.turn_owner_actor_id is not None and (type(self.turn_owner_actor_id) is not int or self.turn_owner_actor_id==0):raise ValueError('INVALID_EXECUTION_OWNER')
        if self.health not in ('HEALTHY','DEGRADED','BLOCKED','UNKNOWN'):raise ValueError('INVALID_EXECUTION_STATE_HEALTH')
        allowed={'KNOWN','UNKNOWN','STALE','CONFLICTING','NOT_OBSERVED'}
        if len({k for k,_ in self.required_proofs})!=len(self.required_proofs) or any(type(k) is not str or v not in allowed for k,v in self.required_proofs):raise ValueError('INVALID_EXECUTION_STATE_PROOFS')
        if type(self.invalidating_change_since_basis) is not bool:raise ValueError('INVALID_EXECUTION_INVALIDATION_FLAG')

@dataclass(frozen=True,slots=True)
class ExecutionClientAttestation:
    attestation_id:str
    account_id:str
    client_instance_id:str
    observed_client_build:str
    pid:int
    process_created_100ns:int
    hwnd:int
    window_generation:int
    projection_generation:int
    calibration_generation:int
    loadout_generation:int|None
    pixel_x:int
    pixel_y:int
    identity_proven:bool
    class_proven:bool
    foreground_proven:bool
    visible_proven:bool
    geometry_proven:bool
    projection_proven:bool
    loadout_binding_proven:bool
    semantic_target_fingerprint:str
    evidence_ids:tuple[str,...]

    def __post_init__(self):
        if not (_token(self.attestation_id,'clientatt-') and _token(self.account_id,'acct-') and _token(self.client_instance_id,'client-')):raise ValueError('INVALID_EXECUTION_CLIENT_IDENTITY')
        if not self.observed_client_build:raise ValueError('EXECUTION_CLIENT_BUILD_REQUIRED')
        if any(type(x) is not int or x<=0 for x in (self.pid,self.process_created_100ns,self.hwnd,self.window_generation,self.projection_generation,self.calibration_generation)):raise ValueError('INVALID_EXECUTION_CLIENT_GENERATION')
        if self.loadout_generation is not None and (type(self.loadout_generation) is not int or self.loadout_generation<=0):raise ValueError('INVALID_EXECUTION_LOADOUT_GENERATION')
        if type(self.pixel_x) is not int or type(self.pixel_y) is not int or self.pixel_x<0 or self.pixel_y<0:raise ValueError('INVALID_EXECUTION_PROJECTION')
        for x in (self.identity_proven,self.class_proven,self.foreground_proven,self.visible_proven,self.geometry_proven,self.projection_proven,self.loadout_binding_proven):
            if type(x) is not bool:raise ValueError('INVALID_EXECUTION_CLIENT_PROOF')
        if len(self.semantic_target_fingerprint)!=64 or any(c not in '0123456789abcdef' for c in self.semantic_target_fingerprint):raise ValueError('INVALID_EXECUTION_TARGET_FINGERPRINT')
        if not self.evidence_ids or len(set(self.evidence_ids))!=len(self.evidence_ids) or any(type(x) is not str or not x for x in self.evidence_ids):raise ValueError('INVALID_EXECUTION_CLIENT_EVIDENCE')

@dataclass(frozen=True,slots=True)
class ExecutionAdmission:
    status:AdmissionStatus
    reason:str
    state:ExecutionStateView|None
    client:ExecutionClientAttestation|None
    party_generation:int|None
    permit_generation:int|None
    evidence_ids:tuple[str,...]=()

    def __post_init__(self):
        if self.status not in ('ADMITTED','REJECTED') or not self.reason:raise ValueError('INVALID_EXECUTION_ADMISSION')
        if self.status=='ADMITTED' and (self.state is None or self.client is None or self.party_generation is None or self.permit_generation is None):raise ValueError('ADMITTED_EXECUTION_REQUIRES_PROOF')
        if self.status=='REJECTED' and (self.state is not None or self.client is not None):raise ValueError('REJECTED_EXECUTION_CANNOT_CARRY_AUTHORITY')

@dataclass(frozen=True,slots=True)
class InputLease:
    lease_id:str
    lease_epoch:int
    action_id:str
    account_id:str
    acquired_monotonic_ns:int
    def __post_init__(self):
        if not (_token(self.lease_id,'lease-') and _token(self.action_id,'action-') and _token(self.account_id,'acct-')):raise ValueError('INVALID_INPUT_LEASE')
        if type(self.lease_epoch) is not int or self.lease_epoch<=0 or type(self.acquired_monotonic_ns) is not int or self.acquired_monotonic_ns<0:raise ValueError('INVALID_INPUT_LEASE_GENERATION')

@dataclass(frozen=True,slots=True)
class DriverSendReceipt:
    action_id:str
    delivery:DriverDelivery
    physical_input_count:int
    detail:str
    def __post_init__(self):
        if not _token(self.action_id,'action-') or self.delivery not in ('NOT_SENT','SENT','MAY_HAVE_SENT'):raise ValueError('INVALID_DRIVER_RECEIPT')
        if type(self.physical_input_count) is not int or self.physical_input_count<0 or not self.detail:raise ValueError('INVALID_DRIVER_RECEIPT_DETAIL')
        if self.delivery=='NOT_SENT' and self.physical_input_count!=0:raise ValueError('NOT_SENT_CANNOT_HAVE_INPUT_COUNT')

@dataclass(frozen=True,slots=True)
class ExecutionOutcomeEvidence:
    evidence_id:str
    account_id:str
    client_instance_id:str
    fight_epoch:int
    observed_turn_epoch:int
    canonical_cursor:int
    result:OutcomeObservationKind
    proofs:tuple[str,...]
    authoritative:bool
    correlated_action_id:str|None=None
    actor_id:int|None=None

    def __post_init__(self):
        if not (_token(self.evidence_id,'outcome-') and _token(self.account_id,'acct-') and _token(self.client_instance_id,'client-')):raise ValueError('INVALID_OUTCOME_EVIDENCE_IDENTITY')
        if any(type(x) is not int or x<0 for x in (self.fight_epoch,self.observed_turn_epoch,self.canonical_cursor)):raise ValueError('INVALID_OUTCOME_EVIDENCE_EPOCH')
        if self.result not in ('CONFIRMATION','FAILURE','INCONCLUSIVE'):raise ValueError('INVALID_OUTCOME_EVIDENCE_RESULT')
        if len(set(self.proofs))!=len(self.proofs) or any(type(x) is not str or not x for x in self.proofs):raise ValueError('INVALID_OUTCOME_EVIDENCE_PROOFS')
        if type(self.authoritative) is not bool:raise ValueError('INVALID_OUTCOME_EVIDENCE_AUTHORITY')
        if self.correlated_action_id is not None and not _token(self.correlated_action_id,'action-'):raise ValueError('INVALID_OUTCOME_CORRELATED_ACTION')
        if self.actor_id is not None and (type(self.actor_id) is not int or self.actor_id==0):raise ValueError('INVALID_OUTCOME_ACTOR')

@dataclass(frozen=True,slots=True)
class ExecutionLedgerAction:
    action_id:str
    action_key:str
    status:str
    attempt_id:str|None
    send_state:str
    run_generation:int
    input_authority_generation:int
    evidence_ids:tuple[str,...]
    unresolved_obligations:tuple[str,...]
    reason:str

@dataclass(frozen=True,slots=True)
class ExecutionCoordinationPermit:
    party_id:str
    account_id:str
    fight_epoch:int
    turn_epoch:int
    party_generation:int
    permit_generation:int
    allowed:bool
    reason:str
    evidence_ids:tuple[str,...]=()
    scope:str='TURN'
    def __post_init__(self):
        if not (_token(self.party_id,'party-') and _token(self.account_id,'acct-')):raise ValueError('INVALID_EXECUTION_PARTY_PERMIT')
        if any(type(x) is not int or x<0 for x in (self.fight_epoch,self.turn_epoch,self.party_generation,self.permit_generation)):raise ValueError('INVALID_EXECUTION_PARTY_GENERATION')
        if type(self.allowed) is not bool or not self.reason:raise ValueError('INVALID_EXECUTION_PARTY_PERMIT_STATE')
        if self.allowed and not self.evidence_ids:raise ValueError('ALLOWED_EXECUTION_PERMIT_REQUIRES_EVIDENCE')
        if self.scope not in ('TURN','PLACEMENT','READY','JOIN','WORLD','FIGHT_ENTRY'):raise ValueError('INVALID_EXECUTION_PERMIT_SCOPE')
