"""P10 read-only *synthetic* protocol-adapter contract qualification.

An adapter passing this suite has NOT been certified against a real client.
Fixture authorship and adapter implementation are independent; tests compare
actual typed facts to exact golden expectations. No canonical admission exists.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json
from typing import Callable
from anka_contracts.protocol import WireMessage
from anka_contracts.semantic import SemanticResult
from anka_protocol.adapters.historical_semantic import HistoricalContext

MAX_SUITE_BYTES = 128 * 1024
MAX_CASES = 64
MAX_BODY_BYTES = 16384
REQUIRED_SCENARIOS = frozenset({
    'resource_absolute', 'cooldown_snapshot', 'hp_with_identity',
    'hp_without_identity', 'malformed_wire', 'wrong_direction',
    'unknown_wire', 'build_mismatch', 'branch_drift', 'repeated_occurrence',
})
EXPECTED_STATUSES = frozenset({
    'CANDIDATES_ONLY', 'NO_SEMANTIC_MAPPING', 'QUARANTINED',
    'BUILD_MISMATCH', 'CONTEXT_MISSING'
})
_FIELDS = {'kind', 'actor_id', 'resource', 'value', 'maximum', 'cooldowns'}

@dataclass(frozen=True, slots=True)
class QualificationCase:
    case_id: str
    scenario: str
    requested_build: str
    name: str
    direction: str
    body: bytes
    packet_number: int
    generation: int
    message_index: int
    context: HistoricalContext | None
    expected_status: str
    expected_failure: str | None
    expected_candidates: tuple[dict, ...]

@dataclass(frozen=True, slots=True)
class QualificationResult:
    case_id: str
    scenario: str
    passed: bool
    failure_codes: tuple[str, ...]
    actual_status: str
    observed_candidate_count: int
    # Never include packet bytes or raw source paths in reports.
    def to_dict(self) -> dict:
        return {'id':self.case_id,'scenario':self.scenario,'passed':self.passed,
                'failure_codes':list(self.failure_codes),'status':self.actual_status,
                'observed_candidate_count':self.observed_candidate_count}

@dataclass(frozen=True,slots=True)
class QualificationReport:
    adapter_id: str
    historical_build: str
    requested_build: str
    fixture_sha256: str
    adapter_sha256: str
    cases: tuple[QualificationResult,...]
    missing_scenarios: tuple[str,...]
    status: str
    # Synthetic fixtures cannot grant authority, regardless of green test results.
    live_semantic_certified: bool = False
    canonical_commits: int = 0
    physical_input_sent: bool = False
    def __post_init__(self) -> None:
        if self.live_semantic_certified or self.canonical_commits!=0 or self.physical_input_sent:
            raise ValueError('QUALIFICATION_LIVE_AUTHORITY_FORBIDDEN')
    def to_dict(self) -> dict:
        blockers=['CURRENT_BUILD_RAW_EVIDENCE_ABSENT',
                  'INDEPENDENT_SEMANTIC_ORACLES_ABSENT',
                  'WINDOW_ACCOUNT_ATTESTATION_ABSENT',
                  'WINDOWS_HOST_AND_LIVE_REPLAY_ACCEPTANCE_PENDING']
        if self.requested_build!=self.historical_build:
            blockers.insert(0,'REQUESTED_BUILD_UNSUPPORTED')
        if self.missing_scenarios:
            blockers.insert(0,'MANDATORY_SCENARIOS_MISSING')
        if any(not c.passed for c in self.cases):
            blockers.insert(0,'SYNTHETIC_CONTRACT_REGRESSION')
        return {'status':self.status,'adapter_id':self.adapter_id,
                'historical_build':self.historical_build,'requested_build':self.requested_build,
                'fixture_sha256':self.fixture_sha256,'adapter_sha256':self.adapter_sha256,
                'passed':sum(c.passed for c in self.cases), 'total':len(self.cases),
                'cases':[c.to_dict() for c in self.cases],
                'missing_scenarios':list(self.missing_scenarios),
                'blocked_gates':blockers,
                'live_semantic_certified':False,'canonical_commits':0,
                'physical_input_sent':False}


def _plain_dict(row: object, required: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(row,dict) or required-row.keys() or row.keys()-(required|optional):
        raise ValueError('QUALIFICATION_FIXTURE_SCHEMA_INVALID')
    return row


def _text(value: object, label: str, limit: int = 96) -> str:
    if not isinstance(value,str) or not 1<=len(value)<=limit or not value.isascii():
        raise ValueError('QUALIFICATION_'+label+'_INVALID')
    return value


def load_suite(path: Path) -> tuple[str, str, str, tuple[QualificationCase,...]]:
    file=Path(path)
    if file.stat().st_size>MAX_SUITE_BYTES:
        raise ValueError('QUALIFICATION_FIXTURE_SIZE_EXCEEDED')
    raw=file.read_bytes()
    if len(raw)>MAX_SUITE_BYTES:
        raise ValueError('QUALIFICATION_FIXTURE_SIZE_EXCEEDED')
    doc=_plain_dict(json.loads(raw),{'schema','adapter_id','historical_build','evidence_type','cases'})
    if type(doc['schema']) is not int or doc['schema']!=1 or doc['evidence_type']!='SYNTHETIC_ONLY':
        raise ValueError('QUALIFICATION_FIXTURE_NOT_SYNTHETIC')
    adapter=_text(doc['adapter_id'],'ADAPTER')
    build=_text(doc['historical_build'],'BUILD')
    cases=doc['cases']
    if not isinstance(cases,list) or not 1<=len(cases)<=MAX_CASES:
        raise ValueError('QUALIFICATION_CASE_COUNT_INVALID')
    items=[];seen=set()
    for row in cases:
        x=_plain_dict(row,{'id','scenario','requested_build','name','direction','body_hex',
            'packet_number','generation','message_index','context','expected_status','expected_failure','expected_candidates'})
        case_id=_text(x['id'],'CASE_ID')
        if case_id in seen:raise ValueError('QUALIFICATION_DUPLICATE_CASE_ID')
        seen.add(case_id)
        scenario=_text(x['scenario'],'SCENARIO')
        req=_text(x['requested_build'],'BUILD')
        name=_text(x['name'],'WIRE_NAME')
        if x['direction'] not in ('server_to_client','client_to_server'):
            raise ValueError('QUALIFICATION_DIRECTION_INVALID')
        bodyhex=x['body_hex']
        if not isinstance(bodyhex,str) or len(bodyhex)>MAX_BODY_BYTES*2:
            raise ValueError('QUALIFICATION_BODY_INVALID')
        try: body=bytes.fromhex(bodyhex)
        except ValueError as exc:raise ValueError('QUALIFICATION_BODY_INVALID') from exc
        for field in ('packet_number','generation','message_index'):
            if type(x[field]) is not int or x[field]<0:
                raise ValueError('QUALIFICATION_ORDINAL_INVALID')
        ctx=x['context']
        if ctx is not None:
            ctx=_plain_dict(ctx,{'local_actor_id','fight_active','identity_verified'})
            if ctx['local_actor_id'] is not None and (type(ctx['local_actor_id']) is not int or ctx['local_actor_id']==0):
                raise ValueError('QUALIFICATION_CONTEXT_INVALID')
            if type(ctx['fight_active']) is not bool or type(ctx['identity_verified']) is not bool:
                raise ValueError('QUALIFICATION_CONTEXT_INVALID')
            ctx=HistoricalContext(**ctx)
        if x['expected_status'] not in EXPECTED_STATUSES:
            raise ValueError('QUALIFICATION_EXPECTATION_INVALID')
        failure=x['expected_failure']
        if failure is not None:_text(failure,'EXPECTED_FAILURE')
        exp=x['expected_candidates']
        if not isinstance(exp,list) or len(exp)>200:
            raise ValueError('QUALIFICATION_EXPECTATION_INVALID')
        for fact in exp:
            _plain_dict(fact, _FIELDS)
            if not isinstance(fact['cooldowns'],list):raise ValueError('QUALIFICATION_EXPECTATION_INVALID')
        if bool(exp)!=(x['expected_status']=='CANDIDATES_ONLY'):
            raise ValueError('QUALIFICATION_EXPECTATION_INVALID')
        items.append(QualificationCase(case_id,scenario,req,name,x['direction'],body,
            x['packet_number'],x['generation'],x['message_index'],ctx,
            x['expected_status'],failure,tuple(exp)))
    return adapter,build,sha256(raw).hexdigest(),tuple(items)


def _fact_dict(draft) -> dict:
    return {'kind':draft.kind,'actor_id':draft.actor_id,'resource':draft.resource,
            'value':draft.value,'maximum':draft.maximum,
            'cooldowns':[[spell,remaining] for spell,remaining in draft.cooldowns]}


def run_suite(path:Path, *, requested_build:str, adapter_factory:Callable,
              adapter_id:str, historical_build:str, adapter_sha256:str) -> QualificationReport:
    declared,declared_build,digest,cases=load_suite(path)
    if declared!=adapter_id or declared_build!=historical_build:
        raise ValueError('QUALIFICATION_ADAPTER_OR_BUILD_MISMATCH')
    if not isinstance(requested_build,str) or not requested_build or len(requested_build)>96:
        raise ValueError('QUALIFICATION_REQUESTED_BUILD_INVALID')
    missing=tuple(sorted(REQUIRED_SCENARIOS-{x.scenario for x in cases}))
    rows=[]
    for case in cases:
        codes=[]
        try:
            decoder=adapter_factory(requested_build=case.requested_build)
            wire=WireMessage(case.direction,case.name,case.body,
                case.packet_number,'qualification-fixture',case.generation,case.message_index)
            result=decoder.decode(wire,context=case.context)
            if not isinstance(result,SemanticResult):
                codes.append('SEMANTIC_RESULT_CONTRACT_VIOLATION')
                actual='INVALID_RESULT';n=0
            else:
                actual=result.status;n=len(result.candidates)
                if actual!=case.expected_status:codes.append('STATUS_MISMATCH')
                if result.failure_code!=case.expected_failure:codes.append('FAILURE_CODE_MISMATCH')
                if [_fact_dict(d) for d in result.candidates]!=list(case.expected_candidates):
                    codes.append('CANONICAL_FACT_MISMATCH')
                if (result.adapter_id,result.protocol_build,result.wire_name)!=(adapter_id,case.requested_build,case.name):
                    codes.append('PROVENANCE_MISMATCH')
                if any(d.authority!='HISTORICAL_CANDIDATE_ONLY' or d.evidence.message_index!=case.message_index
                       or d.evidence.packet_number!=case.packet_number or d.evidence.transport_generation!=case.generation
                       for d in result.candidates):
                    codes.append('AUTHORITY_OR_EVIDENCE_MISMATCH')
        except Exception:
            # A thrown exception must never disappear or be mistaken for a pass.
            codes.append('ADAPTER_EXCEPTION');actual='EXCEPTION';n=0
        rows.append(QualificationResult(case.case_id,case.scenario,not codes,tuple(codes),actual,n))
    success=(all(x.passed for x in rows) and not missing and requested_build==historical_build)
    return QualificationReport(adapter_id,historical_build,requested_build,digest,adapter_sha256,
        tuple(rows),missing,'SYNTHETIC_CONTRACT_PASS_LIVE_BLOCKED' if success else 'QUALIFICATION_FAILED_LIVE_BLOCKED')
