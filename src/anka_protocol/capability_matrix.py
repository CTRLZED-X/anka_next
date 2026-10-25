"""P32 research-only evidence acceptance matrix for biweekly protocol reviews.

Pure analysis of already validated intake metadata and exact-source comparisons.
The output never certifies a client build, admits Canonical events, or authorizes input.
"""
from __future__ import annotations

from typing import Mapping
from collections import Counter

from anka_protocol.evidence_intake import CAPABILITIES, REQUIRED_CAPABILITIES, IntakeReport, evidence_binding_id, evidence_case_binding

# Only statuses actually emitted as a per-message comparison are accepted.
CASE_STATUSES = frozenset({
    'MATCHED_RESEARCH_ONLY', 'FIELD_MISMATCH', 'SOURCE_MESSAGE_NOT_FOUND',
    'SOURCE_SELECTOR_AMBIGUOUS', 'CAPABILITY_NOT_MAPPED_OR_CONTEXT_MISSING',
    'MULTIPLE_FACTS_FOR_ONE_SELECTOR', 'ORACLE_FIELDS_NOT_COMPARABLE',
})
CASE_FIELDS = {
    'actor_ap': {'actor_id', 'ap', 'value'},
    'actor_mp': {'actor_id', 'mp', 'value'},
    'actor_hp': {'actor_id', 'hp', 'max_hp', 'value'},
    'actor_range': {'actor_id', 'range', 'value'},
    'fight_start': {'fight_id'}, 'fight_end': {'fight_id'},
    'turn_start': {'fight_id', 'actor_id', 'turn_index'},
    'turn_end': {'fight_id', 'actor_id', 'turn_index'},
    'actor_cell': {'fight_id', 'actor_id', 'cell_id'},
    'spell_cast': {'fight_id', 'actor_id', 'spell_id', 'target_cell'},
}

ROLE_SET = frozenset({'leader', 'follower'})
MATCHED = 'MATCHED_RESEARCH_ONLY'
MISMATCH = 'FIELD_MISMATCH'


def _comparison_consistent(intake: IntakeReport, comparison: Mapping) -> bool:
    """Fail closed if the comparison's case-index or success counts are contradictory."""
    # Comparisons are ordered by manifest case position. Similar case counts
    # from an unrelated capture are NOT the same evidence. P42 prevents stale
    # (or accidentally mixed) comparison output from inflating research coverage.
    if comparison.get('comparison_binding') != evidence_binding_id(
            intake.archive_sha256, intake.protocol_build, intake.adapter_id):
        return False
    if type(comparison.get('case_count')) is not int or comparison['case_count'] != intake.case_count:
        return False
    cases = comparison.get('case_results')
    if not isinstance(cases, list) or len(cases) != intake.case_count:
        return False
    if not isinstance(comparison.get('matched_cases'), int) or isinstance(comparison.get('matched_cases'), bool):
        return False
    if not isinstance(comparison.get('mismatched_cases'), int) or isinstance(comparison.get('mismatched_cases'), bool):
        return False
    seen = set()
    for entry in cases:
        if not isinstance(entry, dict):
            return False
        idx = entry.get('case_index')
        if type(idx) is not int or idx < 0 or idx >= intake.case_count or idx in seen:
            return False
        capability = intake.case_evidence[idx][0]
        status = entry.get('status')
        if (entry.get('capability') != capability or type(status) is not str
            or status not in CASE_STATUSES):
            return False
        if entry.get('case_binding') != evidence_case_binding(
                intake.archive_sha256, intake.protocol_build, intake.adapter_id,
                idx, intake.case_evidence[idx]):
            return False
        fields = entry.get('mismatch_fields')
        if (type(fields) is not list or len(fields) > 24
            or any(type(f) is not str for f in fields)
            or fields != sorted(set(fields))):
            return False
        if status == MISMATCH:
            if not fields or not set(fields).issubset(CASE_FIELDS.get(capability, set())):
                return False
        elif fields:
            return False
        seen.add(idx)
    # Report-level diagnostic distribution must match the actual rows.
    observed = Counter(row['status'] for row in cases)
    finding_counts = comparison.get('finding_counts')
    if (type(finding_counts) is not dict or set(finding_counts) != set(observed)
        or any(type(v) is not int or v != observed[k] for k,v in finding_counts.items())):
        return False
    if comparison['matched_cases'] != sum(row['status'] == MATCHED for row in cases):
        return False
    if comparison['mismatched_cases'] != sum(row['status'] == MISMATCH for row in cases):
        return False
    all_match = all(row['status'] == MATCHED for row in cases)
    if (comparison.get('status') == 'RESEARCH_COMPARISON_MATCHED_NOT_CERTIFIED') != all_match:
        return False
    return True


