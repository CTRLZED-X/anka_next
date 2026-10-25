"""P36: scoped research-only target-resource windows; never proves spell effects.

A caster's action and a different actor's health change can correlate without
one causing the other. These types intentionally cannot carry action authority.
"""
from __future__ import annotations
from dataclasses import dataclass, field

_METRICS = frozenset({'HP', 'AP', 'MP'})
_STATUSES = frozenset({'BLOCKED_RESEARCH_ONLY', 'INCOMPLETE_RESEARCH_ONLY', 'GAPS_FOUND_RESEARCH_ONLY'})


@dataclass(frozen=True, slots=True)
class TargetEffectWindow:
    """Indices in one fully validated research trace; cell witness is optional."""
    before_index: int
    cast_index: int
    after_index: int
    target_actor_id: int
    metric: str = 'HP'
    target_cell_index: int | None = None

    def __post_init__(self):
        positions = (self.before_index, self.cast_index, self.after_index)
        if (any(type(i) is not int or not 0 <= i <= 4095 for i in positions)
            or not self.before_index < self.cast_index < self.after_index
            or type(self.target_actor_id) is not int or self.target_actor_id == 0
            or abs(self.target_actor_id) >= 2**63 or self.metric not in _METRICS
            or (self.target_cell_index is not None and
                (type(self.target_cell_index) is not int or
                 not self.before_index <= self.target_cell_index < self.cast_index))):
            raise ValueError('P36_TARGET_WINDOW_INVALID')


@dataclass(frozen=True, slots=True)
class TargetEffectComparison:
    """Delta is private research data; never exported in the GPT report."""
    window_index: int
    metric: str
    relation: str
    location_relation: str
    caveats: tuple[str, ...]
    numeric_delta: int | None = field(default=None, repr=False)

    def __post_init__(self):
        if (type(self.window_index) is not int or self.window_index < 0
            or self.metric not in _METRICS
            or self.relation not in {'CHANGED', 'UNCHANGED', 'AMBIGUOUS'}
            or self.location_relation not in {'UNKNOWN', 'MATCHED_OBSERVATION', 'MISMATCHED_OBSERVATION', 'STALE_OBSERVATION'}
            or not isinstance(self.caveats, tuple) or not self.caveats
            or any(not isinstance(x,str) or not x.isascii() or len(x)>120 for x in self.caveats)
            or (self.numeric_delta is not None and type(self.numeric_delta) is not int)):
            raise ValueError('P36_TARGET_COMPARISON_INVALID')

    def to_dict(self) -> dict:
        return {'window_index':self.window_index,'metric':self.metric,
                'relation':self.relation,'location_relation':self.location_relation,
                'caveats':list(self.caveats),'server_effect_proven':False,
                'actionable':False}


@dataclass(frozen=True, slots=True)
class TargetEffectResearchReport:
    status: str
    reason_codes: tuple[str, ...]
    observations: int
    windows_checked: int
    comparisons: tuple[TargetEffectComparison, ...]
    first_blocked_window: int | None = None
    authority: str = field(default='RESEARCH_ONLY_NOT_CANONICAL', init=False)
    actionable: bool = field(default=False, init=False)
    committed_events: int = field(default=0, init=False)
    physical_input_sent: bool = field(default=False, init=False)

    def __post_init__(self):
        if (self.status not in _STATUSES or not isinstance(self.reason_codes,tuple)
            or any(not isinstance(x,str) or len(x)>120 or not x.isascii() for x in self.reason_codes)
            or any(type(x) is not int or x<0 for x in (self.observations,self.windows_checked))
            or self.observations>4096 or self.windows_checked>128
            or not isinstance(self.comparisons,tuple)
            or any(not isinstance(x,TargetEffectComparison) for x in self.comparisons)
            or len(self.comparisons)>self.windows_checked
            or (self.status=='BLOCKED_RESEARCH_ONLY')!=(self.first_blocked_window is not None or
                (self.windows_checked==0 and bool(self.reason_codes) and self.reason_codes[0].startswith('P34_')))
            or (self.first_blocked_window is not None and not 0<=self.first_blocked_window<self.windows_checked)):
            raise ValueError('P36_TARGET_REPORT_INVALID')

    def to_dict(self) -> dict:
        return {'status':self.status,'reason_codes':list(self.reason_codes),
                'observations':self.observations,'windows_checked':self.windows_checked,
                'comparisons':[c.to_dict() for c in self.comparisons],
                'first_blocked_window':self.first_blocked_window,
                'authority':self.authority,'actionable':False,'committed_events':0,
                'physical_input_sent':False,'current_build_certified':False,
                'server_effect_proven':False,'cross_account_order_proven':False}
