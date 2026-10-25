"""P16 bounded, immutable, non-executable hypothetical sequence contracts."""
from __future__ import annotations
from dataclasses import dataclass
from anka_contracts.tactical_research import TacticalResearchRequest


@dataclass(frozen=True, slots=True)
class ResearchCastStep:
    spell_id: int
    grade: int
    target_cell: int

    def __post_init__(self):
        if type(self.spell_id) is not int or self.spell_id <= 0:
            raise ValueError('P16_SPELL_ID_INVALID')
        if type(self.grade) is not int or not 1 <= self.grade <= 10:
            raise ValueError('P16_GRADE_INVALID')
        if type(self.target_cell) is not int or not 0 <= self.target_cell < 560:
            raise ValueError('P16_TARGET_INVALID')


@dataclass(frozen=True, slots=True)
class SequenceResearchRequest:
    tactical: TacticalResearchRequest
    movement_cell: int
    casts: tuple[ResearchCastStep, ...]

    def __post_init__(self):
        if not isinstance(self.tactical,TacticalResearchRequest):
            raise TypeError('P16_TACTICAL_REQUEST_REQUIRED')
        if type(self.movement_cell) is not int or self.movement_cell not in self.tactical.movement_cells:
            raise ValueError('P16_MOVEMENT_NOT_REQUESTED')
        if not isinstance(self.casts,tuple) or not 1 <= len(self.casts) <= 4 or any(
            not isinstance(item,ResearchCastStep) for item in self.casts
        ):
            raise ValueError('P16_CAST_SEQUENCE_INVALID')
        first=self.casts[0];scope=self.tactical.scope
        if (first.spell_id,first.grade,first.target_cell)!=(scope.spell_id,scope.grade,scope.target_cell):
            raise ValueError('P16_FIRST_STEP_MUST_MATCH_PROBE')
        if self.tactical.spell_sequence and tuple((s.spell_id,s.grade) for s in self.casts)!=self.tactical.spell_sequence:
            raise ValueError('P16_TACTICAL_SEQUENCE_MISMATCH')


@dataclass(frozen=True, slots=True)
class SequenceStepResult:
    ordinal: int
    spell_id: int
    target_cell: int
    status: str
    before_ap: int | None
    after_ap: int | None
    after_mp: int | None
    projected_cast_count: int | None
    projected_cooldown: int | None
    projection_complete: bool
    certainty: str
    missing_inputs: tuple[str,...] = ()
    live_requirements: tuple[str,...] = ()
    reasons: tuple[str,...] = ()

    def to_dict(self):
        return dict(ordinal=self.ordinal,spell_id=self.spell_id,target_cell=self.target_cell,status=self.status,
                    before_ap=self.before_ap,after_ap=self.after_ap,after_mp=self.after_mp,
                    projected_cast_count=self.projected_cast_count,projected_cooldown=self.projected_cooldown,
                    projection_complete=self.projection_complete,certainty=self.certainty,
                    missing_inputs=list(self.missing_inputs),live_requirements=list(self.live_requirements),
                    reasons=list(self.reasons))


@dataclass(frozen=True, slots=True)
class SequenceResearchReport:
    status: str
    reasons: tuple[str,...]
    steps: tuple[SequenceStepResult,...]
    attempted_count: int
    requested_count: int
    physical_input_permitted: bool = False
    actionable: bool = False
    authoritative: bool = False
    preview_only: bool = True

    def __post_init__(self):
        if self.physical_input_permitted is not False or self.actionable is not False or self.authoritative is not False or self.preview_only is not True:
            raise ValueError('P16_RESEARCH_AUTHORITY_FORGERY')
        if type(self.attempted_count) is not int or type(self.requested_count) is not int or not 0 <= self.attempted_count <= self.requested_count <= 4:
            raise ValueError('P16_COUNTS_INVALID')
        if len(self.steps)!=self.attempted_count:
            raise ValueError('P16_STEPS_COUNT_MISMATCH')

    def to_dict(self):
        return {'status':self.status,'reasons':list(self.reasons),
                'steps':[step.to_dict() for step in self.steps],
                'attempted_count':self.attempted_count,'requested_count':self.requested_count,
                'physical_input_permitted':False,'actionable':False,'authoritative':False,'preview_only':True,
                'selected_action':None}
