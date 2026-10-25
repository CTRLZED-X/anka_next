"""Public, observer-only diagnostic contract. No imports of application systems."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any
import re

SEVERITIES = frozenset({'DEBUG','INFO','WARNING','ERROR','CRITICAL','SAFETY','SETTLEMENT'})
EVIDENCE_CLASSES = frozenset({'AUTHORITY_COMMITTED','OBSERVED_EXTERNAL','DERIVED','HEURISTIC','UNKNOWN','STALE','CONFLICTING','MISSING'})
EVENT_NAME = re.compile(r'^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$')


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')


@dataclass(frozen=True, slots=True)
class DiagnosticEvent:
    schema_version: int
    event_id: str
    event_name: str
    severity: str
    occurred_utc: str
    monotonic_ns: int
    producer_seq: int
    invocation_id: str
    run_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    parent_event_id: str | None = None
    account_id: str | None = None
    client_generation: str | None = None
    fight_id: str | None = None
    fight_epoch: int | None = None
    turn_epoch: int | None = None
    action_id: str | None = None
    attempt_id: str | None = None
    canonical_revision: int | None = None
    protocol_build: str | None = None
    owner_system: str | None = None
    physical_input_state: str | None = None
    canonical_cursor: int | None = None
    failure_code: str | None = None
    boundary: str | None = None
    evidence_class: str = 'DERIVED'
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Type hints are not runtime validation.  Causal ordering and epoch
        # scoping must reject floats/bools/strings rather than silently comparing
        # them as if they were authoritative sequence numbers.
        if type(self.schema_version) is not int or self.schema_version != 1: raise ValueError('UNSUPPORTED_DIAGNOSTIC_SCHEMA')
        if not EVENT_NAME.fullmatch(self.event_name): raise ValueError('INVALID_EVENT_NAME')
        if self.severity not in SEVERITIES: raise ValueError('INVALID_SEVERITY')
        if self.evidence_class not in EVIDENCE_CLASSES: raise ValueError('INVALID_EVIDENCE_CLASS')
        if not (self.event_id and self.invocation_id): raise ValueError('MISSING_IDENTITY')
        if (type(self.producer_seq) is not int or type(self.monotonic_ns) is not int
                or self.producer_seq < 0 or self.monotonic_ns < 0):
            raise ValueError('INVALID_CLOCK')
        if not isinstance(self.payload, dict): raise ValueError('INVALID_EVENT_PAYLOAD')
        if self.fight_epoch is not None and (type(self.fight_epoch) is not int or self.fight_epoch < 0):
            raise ValueError('INVALID_FIGHT_EPOCH')
        if self.turn_epoch is not None and (type(self.turn_epoch) is not int or self.turn_epoch < 0):
            raise ValueError('INVALID_EPOCH')
        if self.canonical_revision is not None and (type(self.canonical_revision) is not int or self.canonical_revision < 0):
            raise ValueError('INVALID_CANONICAL_REVISION')
        if self.owner_system is not None and not self.owner_system.startswith('anka_'): raise ValueError('INVALID_OWNER_SYSTEM')
        if self.physical_input_state is not None and self.physical_input_state not in ('NOT_SENT','SEND_STARTED','SENT','MAY_HAVE_SENT','UNKNOWN'): raise ValueError('INVALID_PHYSICAL_INPUT_STATE')
        if self.canonical_cursor is not None and (type(self.canonical_cursor) is not int or self.canonical_cursor < 0): raise ValueError('INVALID_CANONICAL_CURSOR')

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str,Any]) -> 'DiagnosticEvent':
        return cls(**data)

FINDING_CONFIDENCE = frozenset({'HIGH','MEDIUM','LOW','UNDETERMINED'})
EVIDENCE_COMPLETENESS = frozenset({'PRESENT','PRESENT_STALE','PARTIAL','MISSING','NOT_APPLICABLE','EXPORT_FAILED'})

@dataclass(frozen=True, slots=True)
class BoundaryExpectation:
    """One expected causal edge in an operation trace.

    This is descriptive only. It grants no gameplay authority.
    """
    event_name: str
    boundary: str
    owner_system: str
    evidence_section: str

    def __post_init__(self) -> None:
        if not EVENT_NAME.fullmatch(self.event_name): raise ValueError('INVALID_EXPECTED_EVENT_NAME')
        if not self.boundary: raise ValueError('MISSING_EXPECTED_BOUNDARY')
        if not self.owner_system.startswith('anka_'): raise ValueError('INVALID_EXPECTED_OWNER')
        if not self.evidence_section: raise ValueError('MISSING_EVIDENCE_SECTION')


@dataclass(frozen=True, slots=True)
class OperationTraceSpec:
    operation: str
    expectations: tuple[BoundaryExpectation, ...]
    correlation_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.operation: raise ValueError('MISSING_OPERATION')
        if not self.expectations: raise ValueError('EMPTY_TRACE_SPEC')
        if len({x.event_name for x in self.expectations}) != len(self.expectations):
            raise ValueError('DUPLICATE_TRACE_EVENT')
        allowed={'trace_id','action_id','account_id','fight_id','attempt_id','client_generation'}
        if (type(self.correlation_keys) is not tuple or len(set(self.correlation_keys))!=len(self.correlation_keys)
                or any(type(k) is not str or not k or (k not in allowed and not k.startswith('payload.')) for k in self.correlation_keys)):
            raise ValueError('INVALID_TRACE_CORRELATION_KEYS')


@dataclass(frozen=True, slots=True)
class DiagnosticFinding:
    finding_id: str
    failure_code: str
    first_divergent_boundary: str
    suspected_owner: str
    confidence: str
    supporting_evidence_ids: tuple[str, ...] = ()
    contradicting_evidence_ids: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    control_state: str = 'UNKNOWN'
    recommended_next_test: str = ''
    candidate_causes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.finding_id or not self.failure_code or not self.first_divergent_boundary:
            raise ValueError('INCOMPLETE_FINDING')
        if not self.suspected_owner.startswith('anka_'): raise ValueError('INVALID_FINDING_OWNER')
        if self.confidence not in FINDING_CONFIDENCE: raise ValueError('INVALID_FINDING_CONFIDENCE')

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
