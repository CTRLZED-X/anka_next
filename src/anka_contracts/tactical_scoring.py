"""P15 immutable contracts for *synthetic* tactical priorities, never actions.

A fixture priority is not a predicted game effect or a real-world observation.
Scores exist only to compare controlled research scenarios. Zero actuation authority.
"""
from __future__ import annotations
from dataclasses import dataclass
from anka_contracts.tactical_research import TacticalResearchRequest, TacticalCandidate

POLICIES = ('CRA_DAMAGE_RESEARCH', 'ENU_CONTROL_RESEARCH', 'BALANCED_RESEARCH')


@dataclass(frozen=True, slots=True)
class SyntheticTargetPriority:
    cell_id: int
    damage_priority: int
    mp_control_priority: int

    def __post_init__(self):
        if type(self.cell_id) is not int or not 0 <= self.cell_id < 560:
            raise ValueError('P15_TARGET_CELL_INVALID')
        if any(type(x) is not int or not 0 <= x <= 5 for x in
               (self.damage_priority, self.mp_control_priority)):
            raise ValueError('P15_SYNTHETIC_TARGET_PRIORITY_INVALID')


@dataclass(frozen=True, slots=True)
class SyntheticPositionRisk:
    cell_id: int
    exposure: int

    def __post_init__(self):
        if type(self.cell_id) is not int or not 0 <= self.cell_id < 560:
            raise ValueError('P15_POSITION_CELL_INVALID')
        if type(self.exposure) is not int or not 0 <= self.exposure <= 5:
            raise ValueError('P15_SYNTHETIC_EXPOSURE_INVALID')


@dataclass(frozen=True, slots=True)
class TacticalScoringRequest:
    research: TacticalResearchRequest
    policy: str
    targets: tuple[SyntheticTargetPriority, ...]
    positions: tuple[SyntheticPositionRisk, ...]

    def __post_init__(self):
        if not isinstance(self.research, TacticalResearchRequest):
            raise TypeError('P15_RESEARCH_REQUEST_REQUIRED')
        if type(self.policy) is not str or self.policy not in POLICIES:
            raise ValueError('P15_POLICY_UNSUPPORTED')
        for values, expected, kind, cls in (
            (self.targets, self.research.target_cells, 'TARGETS', SyntheticTargetPriority),
            (self.positions, self.research.movement_cells, 'POSITIONS', SyntheticPositionRisk),
        ):
            if (not isinstance(values, tuple)
                or any(not isinstance(v, cls) for v in values)
                or len(values) != len(expected)
                or {v.cell_id for v in values} != set(expected)):
                raise ValueError('P15_INCOMPLETE_OR_DUPLICATE_'+kind)


@dataclass(frozen=True, slots=True)
class RankedResearchCandidate:
    candidate: TacticalCandidate
    assessment: str
    score: int | None
    contributions: tuple[tuple[str, int], ...]
    reasons: tuple[str, ...]

    def to_dict(self):
        return {'candidate': self.candidate.to_dict(), 'assessment': self.assessment,
                'score': self.score,
                'contributions': {k: v for k,v in self.contributions},
                'reasons': list(self.reasons), 'actionable': False,
                'physical_input_permitted': False}


@dataclass(frozen=True, slots=True)
class TacticalScoringReport:
    status: str
    reasons: tuple[str, ...]
    policy: str
    ranked: tuple[RankedResearchCandidate, ...]
    evaluated_count: int
    preview_only: bool = True
    authoritative: bool = False
    actionable: bool = False

    def __post_init__(self):
        if self.preview_only is not True or self.authoritative is not False or self.actionable is not False:
            raise ValueError('P15_RESEARCH_AUTHORITY_FORGERY')

    def to_dict(self):
        return {'status':self.status, 'reasons':list(self.reasons),
                'policy':self.policy, 'fixture_priorities_only': True,
                'ranked':[r.to_dict() for r in self.ranked],
                'evaluated_count':self.evaluated_count,
                'authoritative': False, 'actionable':False, 'preview_only':True,
                'physical_input_permitted':False,
                'selected_action':None,
                'damage_or_mp_removal_prediction':None}
