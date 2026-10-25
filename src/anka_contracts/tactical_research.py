"""P14 bounded immutable *offline* tactical research contracts.

Not action commands. Neither this module nor its serialization can authorize input.
"""
from __future__ import annotations
from dataclasses import dataclass
from anka_contracts.decision import CastProbe


@dataclass(frozen=True, slots=True)
class TacticalResearchRequest:
    scope: CastProbe
    geometry_map_id: int
    movement_cells: tuple[int, ...]
    target_cells: tuple[int, ...]
    spell_sequence: tuple[tuple[int,int], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.scope, CastProbe):
            raise TypeError('TACTICAL_SCOPE_REQUIRED')
        if type(self.geometry_map_id) is not int or self.geometry_map_id <= 0:
            raise ValueError('TACTICAL_MAP_INVALID')
        for cells, name in ((self.movement_cells,'MOVEMENT'),(self.target_cells,'TARGET')):
            if (not isinstance(cells,tuple) or not 1 <= len(cells) <= 12
                or any(type(x) is not int or not 0 <= x < 560 for x in cells)
                or len(set(cells)) != len(cells)):
                raise ValueError('TACTICAL_'+name+'_CELLS_INVALID')
        if self.scope.target_cell not in self.target_cells:
            raise ValueError('TACTICAL_PRIMARY_TARGET_REQUIRED')
        seq=self.spell_sequence
        if (not isinstance(seq,tuple) or len(seq)>4 or
            any(not isinstance(x,tuple) or len(x)!=2 or
                type(x[0]) is not int or x[0]<=0 or
                type(x[1]) is not int or not 1 <= x[1] <= 10 for x in seq)):
            raise ValueError('TACTICAL_SEQUENCE_INVALID')
        if seq and seq[0] != (self.scope.spell_id,self.scope.grade):
            raise ValueError('TACTICAL_SEQUENCE_MUST_START_WITH_PROBE_SPELL')


@dataclass(frozen=True, slots=True)
class TacticalCandidate:
    movement_cell: int
    target_cell: int
    movement_path: tuple[int, ...]
    mp_cost: int | None
    ap_cost: int | None
    remaining_mp: int | None
    remaining_ap: int | None
    kernel_legality: str
    missing_inputs: tuple[str, ...]
    reasons: tuple[str, ...]
    sequence_ap_cost: int | None
    sequence_budget: str

    def to_dict(self) -> dict:
        return {'movement_cell':self.movement_cell,'target_cell':self.target_cell,
                'movement_path':list(self.movement_path),'mp_cost':self.mp_cost,'ap_cost':self.ap_cost,
                'remaining_mp':self.remaining_mp,'remaining_ap':self.remaining_ap,
                'kernel_legality':self.kernel_legality,'missing_inputs':list(self.missing_inputs),
                'reasons':list(self.reasons),'sequence_ap_cost':self.sequence_ap_cost,
                'sequence_budget':self.sequence_budget}


@dataclass(frozen=True, slots=True)
class TacticalResearchReport:
    status: str
    reasons: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    candidates: tuple[TacticalCandidate, ...]
    evaluated_count: int
    # Frozen + serialization-level restriction: no execution DTO can be emitted.
    preview_only: bool = True
    actionable: bool = False
    authoritative: bool = False

    def __post_init__(self):
        if self.preview_only is not True or self.actionable is not False or self.authoritative is not False:
            raise ValueError('P14_RESEARCH_AUTHORITY_FORGERY')

    def to_dict(self) -> dict:
        return {'status':self.status,'reasons':list(self.reasons),
                'missing_inputs':list(self.missing_inputs),
                'candidates':[c.to_dict() for c in self.candidates],
                'evaluated_count':self.evaluated_count,'preview_only':True,
                'actionable':False,'authoritative':False,'physical_input_permitted':False}