def assess_capabilities(intake: IntakeReport, comparison: Mapping) -> dict:
    """Summarize *research* coverage per capability, independently for CRA/ENU roles.

    Archive case order is the join key; identifiers and raw oracle values never
    leave the source intake/comparator. An unavailable adapter must not be
    misreported as a mismatched value. Both-account coverage is required for
    required capabilities in the research grade, but is never live certification.
    """
    if len(intake.case_evidence) != intake.case_count or any(
        len(entry) != 4 or entry[0] not in CAPABILITIES or entry[1] not in ROLE_SET | {'other'}
        or type(entry[2]) is not bool or type(entry[3]) is not bool
        for entry in intake.case_evidence
    ):
        comparison_valid = False
    else:
        comparison_valid = _comparison_consistent(intake, comparison) if comparison.get('case_results') else False
    case_results = {row['case_index']: row['status'] for row in comparison.get('case_results', [])} if comparison_valid else {}
    result = []
    required_blocked = []
    for cap in sorted(CAPABILITIES):
        selected = [(idx, role, witnessed, has_selector)
                    for idx, (c, role, witnessed, has_selector) in enumerate(intake.case_evidence)
                    if c == cap]
        matched = [r for r in selected if case_results.get(r[0]) == MATCHED]
        mismatches = [r for r in selected if case_results.get(r[0]) == MISMATCH]
        unresolved = [r for r in selected if r not in matched and r not in mismatches]
        roles = sorted({r[1] for r in selected})
        matched_roles = sorted({r[1] for r in matched})
        reasons = []
        if not selected:
            reasons.append('CAPABILITY_EVIDENCE_MISSING')
        else:
            if not comparison_valid:
                reasons.append('COMPARISON_NOT_COMPLETE_OR_INCONSISTENT')
            if mismatches:
                reasons.append('SEMANTIC_FIELD_MISMATCH')
            if unresolved and comparison_valid:
                reasons.append('CASE_COMPARISON_UNRESOLVED')
            if any(not r[2] for r in selected):
                reasons.append('WITNESS_FILE_MISSING')
            if any(not r[3] for r in selected):
                reasons.append('EXACT_SOURCE_SELECTOR_MISSING')
            if cap in REQUIRED_CAPABILITIES and not ROLE_SET.issubset(matched_roles):
                reasons.append('LEADER_FOLLOWER_COVERAGE_INCOMPLETE')
        if reasons:
            if cap in REQUIRED_CAPABILITIES:
                required_blocked.append(cap)
            status = ('NOT_OBSERVED' if not selected else
                      'FIELD_MISMATCH' if mismatches else
                      'INCOMPLETE_RESEARCH_EVIDENCE')
        else:
            status = 'RESEARCH_MATCHED_NOT_CERTIFIED'
        result.append({
            'capability': cap, 'required': cap in REQUIRED_CAPABILITIES,
            'status': status, 'case_count': len(selected),
            'matched_cases': len(matched), 'mismatched_cases': len(mismatches),
            'unresolved_cases': len(unresolved), 'witnessed_cases': sum(r[2] for r in selected),
            'selected_cases': sum(r[3] for r in selected),
            'roles_declared': roles, 'roles_with_matching_oracles_claimed': matched_roles,
            'blockers': reasons,
        })
    global_fail = not comparison_valid or any(item['status'] == 'FIELD_MISMATCH' for item in result)
    return {
        'status': ('RESEARCH_COMPARISON_BLOCKED' if global_fail else
                   'RESEARCH_COVERAGE_INCOMPLETE' if required_blocked else
                   'RESEARCH_COVERAGE_MATCHED_NOT_CERTIFIED'),
        'protocol_build': intake.protocol_build,
        'required_capabilities': sorted(REQUIRED_CAPABILITIES),
        'required_blocked_capabilities': required_blocked,
        'capabilities': result,
        'comparison_status': str(comparison.get('status', 'NO_COMPARISON'))[:100],
        'research_only': True,
        'current_build_certified': False, 'live_semantic_certified': False,
        'canonical_commits': 0, 'adapter_activated': False,
        'physical_input_sent': False,
        'remaining_live_gates': [
            'ORACLE_INDEPENDENCE_NOT_VERIFIED',
            'REAL_CURRENT_CLIENT_SOURCE_AND_ACCOUNT_IDENTITY_NOT_CERTIFIED',
            'CASE_ACCOUNT_ROLES_DECLARED_NOT_INDEPENDENTLY_ATTESTED',
            'LIVE_EVENT_ORDER_AND_OUTCOME_ACCEPTANCE_PENDING',
            'WINDOW_AND_PHYSICAL_EXECUTION_ACCEPTANCE_PENDING',
        ],
    }
