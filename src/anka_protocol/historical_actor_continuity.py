"""P54 historical world-character -> fight-actor continuity research.

This audit joins the P53 `jnj` historical character witness to P45/P46 fight
observations only when exact flow/build/generation provenance agrees.  It does
not prove current-client identity, account role, breed, spell success, victory,
or any permission to act.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from anka_contracts.historical_identity import HistoricalIdentityObservation
from anka_contracts.historical_lifecycle import LegacyFightObservation
from anka_contracts.historical_combat import HistoricalCombatObservation
from anka_protocol.adapters.historical_identity import BUILD as HISTORICAL_BUILD

HistoricalFightObservation = LegacyFightObservation | HistoricalCombatObservation


@dataclass(frozen=True, slots=True)
class HistoricalActorContinuityAudit:
    status: str
    first_issue: str | None
    fight_id: int | None
    observations_checked: int
    local_actor_references: int
    local_turn_owner_records: int
    local_turn_end_records: int
    local_ready_records: int
    local_cast_records: int
    local_displacement_records: int
    foreign_actor_references: int
    result_boundaries: int
    limitations: tuple[str, ...] = (
        'HISTORICAL_BUILD_ONLY',
        'FLOW_IS_NOT_CURRENT_ACCOUNT_ATTESTATION',
        'CHARACTER_BREED_AND_ACCOUNT_ROLE_UNVERIFIED',
        'CAST_RECORD_IS_NOT_SERVER_SUCCESS_OR_EFFECT_CAUSATION',
        'FIGHT_RESULT_BOUNDARY_IS_NOT_VICTORY',
        'CURRENT_CLIENT_AND_WINDOWS_ACCEPTANCE_ABSENT',
    )
    current_client_certified: bool = field(default=False, init=False)
    account_binding_verified: bool = field(default=False, init=False)
    canonical_commits: int = field(default=0, init=False)
    physical_input_sent: bool = field(default=False, init=False)
    actionable: bool = field(default=False, init=False)
    authority: str = field(default='HISTORICAL_RESEARCH_ONLY', init=False)

    def __post_init__(self):
        if self.status not in {'RESEARCH_ACTOR_CONTINUITY_ONLY','PARTIAL_EVIDENCE','BLOCKED_EVIDENCE'}:
            raise ValueError('P54_CONTINUITY_STATUS_INVALID')
        if (self.status == 'RESEARCH_ACTOR_CONTINUITY_ONLY') != (self.first_issue is None):
            raise ValueError('P54_CONTINUITY_STATUS_REASON_MISMATCH')
        counts=(self.observations_checked,self.local_actor_references,self.local_turn_owner_records,
                self.local_turn_end_records,self.local_ready_records,self.local_cast_records,
                self.local_displacement_records,self.foreign_actor_references,self.result_boundaries)
        if any(type(x) is not int or x < 0 for x in counts):
            raise ValueError('P54_CONTINUITY_COUNTS_INVALID')
        if self.local_actor_references + self.foreign_actor_references > self.observations_checked:
            # Some events (round/result) have no actor, so <= is expected.
            raise ValueError('P54_CONTINUITY_COUNTS_INVALID')
        if self.fight_id is not None and (type(self.fight_id) is not int or not 0 < self.fight_id < 2**63):
            raise ValueError('P54_CONTINUITY_FIGHT_INVALID')


def audit_historical_actor_continuity(
    identity: HistoricalIdentityObservation,
    observations: tuple[HistoricalFightObservation, ...],
) -> HistoricalActorContinuityAudit:
    """Check one historical name/actor witness against one same-flow fight trace.

    Strong requirements are intentional: all fight observations must share the
    P53 identity witness's historical build, flow digest and transport generation,
    must belong to one fight, and must occur strictly after the identity source
    cursor.  This makes the result useful as falsification evidence while keeping
    authority at zero.
    """
    def report(status:str, issue:str|None, fight_id:int|None, checked:int,
               local:int=0, owners:int=0, ends:int=0, ready:int=0, casts:int=0,
               moves:int=0, foreign:int=0, results:int=0):
        return HistoricalActorContinuityAudit(status,issue,fight_id,checked,local,
            owners,ends,ready,casts,moves,foreign,results)

    if not isinstance(identity, HistoricalIdentityObservation):
        return report('BLOCKED_EVIDENCE','P54_IDENTITY_WITNESS_INVALID',None,0)
    ie=identity.evidence
    if (ie.protocol_build != HISTORICAL_BUILD or identity.authority != 'HISTORICAL_RESEARCH_ONLY' or
            identity.current_client_certified or identity.canonical_commits or identity.physical_input_sent):
        return report('BLOCKED_EVIDENCE','P54_IDENTITY_WITNESS_NOT_HISTORICAL_RESEARCH',None,0)
    if not isinstance(observations, tuple):
        return report('BLOCKED_EVIDENCE','P54_FIGHT_OBSERVATIONS_INVALID',None,0)
    if not observations:
        return report('PARTIAL_EVIDENCE','P54_FIGHT_OBSERVATIONS_MISSING',None,0)
    if len(observations) > 4096:
        return report('BLOCKED_EVIDENCE','P54_FIGHT_OBSERVATION_LIMIT_EXCEEDED',None,0)

    base=(ie.protocol_build,ie.flow_digest,ie.transport_generation)
    last=(ie.packet_number,ie.message_index)
    fight_id=None
    local=owners=ends=ready=casts=moves=foreign=results=0
    for idx,item in enumerate(observations):
        if not isinstance(item,(LegacyFightObservation,HistoricalCombatObservation)):
            return report('BLOCKED_EVIDENCE','P54_FIGHT_OBSERVATION_INVALID',fight_id,idx,
                          local,owners,ends,ready,casts,moves,foreign,results)
        e=item.evidence
        if (e.protocol_build,e.flow_digest,e.transport_generation) != base:
            return report('BLOCKED_EVIDENCE','P54_BUILD_FLOW_OR_GENERATION_CONFLICT',fight_id,idx,
                          local,owners,ends,ready,casts,moves,foreign,results)
        if item.fight_id <= 0:
            return report('BLOCKED_EVIDENCE','P54_FIGHT_ID_INVALID',fight_id,idx,
                          local,owners,ends,ready,casts,moves,foreign,results)
        if fight_id is None:
            fight_id=item.fight_id
        elif item.fight_id != fight_id:
            return report('BLOCKED_EVIDENCE','P54_MIXED_FIGHT_IDENTITIES',fight_id,idx,
                          local,owners,ends,ready,casts,moves,foreign,results)
        cursor=(e.packet_number,e.message_index)
        if cursor <= last:
            return report('BLOCKED_EVIDENCE','P54_IDENTITY_TO_FIGHT_SOURCE_NOT_STRICTLY_ORDERED',fight_id,idx,
                          local,owners,ends,ready,casts,moves,foreign,results)
        last=cursor

        actor=item.actor_id
        if actor is not None:
            if actor == identity.actor_id:
                local += 1
                if isinstance(item,LegacyFightObservation):
                    if item.kind == 'TURN_OWNER_OBSERVED': owners += 1
                    elif item.kind == 'TURN_END_OBSERVED': ends += 1
                    elif item.kind == 'FIGHT_READY_OBSERVED': ready += 1
                else:
                    if item.kind == 'CAST_WIRE_OBSERVED': casts += 1
                    elif item.kind == 'DISPLACEMENT_OBSERVED': moves += 1
            else:
                foreign += 1
        if isinstance(item,HistoricalCombatObservation) and item.kind == 'FIGHT_RESULT_BOUNDARY_OBSERVED':
            results += 1

    if local == 0:
        return report('PARTIAL_EVIDENCE','P54_LOCAL_ACTOR_NOT_SEEN_IN_FIGHT',fight_id,len(observations),
                      local,owners,ends,ready,casts,moves,foreign,results)
    if owners == 0 and casts == 0 and moves == 0 and ready == 0:
        return report('PARTIAL_EVIDENCE','P54_LOCAL_ACTOR_REFERENCE_TOO_WEAK',fight_id,len(observations),
                      local,owners,ends,ready,casts,moves,foreign,results)
    return report('RESEARCH_ACTOR_CONTINUITY_ONLY',None,fight_id,len(observations),
                  local,owners,ends,ready,casts,moves,foreign,results)
