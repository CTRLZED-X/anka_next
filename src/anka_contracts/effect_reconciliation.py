"""P35: immutable evidence-window contracts, NEVER action settlement.

A before/after difference is correlation, not server-confirmed causation.
No API herein can authorize physical input or Canonical admission.
"""
from __future__ import annotations
from dataclasses import dataclass, field

_METRICS = frozenset({'AP', 'MP', 'RANGE', 'HP', 'CELL', 'COOLDOWN'})
_STATUSES = frozenset({'GAPS_FOUND_RESEARCH_ONLY', 'INCOMPLETE_RESEARCH_ONLY',
                        'BLOCKED_RESEARCH_ONLY'})


@dataclass(frozen=True, slots=True)
class ObservationWindow:
    """Explicit zero-based indices into an already provenance-verified trace."""
    before_index: int
    action_index: int
    after_index: int
    metric: str

    def __post_init__(self):
        if (any(type(n) is not int or n < 0 or n > 4095 for n in
                (self.before_index, self.action_index, self.after_index))
            or not self.before_index < self.action_index < self.after_index
            or self.metric not in _METRICS):
            raise ValueError('P35_WINDOW_CONTRACT_INVALID')


@dataclass(frozen=True, slots=True)
class ObservationComparison:
    """Private research result: differences deliberately omitted in exports."""
    window_index: int
    metric: str
    relation: str
    caveats: tuple[str, ...]
    numeric_delta: int | None = None

    def __post_init__(self):
        if (type(self.window_index) is not int or self.window_index < 0 or
            self.metric not in _METRICS or
            self.relation not in {'CHANGED', 'UNCHANGED', 'AMBIGUOUS'} or
            (self.numeric_delta is not None and type(self.numeric_delta) is not int) or
            type(self.caveats) is not tuple or not self.caveats or
            any(type(s) is not str or not s.isascii() or len(s)>120 for s in self.caveats)):
            raise ValueError('P35_COMPARISON_CONTRACT_INVALID')

    def to_dict(self) -> dict:
        # Never expose character stats, packet values or numeric deltas in diagnostics.
        return dict(window_index=self.window_index,metric=self.metric,
                    relation=self.relation,caveats=list(self.caveats),
                    server_confirmed=False,actionable=False)


@dataclass(frozen=True, slots=True)
class EffectReconciliationReport:
    status: str
    reason_codes: tuple[str, ...]
    observations: int
    windows_checked: int
    comparisons: tuple[ObservationComparison, ...]
    first_blocked_window: int | None = None
    authority: str = field(default='RESEARCH_ONLY_NOT_CANONICAL', init=False)
    committed_events: int = field(default=0, init=False)
    physical_input_sent: bool = field(default=False, init=False)
    actionable: bool = field(default=False, init=False)
    live_state_mutated: bool = field(default=False, init=False)

    def __post_init__(self):
        if (self.status not in _STATUSES or
            type(self.reason_codes) is not tuple or
            any(type(s) is not str or not s.isascii() or len(s)>120 for s in self.reason_codes) or
            any(type(v) is not int or v < 0 for v in (self.observations,self.windows_checked)) or
            self.windows_checked>128 or self.observations>4096 or
            type(self.comparisons) is not tuple or
            any(not isinstance(c,ObservationComparison) for c in self.comparisons) or
            len(self.comparisons)>self.windows_checked or
            (self.first_blocked_window is not None and
             (type(self.first_blocked_window) is not int or
              not 0 <= self.first_blocked_window < self.windows_checked)) or
            (self.status=='BLOCKED_RESEARCH_ONLY') != (self.first_blocked_window is not None or
              (self.windows_checked==0 and bool(self.reason_codes) and self.reason_codes[0].startswith('P34_')))):
            raise ValueError('P35_REPORT_CONTRACT_INVALID')

    def to_dict(self) -> dict:
        return dict(status=self.status,reason_codes=list(self.reason_codes),
                    observations=self.observations,windows_checked=self.windows_checked,
                    comparisons=[c.to_dict() for c in self.comparisons],
                    first_blocked_window=self.first_blocked_window,
                    authority=self.authority,committed_events=0,physical_input_sent=False,
                    actionable=False,live_state_mutated=False,current_build_certified=False,
                    game_server_outcome_certified=False,cross_account_order_certified=False)
