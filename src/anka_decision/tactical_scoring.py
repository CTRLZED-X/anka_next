"""P15 deterministic, explainable *synthetic* candidate research scoring.

Only the preserved Kernel, via P14, can assess spell/path constraints.
Ranking never certifies a spell, a two-cast sequence, or physical execution.
"""
from __future__ import annotations
from anka_contracts.tactical_scoring import (
    TacticalScoringRequest, TacticalScoringReport, RankedResearchCandidate)
from anka_decision.tactical_research import inspect_tactical_research

_WEIGHTS = {
    'CRA_DAMAGE_RESEARCH': (4, 1),
    'ENU_CONTROL_RESEARCH': (1, 4),
    'BALANCED_RESEARCH': (2, 2),
}


def inspect_tactical_scoring(snapshot: dict, request: TacticalScoringRequest,
                             *, map_definition, fight_context, kernel) -> TacticalScoringReport:
    """Rank a bounded P14 preview, not an executable or probabilistic game plan.

    The priorities/exposure values are synthetic *fixture opinions*, not observed
    target health, predictive damage, MP removal, or real-world danger measures.
    """
    if not isinstance(request, TacticalScoringRequest):
        raise TypeError('P15_SCORING_REQUEST_REQUIRED')
    base = inspect_tactical_research(snapshot, request.research,
                                     map_definition=map_definition,
                                     fight_context=fight_context, kernel=kernel)
    if base.status != 'RESEARCH_ONLY':
        return TacticalScoringReport(base.status,
            tuple(dict.fromkeys(base.reasons + base.missing_inputs)),request.policy,(),0)
    targets = {t.cell_id:t for t in request.targets}
    positions = {p.cell_id:p for p in request.positions}
    d_weight, c_weight = _WEIGHTS[request.policy]
    multi_cast = len(request.research.spell_sequence) > 1
    scored = []
    for c in base.candidates:
        reasons = []
        contributions = ()
        score = None
        assessment = 'UNSCORED'
        if c.kernel_legality == 'ILLEGAL':
            assessment = 'REJECTED_KERNEL'
            reasons.append('P15_KERNEL_REJECTED_CAST')
        elif c.kernel_legality != 'LEGAL_STATIC_ONLY':
            assessment = 'UNSCORED_UNKNOWN'
            reasons.append('P15_CAST_LEGALITY_NOT_PROVEN')
        elif c.sequence_budget == 'OVER_AP_BUDGET':
            assessment = 'REJECTED_AP_BUDGET'
            reasons.append('P15_SEQUENCE_EXCEEDS_AP')
        elif c.sequence_budget != 'WITHIN_AP_BUDGET_COST_ONLY':
            assessment = 'UNSCORED_UNKNOWN'
            reasons.append('P15_SEQUENCE_BUDGET_UNKNOWN')
        elif multi_cast:
            # P14 only checks AP sums, not repeat limits, cooldowns, dynamic
            # effects, interaction with movement, or target validity per spell.
            assessment = 'UNSCORED_MULTI_CAST_UNCERTIFIED'
            reasons.append('P15_MULTICAST_SEQUENCE_NOT_SIMULATED')
        elif c.mp_cost is None or c.remaining_ap is None:
            assessment = 'UNSCORED_UNKNOWN'
            reasons.append('P15_RESOURCE_PROJECTION_INCOMPLETE')
        elif not c.movement_path or c.movement_cell != c.movement_path[-1]:
            assessment = 'UNSCORED_UNKNOWN'
            reasons.append('P15_PATH_NOT_VERIFIED_BY_KERNEL')
        else:
            target = targets[c.target_cell]
            position = positions[c.movement_cell]
            # Integer-only, deterministic illustrative arithmetic. No guessed
            # damage, no fake MP reduction, no hidden/random AI heuristics.
            contributions = (
                ('synthetic_damage_priority', d_weight * target.damage_priority),
                ('synthetic_control_priority', c_weight * target.mp_control_priority),
                ('synthetic_exposure_cost', -2 * position.exposure),
                ('kernel_mp_spend_cost', -c.mp_cost),
            )
            score = sum(v for _,v in contributions)
            assessment = 'SCORED_STATIC_PREVIEW'
            reasons.extend(('P15_SYNTHETIC_PRIORITIES_NOT_GAME_EFFECTS',
                            'P15_NO_SERVER_OUTCOME_OR_EXECUTION_AUTHORITY'))
            if c.movement_cell != c.movement_path[0]:
                reasons.append('P15_MOVEMENT_EFFECTS_UNVERIFIED')
        scored.append(RankedResearchCandidate(c, assessment, score,
                                              contributions, tuple(reasons)))
    # Intuitive ordering: rank only scored static previews by descending score;
    # never let UNKNOWN, an AP overrun or kernel-rejected candidates win.
    ordering = {'SCORED_STATIC_PREVIEW':0, 'UNSCORED_MULTI_CAST_UNCERTIFIED':1,
                'UNSCORED_UNKNOWN':2, 'REJECTED_AP_BUDGET':3,
                'REJECTED_KERNEL':4, 'UNSCORED':5}
    scored.sort(key=lambda r: (
        ordering.get(r.assessment, 6),
        -r.score if r.score is not None else 0,
        r.candidate.mp_cost if r.candidate.mp_cost is not None else 1_000_000,
        r.candidate.movement_cell,r.candidate.target_cell,
    ))
    return TacticalScoringReport('RESEARCH_ONLY',
        ('P15_SCENARIO_HEURISTICS_ARE_SYNTHETIC', 'P15_SCORES_ARE_NOT_DAMAGE_PREDICTIONS',
         'P15_NOT_VALIDATED_FOR_CURRENT_GAME', 'P15_NO_PHYSICAL_GAME_INPUT'),
        request.policy, tuple(scored), len(scored))
