"""Cross-family P45 + P46 research chronology for exactly one captured flow.

Never deduce server acceptance, global multi-account ordering, damage causation
or victory from a cast record. Out-of-turn casts are a *research discrepancy*,
not a proof of packet invalidity (reactive game effects may exist).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from anka_contracts.historical_lifecycle import LegacyFightObservation
from anka_contracts.historical_combat import HistoricalCombatObservation


@dataclass(frozen=True, slots=True)
class HistoricalCombinedAudit:
    status: str
    first_issue: str | None
    observations_checked: int
    casts_observed: int
    casts_without_proven_owner: int
    caster_owner_discrepancies: int
    result_boundaries: int
    limitations: tuple[str, ...] = (
        'SINGLE_FLOW_ONLY_NO_GLOBAL_ACCOUNT_ORDER',
        'SPELL_ACCEPTANCE_AND_EFFECT_CAUSALITY_UNVERIFIED',
        'FIGHT_VICTORY_AND_WORLD_REENTRY_UNVERIFIED',
    )
    canonical_commits: int = field(default=0, init=False)
    physical_input_sent: bool = field(default=False, init=False)
    live_ready: bool = field(default=False, init=False)


def audit_historical_combined(observations: tuple[LegacyFightObservation | HistoricalCombatObservation, ...]) -> HistoricalCombinedAudit:
    def report(status, issue, checked, casts, unknown, mismatches, ends):
        return HistoricalCombinedAudit(status, issue, checked, casts, unknown, mismatches, ends)

    if not observations:
        return report('INSUFFICIENT_EVIDENCE', 'P46_COMBINED_EMPTY', 0, 0, 0, 0, 0)
    first = observations[0]
    if not isinstance(first, (LegacyFightObservation, HistoricalCombatObservation)):
        return report('SCOPE_CONFLICT', 'P46_COMBINED_BAD_OBSERVATION', 0, 0, 0, 0, 0)
    e = first.evidence
    scope = (first.fight_id, e.protocol_build, e.flow_digest, e.transport_generation)
    cursor = (-1, -1)
    casts = unknown = mismatches = ends = 0
    owner = None
    terminal = False
    for i, item in enumerate(observations):
        if not isinstance(item, (LegacyFightObservation, HistoricalCombatObservation)):
            return report('SCOPE_CONFLICT', 'P46_COMBINED_BAD_OBSERVATION', i, casts, unknown, mismatches, ends)
        ev = item.evidence
        if (item.fight_id, ev.protocol_build, ev.flow_digest, ev.transport_generation) != scope:
            return report('SCOPE_CONFLICT', 'P46_COMBINED_MIXED_SCOPE', i, casts, unknown, mismatches, ends)
        pos = (ev.packet_number, ev.message_index)
        if pos <= cursor:
            return report('ORDER_CONFLICT', 'P46_COMBINED_DUPLICATE_OR_REORDERED_SOURCE', i, casts, unknown, mismatches, ends)
        if terminal:
            return report('ORDER_CONFLICT', 'P46_COMBINED_EVENT_AFTER_RESULT', i, casts, unknown, mismatches, ends)
        cursor = pos
        if isinstance(item, LegacyFightObservation):
            if item.kind == 'TURN_OWNER_OBSERVED':
                if owner is not None and owner != item.actor_id:
                    return report('ORDER_CONFLICT', 'P46_COMBINED_OWNER_SWITCH_WITHOUT_END', i, casts, unknown, mismatches, ends)
                owner = item.actor_id
            elif item.kind == 'TURN_END_OBSERVED':
                if owner is None:
                    return report('INSUFFICIENT_EVIDENCE', 'P46_COMBINED_TURN_END_WITHOUT_OWNER', i, casts, unknown, mismatches, ends)
                if owner != item.actor_id:
                    return report('ORDER_CONFLICT', 'P46_COMBINED_TURN_END_ACTOR_MISMATCH', i, casts, unknown, mismatches, ends)
                owner = None
        elif item.kind == 'CAST_WIRE_OBSERVED':
            casts += 1
            if owner is None:
                unknown += 1
            elif owner != item.actor_id:
                mismatches += 1
        elif item.kind == 'FIGHT_RESULT_BOUNDARY_OBSERVED':
            ends += 1
            terminal = True
    if mismatches:
        return report('RESEARCH_DISCREPANCY_NOT_CERTIFIED', 'P46_CASTER_NOT_OBSERVED_TURN_OWNER', len(observations), casts, unknown, mismatches, ends)
    if unknown:
        return report('INSUFFICIENT_EVIDENCE', 'P46_CAST_WITHOUT_OWNER_EVIDENCE', len(observations), casts, unknown, mismatches, ends)
    return report('RESEARCH_CHRONOLOGY_NOT_CERTIFIED', None, len(observations), casts, unknown, mismatches, ends)
