"""Immutable *historical research* combat observations; never gameplay authority.

P46 only recovers fields seen in archived R5.198 handlers. A server-originated
cast envelope proves neither success nor damage; a result boundary proves
neither victory nor defeat. These contracts cannot grant production admission.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from anka_contracts.canonical import EvidenceRef

_KINDS = frozenset({'CAST_WIRE_OBSERVED', 'DISPLACEMENT_OBSERVED', 'FIGHT_RESULT_BOUNDARY_OBSERVED'})


def _actor(value: int | None) -> bool:
    return type(value) is int and 0 != value and -(2**63) < value < 2**63


def _cell(value: int | None) -> bool:
    return type(value) is int and 0 <= value < 560


@dataclass(frozen=True, slots=True)
class HistoricalCombatObservation:
    kind: str
    evidence: EvidenceRef
    fight_id: int
    wire_action_type: int | None = None
    actor_id: int | None = None
    spell_id: int | None = None
    spell_level_record_id: int | None = None
    target_cell_id: int | None = None
    from_cell_id: int | None = None
    to_cell_id: int | None = None
    displacement_kind: str | None = None
    outcome: str = field(default='UNKNOWN', init=False)
    authority: str = field(default='HISTORICAL_RESEARCH_ONLY', init=False)
    server_effect_confirmed: bool = field(default=False, init=False)
    victory_confirmed: bool = field(default=False, init=False)

    def __post_init__(self):
        if self.kind not in _KINDS or not isinstance(self.evidence, EvidenceRef):
            raise ValueError('P46_COMBAT_KIND_OR_EVIDENCE_INVALID')
        if type(self.fight_id) is not int or not 0 < self.fight_id < 2**63:
            raise ValueError('P46_COMBAT_FIGHT_INVALID')
        if self.kind == 'CAST_WIRE_OBSERVED':
            if (self.wire_action_type != 300 or not _actor(self.actor_id) or
                type(self.spell_id) is not int or self.spell_id <= 0 or
                type(self.spell_level_record_id) is not int or self.spell_level_record_id <= 0 or
                not _cell(self.target_cell_id) or
                any(x is not None for x in (self.from_cell_id, self.to_cell_id, self.displacement_kind))):
                raise ValueError('P46_CAST_SHAPE_INVALID')
        elif self.kind == 'DISPLACEMENT_OBSERVED':
            if (self.wire_action_type not in (4, 5) or not _actor(self.actor_id) or
                not _cell(self.to_cell_id) or
                any(x is not None for x in (self.spell_id, self.spell_level_record_id, self.target_cell_id)) or
                self.displacement_kind != ('PUSH' if self.wire_action_type == 5 else 'TELEPORT') or
                (not _cell(self.from_cell_id) if self.wire_action_type == 5 else self.from_cell_id is not None)):
                raise ValueError('P46_DISPLACEMENT_SHAPE_INVALID')
        else:
            if any(x is not None for x in (self.wire_action_type, self.actor_id, self.spell_id,
                  self.spell_level_record_id, self.target_cell_id, self.from_cell_id,
                  self.to_cell_id, self.displacement_kind)):
                raise ValueError('P46_TERMINAL_SHAPE_INVALID')


@dataclass(frozen=True, slots=True)
class HistoricalCombatResult:
    status: str
    adapter_id: str
    protocol_build: str
    wire_name: str
    observations: tuple[HistoricalCombatObservation, ...] = ()
    failure_code: str | None = None
    canonical_commits: int = field(default=0, init=False)
    physical_input_sent: bool = field(default=False, init=False)
    current_client_certified: bool = field(default=False, init=False)

    def __post_init__(self):
        if self.status not in ('OBSERVATIONS_ONLY', 'NO_MAPPING', 'UNSUPPORTED_ACTION',
                               'QUARANTINED', 'BUILD_MISMATCH', 'SCOPE_UNVERIFIED'):
            raise ValueError('P46_COMBAT_STATUS_INVALID')
        if (self.status == 'OBSERVATIONS_ONLY') != bool(self.observations) or len(self.observations) > 1:
            raise ValueError('P46_COMBAT_RESULT_SHAPE_INVALID')
        if any((o.evidence.adapter_id, o.evidence.protocol_build, o.evidence.wire_name) !=
               (self.adapter_id, self.protocol_build, self.wire_name) for o in self.observations):
            raise ValueError('P46_COMBAT_RESULT_PROVENANCE_INVALID')
        if self.status in ('QUARANTINED', 'UNSUPPORTED_ACTION') and not self.failure_code:
            raise ValueError('P46_COMBAT_FAILURE_REASON_MISSING')
