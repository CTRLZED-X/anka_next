"""P46 cautious single-flow combat chronology: NOT causation, NOT victory.

Checks only that archived jsq and jwp observations have compatible provenance,
strictly increasing source cursors and no messages after a terminal boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from anka_contracts.historical_combat import HistoricalCombatObservation


@dataclass(frozen=True, slots=True)
class HistoricalCombatAudit:
    status: str
    first_issue: str | None
    observation_count: int
    cast_records: int
    displacement_records: int
    result_boundaries: int
    unsupported_causation: tuple[str, ...] = (
        'SPELL_SERVER_ACCEPTANCE_UNVERIFIED',
        'CAST_TO_DAMAGE_OR_HEAL_UNPROVEN',
        'DISPLACEMENT_CAST_CAUSATION_UNPROVEN',
        'FIGHT_WIN_LOSS_UNVERIFIED',
    )
    authoritative: bool = field(default=False, init=False)
    live_ready: bool = field(default=False, init=False)
    physical_input_sent: bool = field(default=False, init=False)


def audit_historical_combat(observations: tuple[HistoricalCombatObservation, ...]) -> HistoricalCombatAudit:
    if not observations:
        return HistoricalCombatAudit('INSUFFICIENT_EVIDENCE', 'P46_EMPTY_SEQUENCE', 0, 0, 0, 0)
    first = observations[0]
    if not isinstance(first, HistoricalCombatObservation):
        return HistoricalCombatAudit('SCOPE_CONFLICT', 'P46_NOT_AN_OBSERVATION', 0, 0, 0, 0)
    scope = (first.fight_id, first.evidence.flow_digest, first.evidence.transport_generation,
             first.evidence.protocol_build, first.evidence.adapter_id)
    cursor = (-1, -1)
    counts = [0, 0, 0]
    terminal_seen = False
    for i, obs in enumerate(observations):
        if not isinstance(obs, HistoricalCombatObservation):
            return HistoricalCombatAudit('SCOPE_CONFLICT', 'P46_NOT_AN_OBSERVATION', i, *counts)
        e = obs.evidence
        if (obs.fight_id, e.flow_digest, e.transport_generation, e.protocol_build, e.adapter_id) != scope:
            return HistoricalCombatAudit('SCOPE_CONFLICT', 'P46_MIXED_FIGHT_FLOW_OR_BUILD', i, *counts)
        pos = (e.packet_number, e.message_index)
        if pos <= cursor:
            return HistoricalCombatAudit('ORDER_CONFLICT', 'P46_DUPLICATE_OR_REORDERED_SOURCE', i, *counts)
        cursor = pos
        if terminal_seen:
            return HistoricalCombatAudit('ORDER_CONFLICT', 'P46_OBSERVATION_AFTER_RESULT', i, *counts)
        if obs.kind == 'CAST_WIRE_OBSERVED':
            counts[0] += 1
        elif obs.kind == 'DISPLACEMENT_OBSERVED':
            counts[1] += 1
        elif obs.kind == 'FIGHT_RESULT_BOUNDARY_OBSERVED':
            counts[2] += 1
            terminal_seen = True
    return HistoricalCombatAudit('RESEARCH_SEQUENCE_COHERENT_NOT_CERTIFIED', None, len(observations), *counts)
