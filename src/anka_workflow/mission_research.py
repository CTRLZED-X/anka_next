"""Independent read-only mission projection from coordination and outcome DTOs.

Fight-ended is not victory. No downstream routing, input or automatic retry.
"""
from __future__ import annotations
from anka_contracts.coordination_flow import PartyTimelineReport
from anka_contracts.workflow_flow import SyntheticFightOutcome, MissionResearchReport


def evaluate_mission(reports: tuple[PartyTimelineReport, ...], outcomes: tuple[SyntheticFightOutcome, ...], *, target_wins: int = 1, max_losses: int = 0) -> MissionResearchReport:
    if type(reports) is not tuple or len(reports) > 100 or any(not isinstance(r, PartyTimelineReport) for r in reports):
        raise ValueError('P17_MISSION_REPORTS_INVALID')
    if type(outcomes) is not tuple or len(outcomes) > 100 or any(not isinstance(o, SyntheticFightOutcome) for o in outcomes):
        raise ValueError('P17_MISSION_OUTCOMES_INVALID')
    if type(target_wins) is not int or not 1 <= target_wins <= 100 or type(max_losses) is not int or not 0 <= max_losses <= 100:
        raise ValueError('P17_MISSION_POLICY_INVALID')
    ids = [r.fight_id for r in reports if r.fight_id is not None]
    if len(ids) != len(set(ids)) or len({o.fight_id for o in outcomes}) != len(outcomes) or len({o.observation_id for o in outcomes}) != len(outcomes):
        raise ValueError('P17_DUPLICATE_FIGHT_OR_OUTCOME')
    by_id = {r.fight_id:r for r in reports if r.fight_id is not None}
    if any(o.fight_id not in by_id for o in outcomes):
        raise ValueError('P17_ORPHAN_FIGHT_OUTCOME')
    reasons = []
    wins = losses = unresolved = 0
    for report in reports:
        if report.status == 'QUARANTINED':
            reasons.append('P17_COORDINATION_FAILED')
        if report.status != 'FINISHED':
            unresolved += 1
        elif not any(o.fight_id == report.fight_id for o in outcomes):
            unresolved += 1
            reasons.append('P17_FIGHT_END_NOT_VICTORY_PROOF')
    for outcome in outcomes:
        if by_id[outcome.fight_id].status != 'FINISHED':
            reasons.append('P17_OUTCOME_BEFORE_FIGHT_END')
        elif outcome.outcome == 'VICTORY':
            wins += 1
        else:
            losses += 1
    if losses > max_losses:
        reasons.append('P17_LOSS_BUDGET_EXCEEDED')
    if reasons:
        status = 'BLOCKED_SYNTHETIC'
    elif wins >= target_wins:
        status = 'SYNTHETIC_TARGET_REACHED'
    elif unresolved:
        status = 'WAITING_FOR_SYNTHETIC_EVIDENCE'
    else:
        status = 'SYNTHETIC_CONTINUE_CANDIDATE'
    return MissionResearchReport(status, wins, losses, unresolved, tuple(sorted(set(reasons))))
