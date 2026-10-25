"""Workflow persistence/migration boundary for Issue #32 Phase A.

This module expands the shared contract without taking lifecycle ownership away
from :mod:`anka_workflow`.  It can parse legacy snapshots for diagnostics, but
resume/recovery authority is granted only when persisted identity and monotonic
watermark evidence are explicit.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from typing import Literal

from anka_contracts.workflow import (
    WorkflowSignal,
    WorkflowSnapshot,
    correlate_recovery_outcome,
    with_accepted_workflow_tick,
)

WORKFLOW_PERSISTENCE_SCHEMA_VERSION = 2
MigrationClassification = Literal['SAFE','AMBIGUOUS','INCOMPATIBLE']
AdmissionStatus = Literal['ALLOWED','IDEMPOTENT','REJECTED']
_TERMINAL_PHASES = {'COMPLETED','STOPPED','BLOCKED'}
_SNAPSHOT_TUPLES = {
    'counted_fight_epochs','started_fight_epochs','processed_signal_ids','expected_next_evidence',
}
_SIGNAL_TUPLES = {'evidence_ids'}
_NEW_SNAPSHOT_FIELDS = {'recovery_generation','active_recovery_generation','last_processed_tick'}


@dataclass(frozen=True, slots=True)
class WorkflowSnapshotMigration:
    classification: MigrationClassification
    snapshot: WorkflowSnapshot | None
    resume_authorized: bool
    reasons: tuple[str, ...]
    source_schema_version: int | None

    def __post_init__(self):
        if self.classification not in ('SAFE','AMBIGUOUS','INCOMPATIBLE'):
            raise ValueError('INVALID_WORKFLOW_MIGRATION_CLASSIFICATION')
        if type(self.resume_authorized) is not bool or not self.reasons:
            raise ValueError('INVALID_WORKFLOW_SNAPSHOT_MIGRATION')
        if self.source_schema_version is not None and (
            type(self.source_schema_version) is not int or self.source_schema_version<1
        ):
            raise ValueError('INVALID_WORKFLOW_SOURCE_SCHEMA')
        if self.resume_authorized and (self.classification!='SAFE' or self.snapshot is None):
            raise ValueError('WORKFLOW_RESUME_AUTHORITY_WITHOUT_SAFE_MIGRATION')


@dataclass(frozen=True, slots=True)
class WorkflowSignalMigration:
    classification: MigrationClassification
    signal: WorkflowSignal | None
    authoritative: bool
    reasons: tuple[str, ...]
    source_schema_version: int | None

    def __post_init__(self):
        if self.classification not in ('SAFE','AMBIGUOUS','INCOMPATIBLE'):
            raise ValueError('INVALID_WORKFLOW_MIGRATION_CLASSIFICATION')
        if type(self.authoritative) is not bool or not self.reasons:
            raise ValueError('INVALID_WORKFLOW_SIGNAL_MIGRATION')
        if self.authoritative and (self.classification!='SAFE' or self.signal is None):
            raise ValueError('WORKFLOW_SIGNAL_AUTHORITY_WITHOUT_SAFE_MIGRATION')


@dataclass(frozen=True, slots=True)
class WorkflowAdmission:
    status: AdmissionStatus
    reason: str

    def __post_init__(self):
        if self.status not in ('ALLOWED','IDEMPOTENT','REJECTED') or not self.reason:
            raise ValueError('INVALID_WORKFLOW_ADMISSION')


@dataclass(frozen=True, slots=True)
class WorkflowRecoverySignalPreparation:
    admission: WorkflowAdmission
    signal: WorkflowSignal | None

    def __post_init__(self):
        if self.admission.status=='ALLOWED' and self.signal is None:
            raise ValueError('WORKFLOW_RECOVERY_SIGNAL_REQUIRED')
        if self.admission.status!='ALLOWED' and self.signal is not None:
            raise ValueError('NONCURRENT_RECOVERY_SIGNAL_MUST_NOT_BE_EMITTED')


def _jsonable_contract(obj, tuple_fields: set[str]) -> dict:
    data=asdict(obj)
    for name in tuple_fields:
        data[name]=list(data[name])
    return data


def _unwrap(payload: object, key: str) -> tuple[int | None, dict | None, tuple[str,...]]:
    if not isinstance(payload,dict):
        return None,None,('WORKFLOW_PAYLOAD_NOT_OBJECT',)
    if 'schema_version' in payload or key in payload:
        version=payload.get('schema_version')
        body=payload.get(key)
        if type(version) is not int or version<1:
            return None,None,('WORKFLOW_SCHEMA_VERSION_INVALID',)
        if not isinstance(body,dict):
            return version,None,(f'WORKFLOW_{key.upper()}_PAYLOAD_INVALID',)
        return version,dict(body),()
    # Historic code had no canonical persistence envelope.  Treat a bare dict
    # as legacy schema 1, never as current authority.
    return 1,dict(payload),('LEGACY_UNVERSIONED_PAYLOAD',)


def _normalize_tuples(data: dict, names: set[str]) -> tuple[dict | None, tuple[str,...]]:
    out=dict(data)
    for name in names:
        if name not in out:
            continue
        value=out[name]
        if not isinstance(value,(list,tuple)):
            return None,(f'WORKFLOW_{name.upper()}_INVALID',)
        out[name]=tuple(value)
    return out,()


def dump_workflow_snapshot(snapshot: WorkflowSnapshot) -> dict:
    if not isinstance(snapshot,WorkflowSnapshot):
        raise ValueError('WORKFLOW_SNAPSHOT_REQUIRED')
    # A current persistence envelope is evidence-bearing.  Do not stamp v2 over
    # an engine snapshot that still lacks Phase-B recovery/time authority.
    if snapshot.recovery_generation is None or snapshot.last_processed_tick is None:
        raise ValueError('WORKFLOW_SNAPSHOT_AUTHORITY_INCOMPLETE')
    if snapshot.phase=='RECOVERING' and snapshot.active_recovery_generation is None:
        raise ValueError('WORKFLOW_ACTIVE_RECOVERY_GENERATION_UNPROVEN')
    return {
        'schema_version':WORKFLOW_PERSISTENCE_SCHEMA_VERSION,
        'snapshot':_jsonable_contract(snapshot,_SNAPSHOT_TUPLES),
    }


def load_workflow_snapshot(payload: object) -> WorkflowSnapshotMigration:
    version,body,unwrap_reasons=_unwrap(payload,'snapshot')
    if body is None:
        return WorkflowSnapshotMigration('INCOMPATIBLE',None,False,unwrap_reasons,version)

    current=version==WORKFLOW_PERSISTENCE_SCHEMA_VERSION
    if version is not None and version>WORKFLOW_PERSISTENCE_SCHEMA_VERSION:
        return WorkflowSnapshotMigration(
            'INCOMPATIBLE',None,False,('WORKFLOW_SNAPSHOT_SCHEMA_TOO_NEW',),version
        )
    if current and not _NEW_SNAPSHOT_FIELDS.issubset(body):
        return WorkflowSnapshotMigration(
            'INCOMPATIBLE',None,False,('CURRENT_SNAPSHOT_AUTHORITY_FIELDS_MISSING',),version
        )

    normalized,shape_reasons=_normalize_tuples(body,_SNAPSHOT_TUPLES)
    if normalized is None:
        return WorkflowSnapshotMigration('INCOMPATIBLE',None,False,shape_reasons,version)
    allowed={field.name for field in fields(WorkflowSnapshot)}
    if set(normalized)-allowed:
        return WorkflowSnapshotMigration(
            'INCOMPATIBLE',None,False,('WORKFLOW_SNAPSHOT_UNKNOWN_FIELDS',),version
        )
    for name in _NEW_SNAPSHOT_FIELDS:
        normalized.setdefault(name,None)
    try:
        snapshot=WorkflowSnapshot(**normalized)
    except (TypeError,ValueError) as exc:
        return WorkflowSnapshotMigration(
            'INCOMPATIBLE',None,False,(f'WORKFLOW_SNAPSHOT_INVALID:{type(exc).__name__}',),version
        )

    if current:
        if snapshot.recovery_generation is None or snapshot.last_processed_tick is None:
            return WorkflowSnapshotMigration(
                'INCOMPATIBLE',snapshot,False,('CURRENT_SNAPSHOT_AUTHORITY_UNPROVEN',),version
            )
        if snapshot.phase=='RECOVERING' and snapshot.active_recovery_generation is None:
            return WorkflowSnapshotMigration(
                'INCOMPATIBLE',snapshot,False,('CURRENT_RECOVERY_IDENTITY_UNPROVEN',),version
            )
        resume_allowed=snapshot.phase not in _TERMINAL_PHASES and snapshot.pending_action_id is None
        reasons=('CURRENT_SCHEMA_AUTHORITY_COMPLETE',) if resume_allowed else ('CURRENT_SCHEMA_READ_ONLY_OR_RECONCILIATION_REQUIRED',)
        return WorkflowSnapshotMigration('SAFE',snapshot,resume_allowed,reasons,version)

    # Legacy RECOVERING state cannot be resumed: there is no defensible way to
    # invent which historical attempt a delayed success/failure belongs to.
    if snapshot.phase=='RECOVERING' and snapshot.active_recovery_generation is None:
        return WorkflowSnapshotMigration(
            'INCOMPATIBLE',snapshot,False,
            unwrap_reasons+('LEGACY_ACTIVE_RECOVERY_IDENTITY_UNPROVEN',),version
        )

    # A pristine CREATED snapshot proves that no signal or recovery attempt has
    # happened yet.  Initializing generation/watermark zero does not rewrite
    # history and is the sole authoritative legacy upgrade.
    if (
        snapshot.phase=='CREATED'
        and snapshot.phase_started_tick==0
        and not snapshot.processed_signal_ids
        and snapshot.pending_action_id is None
    ):
        upgraded=replace(
            snapshot,recovery_generation=0,active_recovery_generation=None,last_processed_tick=0
        )
        return WorkflowSnapshotMigration(
            'SAFE',upgraded,True,unwrap_reasons+('LEGACY_PRISTINE_BOOTSTRAP_SAFE',),version
        )

    # Terminal legacy snapshots are safe to retain as read-only history.  Their
    # missing watermark/generation must remain unknown rather than fabricated.
    if snapshot.phase in _TERMINAL_PHASES:
        return WorkflowSnapshotMigration(
            'SAFE',snapshot,False,unwrap_reasons+('LEGACY_TERMINAL_READ_ONLY',),version
        )

    return WorkflowSnapshotMigration(
        'AMBIGUOUS',snapshot,False,
        unwrap_reasons+('LEGACY_TEMPORAL_OR_RECOVERY_AUTHORITY_UNPROVEN',),version
    )


def dump_workflow_signal(signal: WorkflowSignal) -> dict:
    if not isinstance(signal,WorkflowSignal):
        raise ValueError('WORKFLOW_SIGNAL_REQUIRED')
    if signal.kind in ('RECOVERY_SUCCEEDED','RECOVERY_FAILED') and signal.recovery_generation is None:
        raise ValueError('WORKFLOW_RECOVERY_IDENTITY_REQUIRED')
    return {
        'schema_version':WORKFLOW_PERSISTENCE_SCHEMA_VERSION,
        'signal':_jsonable_contract(signal,_SIGNAL_TUPLES),
    }


def load_workflow_signal(payload: object) -> WorkflowSignalMigration:
    version,body,unwrap_reasons=_unwrap(payload,'signal')
    if body is None:
        return WorkflowSignalMigration('INCOMPATIBLE',None,False,unwrap_reasons,version)
    if version is not None and version>WORKFLOW_PERSISTENCE_SCHEMA_VERSION:
        return WorkflowSignalMigration(
            'INCOMPATIBLE',None,False,('WORKFLOW_SIGNAL_SCHEMA_TOO_NEW',),version
        )
    normalized,shape_reasons=_normalize_tuples(body,_SIGNAL_TUPLES)
    if normalized is None:
        return WorkflowSignalMigration('INCOMPATIBLE',None,False,shape_reasons,version)
    allowed={field.name for field in fields(WorkflowSignal)}
    if set(normalized)-allowed:
        return WorkflowSignalMigration(
            'INCOMPATIBLE',None,False,('WORKFLOW_SIGNAL_UNKNOWN_FIELDS',),version
        )
    normalized.setdefault('recovery_generation',None)
    try:
        signal=WorkflowSignal(**normalized)
    except (TypeError,ValueError) as exc:
        return WorkflowSignalMigration(
            'INCOMPATIBLE',None,False,(f'WORKFLOW_SIGNAL_INVALID:{type(exc).__name__}',),version
        )
    if signal.kind in ('RECOVERY_SUCCEEDED','RECOVERY_FAILED') and signal.recovery_generation is None:
        return WorkflowSignalMigration(
            'INCOMPATIBLE',signal,False,
            unwrap_reasons+('RECOVERY_IDENTITY_MISSING',),version
        )
    if version==WORKFLOW_PERSISTENCE_SCHEMA_VERSION:
        return WorkflowSignalMigration('SAFE',signal,True,('CURRENT_SIGNAL_SCHEMA',),version)
    # Legacy signals remain parseable for replay/diagnostics, but old storage
    # did not carry the Phase-A authority envelope.  Do not silently promote
    # any historic fixture to current authoritative input.
    return WorkflowSignalMigration(
        'AMBIGUOUS',signal,False,
        unwrap_reasons+('LEGACY_SIGNAL_AUTHORITY_UNPROVEN',),version
    )


def admit_workflow_resume(snapshot: WorkflowSnapshot, resume_tick: int) -> WorkflowAdmission:
    if not isinstance(snapshot,WorkflowSnapshot) or type(resume_tick) is not int or resume_tick<0:
        return WorkflowAdmission('REJECTED','INVALID_WORKFLOW_RESUME')
    if snapshot.phase in _TERMINAL_PHASES:
        return WorkflowAdmission('REJECTED','WORKFLOW_TERMINAL')
    if snapshot.pending_action_id is not None:
        return WorkflowAdmission('REJECTED','RESUME_PENDING_ACTION_RECONCILIATION_REQUIRED')
    if snapshot.recovery_generation is None:
        return WorkflowAdmission('REJECTED','RECOVERY_GENERATION_UNPROVEN')
    if snapshot.last_processed_tick is None:
        return WorkflowAdmission('REJECTED','WORKFLOW_WATERMARK_UNPROVEN')
    if resume_tick<snapshot.last_processed_tick:
        return WorkflowAdmission('REJECTED','RESUME_TICK_BELOW_WATERMARK')
    if snapshot.phase=='RECOVERING' and snapshot.active_recovery_generation is None:
        return WorkflowAdmission('REJECTED','RECOVERY_ACTIVE_GENERATION_UNPROVEN')
    return WorkflowAdmission('ALLOWED','WORKFLOW_RESUME_IDENTITY_PROVEN')


def admit_workflow_signal_tick(snapshot: WorkflowSnapshot, monotonic_tick: int) -> WorkflowAdmission:
    if not isinstance(snapshot,WorkflowSnapshot) or type(monotonic_tick) is not int or monotonic_tick<0:
        return WorkflowAdmission('REJECTED','INVALID_WORKFLOW_TICK')
    if snapshot.last_processed_tick is None:
        return WorkflowAdmission('REJECTED','WORKFLOW_WATERMARK_UNPROVEN')
    if monotonic_tick<snapshot.last_processed_tick:
        return WorkflowAdmission('REJECTED','SIGNAL_TICK_BELOW_WATERMARK')
    return WorkflowAdmission('ALLOWED','SIGNAL_TICK_CURRENT')


def persist_workflow_signal_tick(
    snapshot: WorkflowSnapshot, monotonic_tick: int, *, accepted: bool
) -> WorkflowSnapshot:
    """Persist time only for an already accepted/recorded Workflow signal."""
    if type(accepted) is not bool:
        raise ValueError('WORKFLOW_ACCEPTANCE_FLAG_REQUIRED')
    if not accepted:
        return snapshot
    return with_accepted_workflow_tick(snapshot,monotonic_tick)


def prepare_recovery_outcome_signal(
    snapshot: WorkflowSnapshot,
    *,
    signal_id: str,
    kind: str,
    monotonic_tick: int,
    evidence_ids: tuple[str,...]=(),
    recovery_generation: int | None,
) -> WorkflowRecoverySignalPreparation:
    """Build an App-origin recovery result only when it targets the active attempt."""
    try:
        signal=WorkflowSignal(
            signal_id,kind,monotonic_tick,evidence_ids,recovery_generation=recovery_generation
        )
    except ValueError as exc:
        return WorkflowRecoverySignalPreparation(
            WorkflowAdmission('REJECTED',str(exc)),None
        )
    correlation=correlate_recovery_outcome(snapshot,signal)
    if correlation.disposition=='IDEMPOTENT':
        return WorkflowRecoverySignalPreparation(
            WorkflowAdmission('IDEMPOTENT',correlation.reason),None
        )
    if correlation.disposition!='CURRENT':
        return WorkflowRecoverySignalPreparation(
            WorkflowAdmission('REJECTED',correlation.reason),None
        )
    tick=admit_workflow_signal_tick(snapshot,signal.monotonic_tick)
    if tick.status!='ALLOWED':
        return WorkflowRecoverySignalPreparation(tick,None)
    return WorkflowRecoverySignalPreparation(
        WorkflowAdmission('ALLOWED','RECOVERY_OUTCOME_CURRENT_AND_TEMPORAL'),signal
    )
