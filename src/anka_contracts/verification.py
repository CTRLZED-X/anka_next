"""Machine-readable verification receipt contracts used by definitive quality gates.

These DTOs deliberately distinguish PASS/FAIL/SKIP/NOT_RUN/MISSING_EVIDENCE.
A receipt records the hashes that make a cached result meaningful; changing an
input requires a new receipt.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Literal
import re

CheckStatus = Literal['PASS','FAIL','SKIP','NOT_RUN','MISSING_EVIDENCE']
_STATUSES = frozenset({'PASS','FAIL','SKIP','NOT_RUN','MISSING_EVIDENCE'})
_HEX64 = re.compile(r'^[0-9a-f]{64}$')
_GATE = re.compile(r'^Q(?:[0-9]|1[0-3])(?:[-A-Z0-9_]*)$')

@dataclass(frozen=True, slots=True)
class VerificationCheck:
    code: str
    status: CheckStatus
    detail: str
    evidence: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.code) is not str or not self.code or len(self.code) > 128:
            raise ValueError('INVALID_VERIFICATION_CHECK_CODE')
        if self.status not in _STATUSES:
            raise ValueError('INVALID_VERIFICATION_CHECK_STATUS')
        if type(self.detail) is not str or not self.detail or len(self.detail) > 2000:
            raise ValueError('INVALID_VERIFICATION_CHECK_DETAIL')
        if any(type(x) is not str or not x for x in self.evidence):
            raise ValueError('INVALID_VERIFICATION_CHECK_EVIDENCE')

@dataclass(frozen=True, slots=True)
class VerificationCounts:
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    not_run: int = 0
    missing_evidence: int = 0

    def __post_init__(self):
        values=(self.passed,self.failed,self.skipped,self.not_run,self.missing_evidence)
        if any(type(v) is not int or v < 0 for v in values):
            raise ValueError('INVALID_VERIFICATION_COUNTS')

@dataclass(frozen=True, slots=True)
class VerificationReceipt:
    schema_version: int
    gate_id: str
    milestone: str
    status: CheckStatus
    generated_utc: str
    source_tree_sha256: str
    config_schema_sha256: str | None
    effective_config_sha256: str | None
    python_version: str
    dependency_manifest_sha256: str | None
    observed_client_build: str | None
    protocol_adapter_release: str | None
    kernel_tree_sha256: str | None
    game_data_tree_sha256: str | None
    calibration_sha256: str | None
    fixture_manifest_sha256: str | None
    check_counts: VerificationCounts
    test_counts: VerificationCounts
    environment: tuple[tuple[str,str], ...]
    duration_ms: int
    physical_input_count: int
    physical_input_state: str
    checks: tuple[VerificationCheck, ...]
    known_limitations: tuple[str, ...]
    artifacts: tuple[tuple[str,str], ...] = ()

    def __post_init__(self):
        if self.schema_version != 1: raise ValueError('UNSUPPORTED_VERIFICATION_RECEIPT_SCHEMA')
        if not _GATE.fullmatch(self.gate_id): raise ValueError('INVALID_GATE_ID')
        if type(self.milestone) is not str or not self.milestone.startswith('M'): raise ValueError('INVALID_MILESTONE_ID')
        if self.status not in _STATUSES: raise ValueError('INVALID_VERIFICATION_STATUS')
        for value,code in ((self.source_tree_sha256,'INVALID_SOURCE_TREE_HASH'),):
            if not _HEX64.fullmatch(value): raise ValueError(code)
        for value,code in (
            (self.config_schema_sha256,'INVALID_CONFIG_SCHEMA_HASH'),
            (self.effective_config_sha256,'INVALID_EFFECTIVE_CONFIG_HASH'),
            (self.dependency_manifest_sha256,'INVALID_DEPENDENCY_HASH'),
            (self.kernel_tree_sha256,'INVALID_KERNEL_HASH'),
            (self.game_data_tree_sha256,'INVALID_GAME_DATA_HASH'),
            (self.calibration_sha256,'INVALID_CALIBRATION_HASH'),
            (self.fixture_manifest_sha256,'INVALID_FIXTURE_HASH'),
        ):
            if value is not None and not _HEX64.fullmatch(value): raise ValueError(code)
        if type(self.duration_ms) is not int or self.duration_ms < 0: raise ValueError('INVALID_VERIFICATION_DURATION')
        if type(self.physical_input_count) is not int or self.physical_input_count < 0: raise ValueError('INVALID_PHYSICAL_INPUT_COUNT')
        if self.physical_input_state not in ('DISABLED','FAKE_ONLY','POSSIBLE','OBSERVED'):
            raise ValueError('INVALID_PHYSICAL_INPUT_STATE')
        if not self.checks: raise ValueError('VERIFICATION_CHECKS_REQUIRED')
        expected=VerificationCounts(
            passed=sum(c.status=='PASS' for c in self.checks),
            failed=sum(c.status=='FAIL' for c in self.checks),
            skipped=sum(c.status=='SKIP' for c in self.checks),
            not_run=sum(c.status=='NOT_RUN' for c in self.checks),
            missing_evidence=sum(c.status=='MISSING_EVIDENCE' for c in self.checks),
        )
        if self.check_counts != expected: raise ValueError('VERIFICATION_CHECK_COUNT_MISMATCH')
        if self.status == 'PASS' and (self.check_counts.failed or self.check_counts.not_run or self.check_counts.missing_evidence or self.test_counts.failed or self.test_counts.not_run or self.test_counts.missing_evidence):
            raise ValueError('PASS_RECEIPT_HAS_UNSATISFIED_CHECKS')
        if any(type(k) is not str or type(v) is not str or not k or not v for k,v in self.environment):
            raise ValueError('INVALID_VERIFICATION_ENVIRONMENT')
        if any(type(x) is not str or not x for x in self.known_limitations):
            raise ValueError('INVALID_VERIFICATION_LIMITATION')
        for path,digest in self.artifacts:
            if not path or not _HEX64.fullmatch(digest): raise ValueError('INVALID_VERIFICATION_ARTIFACT')

    def to_dict(self) -> dict:
        data=asdict(self)
        data['check_counts']=asdict(self.check_counts)
        data['test_counts']=asdict(self.test_counts)
        data['checks']=[asdict(x) for x in self.checks]
        data['environment']={k:v for k,v in self.environment}
        data['known_limitations']=list(self.known_limitations)
        data['artifacts']={k:v for k,v in self.artifacts}
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'VerificationReceipt':
        d=dict(data)
        d['check_counts']=VerificationCounts(**d['check_counts'])
        d['test_counts']=VerificationCounts(**d['test_counts'])
        d['checks']=tuple(VerificationCheck(**x) for x in d['checks'])
        env=d.get('environment',{})
        d['environment']=tuple(sorted(env.items())) if isinstance(env,dict) else tuple(tuple(x) for x in env)
        d['known_limitations']=tuple(d.get('known_limitations',()))
        artifacts=d.get('artifacts',{})
        d['artifacts']=tuple(sorted(artifacts.items())) if isinstance(artifacts,dict) else tuple(tuple(x) for x in artifacts)
        return cls(**d)

_MILESTONE = re.compile(r'^M(?:[0-9]|1[0-3])(?:[-A-Z0-9_]*)$')

@dataclass(frozen=True, slots=True)
class MilestoneReceipt:
    """Evidence receipt for roadmap milestones that do not have a dedicated Q gate.

    It deliberately cannot substitute for a later live/Windows quality gate.  The
    ``verification_scope`` field must say exactly what was proven.
    """
    schema_version: int
    milestone_id: str
    status: CheckStatus
    verification_scope: str
    generated_utc: str
    source_tree_sha256: str
    test_counts: VerificationCounts
    duration_ms: int
    physical_input_count: int
    physical_input_state: str
    checks: tuple[VerificationCheck, ...]
    known_limitations: tuple[str, ...]
    artifacts: tuple[tuple[str,str], ...] = ()

    def __post_init__(self):
        if self.schema_version != 1: raise ValueError('UNSUPPORTED_MILESTONE_RECEIPT_SCHEMA')
        if not _MILESTONE.fullmatch(self.milestone_id): raise ValueError('INVALID_MILESTONE_RECEIPT_ID')
        if self.status not in _STATUSES: raise ValueError('INVALID_MILESTONE_RECEIPT_STATUS')
        if not self.verification_scope: raise ValueError('MILESTONE_VERIFICATION_SCOPE_REQUIRED')
        if not _HEX64.fullmatch(self.source_tree_sha256): raise ValueError('INVALID_MILESTONE_SOURCE_HASH')
        if type(self.duration_ms) is not int or self.duration_ms < 0: raise ValueError('INVALID_MILESTONE_DURATION')
        if type(self.physical_input_count) is not int or self.physical_input_count < 0: raise ValueError('INVALID_MILESTONE_INPUT_COUNT')
        if self.physical_input_state not in ('DISABLED','FAKE_ONLY','POSSIBLE','OBSERVED'):
            raise ValueError('INVALID_MILESTONE_INPUT_STATE')
        if not self.checks: raise ValueError('MILESTONE_CHECKS_REQUIRED')
        if self.status == 'PASS' and (any(c.status!='PASS' for c in self.checks) or self.test_counts.failed or self.test_counts.not_run or self.test_counts.missing_evidence):
            raise ValueError('PASS_MILESTONE_HAS_UNSATISFIED_EVIDENCE')
        if any(type(x) is not str or not x for x in self.known_limitations):
            raise ValueError('INVALID_MILESTONE_LIMITATION')
        for path,digest in self.artifacts:
            if not path or not _HEX64.fullmatch(digest): raise ValueError('INVALID_MILESTONE_ARTIFACT')

    def to_dict(self) -> dict:
        data=asdict(self)
        data['test_counts']=asdict(self.test_counts)
        data['checks']=[asdict(x) for x in self.checks]
        data['known_limitations']=list(self.known_limitations)
        data['artifacts']={k:v for k,v in self.artifacts}
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'MilestoneReceipt':
        d=dict(data)
        d['test_counts']=VerificationCounts(**d['test_counts'])
        d['checks']=tuple(VerificationCheck(**x) for x in d['checks'])
        d['known_limitations']=tuple(d.get('known_limitations',()))
        artifacts=d.get('artifacts',{})
        d['artifacts']=tuple(sorted(artifacts.items())) if isinstance(artifacts,dict) else tuple(tuple(x) for x in artifacts)
        return cls(**d)
