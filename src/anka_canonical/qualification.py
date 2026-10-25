"""P9 read-only canonical evidence qualification, never live admission.

A structurally valid decoded value is not necessarily a trusted game fact.
This research gate tests provenance, capture continuity claims and conflicts,
without issuing live-state authority or interpreting a flag as certification.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from collections import Counter
from hashlib import sha256
import json
from typing import Sequence
from anka_contracts.canonical import CanonicalDraft

MAX_REVIEW_ITEMS = 4096
_TRANSPORT = frozenset({'UNKNOWN', 'INCOMPLETE', 'OBSERVED_NO_GAPS'})
_IDENTITY = frozenset({'UNKNOWN', 'PROVISIONAL', 'INDEPENDENTLY_OBSERVED'})

@dataclass(frozen=True, slots=True)
class ResearchContext:
    expected_build: str
    expected_adapter: str
    transport: str = 'UNKNOWN'
    identity: str = 'UNKNOWN'
    # All of these labels are observational; none is a grant of authority.
    def __post_init__(self) -> None:
        for item in (self.expected_build, self.expected_adapter):
            if not isinstance(item, str) or not 1 <= len(item) <= 96 or not item.isascii():
                raise ValueError('QUALIFICATION_IDENTITY_INVALID')
        if self.transport not in _TRANSPORT:
            raise ValueError('QUALIFICATION_TRANSPORT_INVALID')
        if self.identity not in _IDENTITY:
            raise ValueError('QUALIFICATION_ACCOUNT_STATUS_INVALID')

@dataclass(frozen=True, slots=True)
class ResearchReview:
    status: str
    inspected: int
    unique: int
    reason_codes: tuple[str, ...]
    kinds: tuple[tuple[str, int], ...]
    # Deliberately no field named certified, approved or admitted.
    committed_events: int = 0
    live_state_mutated: bool = False
    actionable: bool = False
    def to_dict(self) -> dict:
        return {'status': self.status, 'inspected': self.inspected, 'unique': self.unique,
                'reason_codes': list(self.reason_codes), 'kinds': dict(self.kinds),
                'committed_events': self.committed_events,
                'live_state_mutated': self.live_state_mutated, 'actionable': self.actionable}


def _fingerprint(draft: CanonicalDraft) -> str:
    raw = json.dumps(asdict(draft), sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return sha256(raw.encode('ascii')).hexdigest()


def review_candidates(candidates: Sequence[CanonicalDraft], context: ResearchContext) -> ResearchReview:
    """Qualify *research evidence only*; cannot write state or certify a build.

    Any invalid observation makes the batch quarantined. Conflicting payloads
    sharing an evidence coordinate are rejected even when individually valid.
    """
    if not isinstance(context, ResearchContext):
        raise TypeError('QUALIFICATION_CONTEXT_REQUIRED')
    if not isinstance(candidates, (tuple, list)):
        raise TypeError('QUALIFICATION_SEQUENCE_REQUIRED')
    count = len(candidates)
    if count > MAX_REVIEW_ITEMS:
        return ResearchReview('QUARANTINED', count, 0, ('REVIEW_CAPACITY_EXCEEDED',), ())
    reasons = set()
    if context.transport == 'UNKNOWN':
        reasons.add('TRANSPORT_EVIDENCE_MISSING')
    elif context.transport == 'INCOMPLETE':
        reasons.add('TRANSPORT_INCOMPLETE')
    else:
        # A capture with no *observed* gaps is not proof against driver loss.
        reasons.add('DRIVER_CAPTURE_COMPLETENESS_UNPROVEN')
    if context.identity == 'UNKNOWN':
        reasons.add('ACCOUNT_IDENTITY_MISSING')
    elif context.identity == 'PROVISIONAL':
        reasons.add('ACCOUNT_IDENTITY_PROVISIONAL')
    else:
        reasons.add('ACCOUNT_IDENTITY_NOT_CRYPTICALLY_BOUND_TO_PACKETS')
    reasons.add('CURRENT_BUILD_SEMANTIC_CERTIFICATION_MISSING')
    by_coordinate: dict[tuple, str] = {}
    kinds: Counter[str] = Counter()
    for draft in candidates:
        if not isinstance(draft, CanonicalDraft):
            reasons.add('NON_CANONICAL_DRAFT')
            continue
        if draft.authority != 'HISTORICAL_CANDIDATE_ONLY':
            reasons.add('SOURCE_AUTHORITY_INVALID')
        proof = draft.evidence
        if proof.protocol_build != context.expected_build:
            reasons.add('BUILD_MISMATCH')
        if proof.adapter_id != context.expected_adapter:
            reasons.add('ADAPTER_MISMATCH')
        key = (proof.protocol_build, proof.adapter_id, proof.flow_digest,
               proof.transport_generation, proof.packet_number, proof.message_index,
               draft.kind, draft.actor_id, draft.resource)
        fingerprint = _fingerprint(draft)
        if key in by_coordinate:
            if by_coordinate[key] == fingerprint:
                reasons.add('DUPLICATE_OBSERVATION')
            else:
                reasons.add('CONFLICTING_OBSERVATION')
        else:
            by_coordinate[key] = fingerprint
        kinds[draft.kind] += 1
    if not count:
        reasons.add('NO_CANDIDATES')
    blockers = {'NON_CANONICAL_DRAFT', 'SOURCE_AUTHORITY_INVALID', 'BUILD_MISMATCH',
                'ADAPTER_MISMATCH', 'DUPLICATE_OBSERVATION',
                'CONFLICTING_OBSERVATION', 'REVIEW_CAPACITY_EXCEEDED'}
    status = 'QUARANTINED' if reasons & blockers else 'RESEARCH_ONLY'
    return ResearchReview(status, count, len(by_coordinate), tuple(sorted(reasons)),
                          tuple(sorted(kinds.items())))
