"""P11 diagnostic-only multi-account observation reconciliation.

A common SQLite snapshot cannot prove synchronized server observations.
This component never grants game-input authority or converts fixture data into
live facts. Invalid or incomplete diagnostic views fail closed with reason codes.
"""
from __future__ import annotations

from collections.abc import Mapping

from anka_contracts.fight_audit import AccountExpectation, FightEvidenceReport

_DECISION_FIELDS = ('hp', 'max_hp', 'AP', 'MP', 'cell_id', 'cooldowns')
_NONBLOCKING = frozenset({
    'NO_SHARED_CURRENT_BUILD_EVENT_PROOF', 'CURRENT_BUILD_PROTOCOL_NOT_CERTIFIED'
})


def compare_fight_views(
    expectations: tuple[AccountExpectation, ...],
    views: Mapping[str, object],
    *,
    same_database_snapshot: bool = False,
) -> FightEvidenceReport:
    if (type(expectations) is not tuple or not 1 <= len(expectations) <= 8
            or any(not isinstance(item, AccountExpectation) for item in expectations)):
        raise ValueError('FIGHT_AUDIT_ACCOUNTS_INVALID')
    if (len({e.session_id for e in expectations}) != len(expectations)
            or len({e.account_id for e in expectations}) != len(expectations)
            or len({e.local_actor_id for e in expectations}) != len(expectations)):
        raise ValueError('FIGHT_AUDIT_DUPLICATE_ACCOUNT')
    if not isinstance(views, Mapping):
        raise TypeError('FIGHT_AUDIT_VIEWS_REQUIRED')
    if type(same_database_snapshot) is not bool:
        raise ValueError('FIGHT_AUDIT_SNAPSHOT_FLAG_INVALID')

    reasons: set[str] = set()
    findings: list[dict] = []
    fights: set[str] = set()
    owners: set[int] = set()
    if not same_database_snapshot:
        reasons.add('MULTI_SESSION_SNAPSHOT_NOT_ATTESTED')

    for expected in expectations:
        item = views.get(expected.session_id)
        snapshot = item.get('snapshot') if isinstance(item, Mapping) else None
        trace = item.get('trace') if isinstance(item, Mapping) else None
        problems: set[str] = set()
        missing_decision_fields: list[str] = list(_DECISION_FIELDS)
        if not isinstance(snapshot, Mapping):
            problems.add('MISSING_SESSION_SNAPSHOT')
        else:
            if (snapshot.get('session_id'), snapshot.get('account_id'),
                    snapshot.get('account_generation')) != (
                    expected.session_id, expected.account_id, expected.account_generation):
                problems.add('ACCOUNT_IDENTITY_OR_GENERATION_MISMATCH')
            if snapshot.get('authority') != 'SYNTHETIC_FIXTURE_ONLY' or snapshot.get('actionable') is not False:
                problems.add('UNSUPPORTED_STATE_AUTHORITY')
            if snapshot.get('phase') != 'IN_FIGHT':
                problems.add('NO_ACTIVE_FIGHT')

            actors = snapshot.get('actors')
            if not isinstance(actors, Mapping):
                problems.add('ACTOR_STATE_INVALID')
                actors = {}
            local_actor = actors.get(str(expected.local_actor_id))
            if local_actor is None:
                problems.add('LOCAL_ACTOR_NOT_OBSERVED')
            elif not isinstance(local_actor, Mapping):
                problems.add('LOCAL_ACTOR_STATE_INVALID')
            else:
                missing_decision_fields = [key for key in _DECISION_FIELDS if local_actor.get(key) is None]

            fight = snapshot.get('fight_id')
            owner = snapshot.get('turn_owner_id')
            if isinstance(fight, str) and fight:
                fights.add(fight)
            else:
                problems.add('FIGHT_ID_UNPROVEN')
            if type(owner) is int and owner != 0:
                owners.add(owner)
                if str(owner) not in actors:
                    problems.add('TURN_OWNER_NOT_OBSERVED')
            else:
                problems.add('TURN_OWNER_UNPROVEN')

            if not isinstance(trace, Mapping) or trace.get('status') != 'SYNTHETIC_TRACE_ONLY':
                problems.add('TURN_TRACE_UNAVAILABLE')
            elif ((trace.get('fight_id'), trace.get('active_owner')) != (fight, owner)
                  or (trace.get('session_id'), trace.get('account_id'),
                      trace.get('account_generation')) != (
                      expected.session_id, expected.account_id, expected.account_generation)
                  or trace.get('last_sequence') != snapshot.get('revision')):
                problems.add('TURN_TRACE_SNAPSHOT_MISMATCH')

        reasons.update(problems)
        findings.append({
            'session_id': expected.session_id,
            'account_id': expected.account_id,
            'account_generation': expected.account_generation,
            'local_actor_id': expected.local_actor_id,
            'status': 'INCOMPLETE' if problems else 'OBSERVATIONAL_ONLY',
            'reasons': sorted(problems),
            # These fields are *diagnostic* and never upgrade actionability.
            # Cross-observer turn agreement is a separate, narrower property.
            'missing_decision_fields': missing_decision_fields,
        })

    if len(fights) > 1:
        reasons.add('FIGHT_ID_CONFLICT')
    if len(owners) > 1:
        reasons.add('TURN_OWNER_CONFLICT')
    reasons.update(_NONBLOCKING)
    return FightEvidenceReport(
        status='BLOCKED_INCONSISTENT' if reasons - _NONBLOCKING else 'ALIGNED_SIMULATED_ONLY',
        observed_fight_id=next(iter(fights)) if len(fights) == 1 else None,
        observed_turn_owner=next(iter(owners)) if len(owners) == 1 else None,
        reasons=tuple(sorted(reasons)),
        account_findings=tuple(findings),
        same_database_snapshot=same_database_snapshot,
    )
