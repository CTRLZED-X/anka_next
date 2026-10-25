"""Kernel-backed offline cast feasibility: NEVER a cast planner or actuation permit.

State is read through a caller-owned, synthetic snapshot. Missing map, turn
history, class/spell binding and client evidence cannot be substituted by guesses.
The kernel is the ONLY authority consulted for known static cast constraints.
"""
from __future__ import annotations
from anka_contracts.decision import CastProbe, CastProbeReport
from anka_game_kernel.domain.ids import SpellId
from anka_game_kernel.mechanics.casting.model import CastAvailabilityContext, CastAvailabilitySpec


_MISSING_ALWAYS = (
    'CURRENT_CLIENT_BUILD_UNCERTIFIED',
    'MAP_GEOMETRY_AND_LINE_OF_SIGHT_UNPROVEN',
    'SPELL_EQUIPMENT_AND_SLOT_UNPROVEN',
    'ACTOR_CLASS_UNVERIFIED',
    'TURN_CAST_COUNTS_UNAVAILABLE',
    'TARGET_SEMANTICS_UNVERIFIED',
)


def inspect_cast_probe(snapshot: dict | None, probe: CastProbe, *, kernel) -> CastProbeReport:
    """Return explainable feasibility, never executable instructions or approval."""
    if not isinstance(probe,CastProbe):raise TypeError('CAST_PROBE_CONTRACT_REQUIRED')
    reasons=[];missing=[];revision=None;spell_name=None;cost=None;legality='NOT_EVALUATED'
    if not isinstance(snapshot,dict):
        reasons.append('STATE_SNAPSHOT_MISSING')
    else:
        revision=snapshot.get('revision') if type(snapshot.get('revision')) is int else None
        if type(snapshot.get('schema')) is not int or snapshot['schema']!=1: reasons.append('STATE_SCHEMA_UNRECOGNIZED')
        if snapshot.get('authority')!='SYNTHETIC_FIXTURE_ONLY' or snapshot.get('actionable') is not False:
            reasons.append('STATE_AUTHORITY_NOT_SYNTHETIC')
        if snapshot.get('session_id')!=probe.session_id or snapshot.get('account_id')!=probe.account_id or type(snapshot.get('account_generation')) is not int or snapshot['account_generation']!=probe.account_generation:
            reasons.append('ACCOUNT_SCOPE_MISMATCH')
        if snapshot.get('fight_id')!=probe.fight_id:reasons.append('FIGHT_EPOCH_MISMATCH')
        if revision is None or revision<probe.minimum_revision:reasons.append('STATE_REVISION_STALE')
        if type(snapshot.get('last_sequence')) is not int or snapshot['last_sequence']!=revision:
            reasons.append('STATE_SEQUENCE_INCONSISTENT')
        if snapshot.get('phase')!='IN_FIGHT':reasons.append('FIGHT_NOT_ACTIVE')
        if type(snapshot.get('turn_owner_id')) is not int or snapshot['turn_owner_id']!=probe.actor_id:
            reasons.append('TURN_OWNER_NOT_PROVEN')
        actors=snapshot.get('actors')
        if not isinstance(actors,dict) or not isinstance(actors.get(str(probe.actor_id)),dict):
            reasons.append('ACTOR_STATE_MISSING')
        else:
            actor=actors[str(probe.actor_id)]
            for key in ('hp','max_hp','AP','MP','cell_id','cooldowns'):
                if key not in actor or actor[key] is None:reasons.append('ACTOR_'+key.upper()+'_MISSING')
            # Reject structurally invalid snapshots; the reducer normally prevents these.
            if not all(type(actor.get(k)) is int and actor[k]>=0 for k in ('AP','MP','cell_id','hp','max_hp') if actor.get(k) is not None):
                reasons.append('ACTOR_RESOURCES_INVALID')
            if (type(actor.get('hp')) is int and type(actor.get('max_hp')) is int and actor['hp']>actor['max_hp']):
                reasons.append('ACTOR_HP_EXCEEDS_MAXIMUM')
            if (type(actor.get('AP')) is int and actor['AP']>200) or (type(actor.get('MP')) is int and actor['MP']>200) or (type(actor.get('cell_id')) is int and actor['cell_id']>100000):
                reasons.append('ACTOR_RESOURCES_OUT_OF_RANGE')
            if actor.get('cooldowns') is not None and (
                not isinstance(actor['cooldowns'],list)
                or any(not isinstance(pair,list) or len(pair)!=2 or type(pair[0]) is not int or pair[0]<=0 or type(pair[1]) is not int or not 0<=pair[1]<=1000 for pair in actor['cooldowns'])
            ):
                reasons.append('ACTOR_COOLDOWNS_INVALID')
    if reasons:
        return CastProbeReport('BLOCKED_EVIDENCE',probe,tuple(dict.fromkeys(reasons)),(),revision,None,None,legality)

    # The game kernel is caller-provided, not constructed by this system.
    # Invalid/missing static data fails closed; no fallback spells are invented.
    try:
        spell=kernel.spells.require(SpellId(probe.spell_id))
        view=kernel.spell_mechanics_overlay.require_grade(SpellId(probe.spell_id),probe.grade)
        grade=view.effective_grade
        spell_name=spell.name
        cost=grade.ap_cost
    except (AttributeError,KeyError,ValueError,TypeError,LookupError) as exc:
        # DefinitionNotFoundError is part of the kernel exception family, not
        # necessarily a LookupError: no source exception message is surfaced.
        return CastProbeReport('BLOCKED_STATIC_DATA',probe,('SPELL_OR_GRADE_NOT_IN_VERIFIED_STATIC_CATALOG',),(),revision,None,None,'NOT_EVALUATED')
    except Exception:
        return CastProbeReport('BLOCKED_STATIC_DATA',probe,('KERNEL_STATIC_EVALUATION_FAILED',),(),revision,None,None,'NOT_EVALUATED')
    if grade.max_cast_per_turn<0 or grade.initial_cooldown<0:
        return CastProbeReport('BLOCKED_STATIC_DATA',probe,('KERNEL_STATIC_CAST_RULE_UNRESOLVED',),(),revision,spell_name,cost,'NOT_EVALUATED')
    actor=snapshot['actors'][str(probe.actor_id)]
    cooldowns=actor['cooldowns']
    if cooldowns is None:
        remaining=None
    else:
        # Reject conflicting duplicate cooldowns instead of choosing one.
        ids=[item[0] for item in cooldowns]
        if len(set(ids))!=len(ids):
            return CastProbeReport('BLOCKED_EVIDENCE',probe,('COOLDOWN_ID_DUPLICATED',),(),revision,spell_name,cost,'NOT_EVALUATED')
        remaining=next((item[1] for item in cooldowns if item[0]==probe.spell_id),None)
    try:
        spec=CastAvailabilitySpec(
            ap_cost=grade.ap_cost,max_cast_per_turn=grade.max_cast_per_turn,
            max_global_cast_per_turn=grade.max_global_cast_per_turn,
            max_cast_per_target=grade.max_cast_per_target,
            min_cast_interval=grade.min_cast_interval,
            initial_cooldown=grade.initial_cooldown,
            state_criterion=grade.state_criterion,requires_summon_slot=grade.can_summon,
        )
        result=kernel.casting.evaluate(spec,CastAvailabilityContext(
            current_ap=actor['AP'],casts_this_turn=None,global_casts_this_turn=None,
            cooldown_remaining=remaining,casts_on_target_this_turn=None,
            active_state_ids=None,summon_slots_remaining=None,
        ))
    except Exception:
        return CastProbeReport('BLOCKED_KERNEL',probe,('KERNEL_CAST_EVALUATION_FAILED',),(),revision,spell_name,cost,'NOT_EVALUATED')
    if result.legal is False:
        return CastProbeReport('REJECTED_BY_KERNEL',probe,('KERNEL_'+str(result.failure).upper().split('.')[-1],),(),revision,spell_name,cost,'ILLEGAL')
    if result.legal is None:
        missing=tuple(result.missing_inputs)
        legality='UNKNOWN'
    elif result.legal is True:
        legality='AVAILABILITY_ONLY'
    else:
        return CastProbeReport('BLOCKED_KERNEL',probe,('KERNEL_RESULT_UNRECOGNIZED',),(),revision,spell_name,cost,'NOT_EVALUATED')
    return CastProbeReport('RESEARCH_ONLY',probe,_MISSING_ALWAYS+('SYNTHETIC_STATE_NON_AUTHORITATIVE',),missing,
                           revision,spell_name,cost,legality)
