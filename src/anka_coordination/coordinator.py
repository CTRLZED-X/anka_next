"""Definitive M9 multi-account coordination authority.

The coordinator owns no gameplay state and no physical input. It accepts immutable,
per-account observations, proves cross-account coherence, and issues generation-bound
turn permits only when all required evidence agrees.
"""
from __future__ import annotations
from dataclasses import replace
from hashlib import sha256
import json
from threading import RLock
from collections import OrderedDict

from anka_contracts.coordination import (
    CoordinationUpdate, DefinitivePartySnapshot, MemberCursor, MemberPartyObservation,
    PartyBarrier, PartyCoherenceFrame, PartyRosterMember, TurnPermit, ActionPermit,
)


class CoordinationRejected(ValueError):
    pass


def _hash_semantic(obj: object) -> str:
    return sha256(json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


class PartyCoordinatorService:
    """Single owner of party coherence and ephemeral permit generations."""

    def __init__(self, party_id: str, roster: tuple[PartyRosterMember, ...], *, party_generation: int = 1, observer=None):
        if not party_id.startswith('party-'):
            raise CoordinationRejected('INVALID_PARTY_ID')
        if type(party_generation) is not int or party_generation <= 0:
            raise CoordinationRejected('INVALID_PARTY_GENERATION')
        if type(roster) is not tuple or not 2 <= len(roster) <= 8 or any(not isinstance(x,PartyRosterMember) for x in roster):
            raise CoordinationRejected('INVALID_PARTY_ROSTER')
        required=tuple(x for x in roster if x.required)
        if len({x.account_id for x in roster})!=len(roster) or len({x.actor_id for x in roster})!=len(roster) or len({x.client_instance_id for x in roster})!=len(roster):
            raise CoordinationRejected('DUPLICATE_PARTY_BINDING')
        if sum(x.role=='leader' and x.required for x in roster)!=1 or len(required)<2:
            raise CoordinationRejected('INVALID_REQUIRED_PARTY_ROSTER')
        self.party_id=party_id
        self._roster=roster
        self._by_account={x.account_id:x for x in roster}
        self._by_actor={x.actor_id:x for x in roster}
        self._observations:dict[str,MemberPartyObservation]={}
        # Exact observation-id conflict detection is useful, but retaining every
        # transport identity forever would leak memory during long-running farms.
        # Canonical cursor/revision monotonicity remains the safety authority for
        # observations older than this bounded recent-id cache.
        self._max_seen_observations=8192
        self._seen:OrderedDict[str,MemberPartyObservation]=OrderedDict()
        self._party_generation=party_generation
        self._permit_generation=1
        self._last_semantic_token='0'*64
        self._lock=RLock()
        self._observer=observer

    @property
    def roster(self) -> tuple[PartyRosterMember,...]:
        return self._roster

    @property
    def party_generation(self) -> int:
        with self._lock:return self._party_generation

    def invalidate_ephemeral_permits(self) -> None:
        """Invalidate all previously issued permits without changing observed game truth.

        The composition root calls this when the coordination lifetime changes or when an
        operator/runtime fence requires fresh authorization.  Callers must obtain a new
        permit and compare both party_generation and permit_generation.
        """
        with self._lock:
            self._party_generation += 1
            self._permit_generation += 1
            self._last_semantic_token='0'*64

    def _record(self,name:str,**kwargs)->None:
        if self._observer is None:return
        try:self._observer.record(name,owner_system='anka_coordination',**kwargs)
        except Exception:pass

    def _remember_observation_id(self,observation:MemberPartyObservation)->None:
        self._seen[observation.observation_id]=observation
        self._seen.move_to_end(observation.observation_id)
        while len(self._seen)>self._max_seen_observations:
            self._seen.popitem(last=False)

    def _publish_progress(self,before:DefinitivePartySnapshot,after:DefinitivePartySnapshot)->None:
        # Observer I/O happens after the coordination lock is released.  Failure
        # here must never change party authority or permit generations.
        common={'fight_epoch':after.fight_epoch if after.fight_epoch>0 else None,'payload':{'party_id':after.party_id,'phase':after.phase,'party_generation':after.party_generation,'permit_generation':after.permit_generation}}
        if not before.join_barrier.satisfied and after.join_barrier.satisfied:
            self._record('coordination.join_barrier_satisfied',boundary='coordination.join_barrier',evidence_class='AUTHORITY_COMMITTED',payload={**common['payload'],'required_accounts':list(after.join_barrier.required_accounts),'evidence_ids':list(after.join_barrier.evidence_ids)},fight_epoch=common['fight_epoch'])
        if not before.placement_barrier.satisfied and after.placement_barrier.satisfied:
            self._record('coordination.placement_barrier_satisfied',boundary='coordination.placement_barrier',evidence_class='AUTHORITY_COMMITTED',payload={**common['payload'],'required_accounts':list(after.placement_barrier.required_accounts),'evidence_ids':list(after.placement_barrier.evidence_ids)},fight_epoch=common['fight_epoch'])
        if not before.ready_barrier.satisfied and after.ready_barrier.satisfied:
            self._record('coordination.ready_barrier_satisfied',boundary='coordination.ready_barrier',evidence_class='AUTHORITY_COMMITTED',payload={**common['payload'],'required_accounts':list(after.ready_barrier.required_accounts),'evidence_ids':list(after.ready_barrier.evidence_ids)},fight_epoch=common['fight_epoch'])
        if before.turn_owner_account_id!=after.turn_owner_account_id and after.turn_owner_account_id is not None:
            member=next((m for m in after.members if m.account_id==after.turn_owner_account_id),None)
            self._record('coordination.turn_owner_proved',boundary='coordination.first_turn',evidence_class='AUTHORITY_COMMITTED',account_id=after.turn_owner_account_id,fight_epoch=common['fight_epoch'],turn_epoch=member.turn_epoch if member is not None else None,payload={**common['payload'],'owner_account_id':after.turn_owner_account_id,'evidence_ids':list(member.evidence_ids if member is not None else ())})

    def observe(self, observation: MemberPartyObservation) -> CoordinationUpdate:
        # Capture/decoder lanes may publish account observations concurrently.
        # Coordination is a single mutable authority, so serialize the entire
        # validation+mutation+permit-generation transaction.
        with self._lock:
            before=self._build_snapshot()
            result=self._observe_unlocked(observation)
            after=result.snapshot
        if result.status=='APPLIED' and result.semantic_progress:
            self._publish_progress(before,after)
        return result

    def _observe_unlocked(self, observation: MemberPartyObservation) -> CoordinationUpdate:
        if not isinstance(observation,MemberPartyObservation):
            raise CoordinationRejected('INVALID_COORDINATION_OBSERVATION')
        binding=self._by_account.get(observation.account_id)
        if binding is None:
            return CoordinationUpdate('REJECTED',False,False,'ACCOUNT_NOT_IN_ROSTER',self.snapshot())
        if (observation.client_instance_id,observation.actor_id)!=(binding.client_instance_id,binding.actor_id):
            return CoordinationUpdate('REJECTED',False,False,'MEMBER_IDENTITY_MISMATCH',self.snapshot())
        seen=self._seen.get(observation.observation_id)
        if seen is not None:
            if seen != observation:
                return CoordinationUpdate('REJECTED',False,False,'OBSERVATION_ID_CONFLICT',self.snapshot())
            return CoordinationUpdate('DUPLICATE',False,False,'DUPLICATE_IDEMPOTENT',self.snapshot())
        previous=self._observations.get(observation.account_id)
        if previous is not None:
            if observation.canonical_cursor < previous.canonical_cursor or observation.snapshot_revision < previous.snapshot_revision:
                return CoordinationUpdate('REJECTED',False,False,'MEMBER_CURSOR_REGRESSION',self.snapshot())
            if observation.canonical_cursor == previous.canonical_cursor and observation.snapshot_revision == previous.snapshot_revision:
                if observation.semantic_tuple() == previous.semantic_tuple():
                    self._remember_observation_id(observation)
                    return CoordinationUpdate('DUPLICATE',False,False,'SAME_REVISION_IDEMPOTENT',self.snapshot())
                return CoordinationUpdate('REJECTED',False,False,'SAME_REVISION_CONFLICT',self.snapshot())
            if observation.fight_epoch < previous.fight_epoch or (observation.fight_epoch==previous.fight_epoch and observation.turn_epoch < previous.turn_epoch):
                return CoordinationUpdate('REJECTED',False,False,'MEMBER_EPOCH_REGRESSION',self.snapshot())
        before=self.snapshot()
        self._remember_observation_id(observation)
        self._observations[observation.account_id]=observation
        after=self._build_snapshot()
        semantic_progress=after.semantic_progress_token != before.semantic_progress_token
        if semantic_progress:
            self._permit_generation += 1
            after=self._build_snapshot()
        self._last_semantic_token=after.semantic_progress_token
        return CoordinationUpdate('APPLIED',True,semantic_progress,'SEMANTIC_PROGRESS' if semantic_progress else 'CURSOR_ONLY_PROGRESS',after)

    def _required(self) -> tuple[PartyRosterMember,...]:
        return tuple(x for x in self._roster if x.required)

    def _coherence_facts(self):
        required=self._required(); obs=[self._observations.get(x.account_id) for x in required]
        missing=[];conflicts=[]
        for binding,o in zip(required,obs):
            if o is None:
                missing.append(f'MEMBER_NOT_OBSERVED:{binding.account_id}')
            elif o.health!='HEALTHY':
                missing.append(f'MEMBER_NOT_HEALTHY:{binding.account_id}:{o.health}')
            elif o.capture_gap:
                missing.append(f'MEMBER_CAPTURE_GAP:{binding.account_id}')
            elif o.fight_id is None or o.fight_epoch<=0:
                missing.append(f'FIGHT_IDENTITY_UNPROVEN:{binding.account_id}')
            elif o.map_id is None:
                missing.append(f'FIGHT_MAP_UNPROVEN:{binding.account_id}')
        present=[o for o in obs if o is not None]
        fight_ids={o.fight_id for o in present if o.fight_id is not None}
        fight_epochs={o.fight_epoch for o in present if o.fight_epoch>0}
        map_ids={o.map_id for o in present if o.map_id is not None}
        if len(fight_ids)>1: conflicts.append('FIGHT_ID_CONFLICT')
        if len(fight_epochs)>1: conflicts.append('FIGHT_EPOCH_CONFLICT')
        if len(map_ids)>1: conflicts.append('FIGHT_MAP_CONFLICT')
        same=(len(obs)==len(required) and all(o is not None and o.health=='HEALTHY' and not o.capture_gap and o.fight_id is not None and o.map_id is not None and o.fight_epoch>0 for o in obs)
              and len(fight_ids)==len(fight_epochs)==len(map_ids)==1)
        fight_id=next(iter(fight_ids)) if len(fight_ids)==1 else None
        fight_epoch=next(iter(fight_epochs)) if len(fight_epochs)==1 else 0
        return required,obs,tuple(missing),tuple(conflicts),same,fight_id,fight_epoch

    def _barrier(self,name:str,required,obs,same:bool,fight_epoch:int,conflicts:tuple[str,...]) -> PartyBarrier:
        attr={'JOIN':'joined','PLACEMENT':'placed','READY':'ready'}[name]
        confirmed=[];missing=[];bad=[];evidence=[]
        for binding,o in zip(required,obs):
            if o is None:
                missing.append(binding.account_id);continue
            if not same or o.health!='HEALTHY' or o.capture_gap:
                bad.append(binding.account_id);continue
            if name=='JOIN':
                value=(o.joined is True)
            elif name=='PLACEMENT':
                value=(o.joined is True and o.placed is True)
            else:
                value=(o.joined is True and o.placed is True and o.ready is True)
            if value:
                confirmed.append(binding.account_id);evidence.extend(o.evidence_ids)
            else:
                missing.append(binding.account_id)
        if conflicts:
            bad=sorted(set(bad)|{x.account_id for x in required})
        required_ids=tuple(x.account_id for x in required)
        return PartyBarrier(name,self.party_id,fight_epoch,self._permit_generation,
            set(confirmed)==set(required_ids) and not missing and not bad,
            required_ids,tuple(sorted(confirmed)),tuple(sorted(set(missing))),tuple(sorted(set(bad))),tuple(sorted(set(evidence))))

    def _build_snapshot(self) -> DefinitivePartySnapshot:
        required,obs,missing,conflicts,same,fight_id,fight_epoch=self._coherence_facts()
        join=self._barrier('JOIN',required,obs,same,fight_epoch,conflicts)
        placement=self._barrier('PLACEMENT',required,obs,same,fight_epoch,conflicts)
        ready=self._barrier('READY',required,obs,same,fight_epoch,conflicts)
        turn_owner=None
        owner_values={o.turn_owner_actor_id for o in obs if o is not None and o.turn_owner_actor_id is not None}
        # A turn owner is authoritative only when *every* required member proves
        # the same positive turn epoch.  Filtering zero epochs out of the set can
        # otherwise make {0, 1} look like the coherent singleton {1} and issue a
        # permit from incomplete evidence.
        positive_turn_epochs={o.turn_epoch for o in obs if o is not None and o.turn_epoch>0}
        all_turn_epochs_proven=(
            len(obs)==len(required)
            and all(o is not None and o.turn_epoch>0 for o in obs)
            and len(positive_turn_epochs)==1
        )
        local_conflicts=list(conflicts)
        if len(owner_values)>1:
            local_conflicts.append('TURN_OWNER_SKEW')
        elif len(owner_values)==1:
            owner_actor=next(iter(owner_values))
            owner_binding=self._by_actor.get(owner_actor)
            if owner_binding is None:
                local_conflicts.append('TURN_OWNER_NOT_PARTY_MEMBER')
            elif not owner_binding.required:
                # Required-member observations cannot authorize input for a
                # non-required roster member whose own state is outside the
                # authoritative quorum.  Fail closed instead of constructing a
                # snapshot whose owner is absent from its authoritative members.
                local_conflicts.append('TURN_OWNER_NOT_REQUIRED_MEMBER')
            elif (len(obs)==len(required)
                  and all(o is not None and o.turn_owner_actor_id==owner_actor for o in obs)
                  and all_turn_epochs_proven):
                turn_owner=owner_binding.account_id
            else:
                missing=tuple(sorted(set(missing)|{'TURN_OWNER_NOT_COHERENT'}))
        else:
            missing=tuple(sorted(set(missing)|{'TURN_OWNER_UNPROVEN'}))
        if not obs or any(o is None for o in obs):phase='WAIT_MEMBERS'
        elif local_conflicts and any(x in local_conflicts for x in ('FIGHT_ID_CONFLICT','FIGHT_EPOCH_CONFLICT','FIGHT_MAP_CONFLICT','TURN_OWNER_NOT_PARTY_MEMBER','TURN_OWNER_NOT_REQUIRED_MEMBER')):phase='BLOCKED'
        elif not same:phase='WAIT_SAME_FIGHT'
        elif not join.satisfied:phase='WAIT_JOIN'
        elif not placement.satisfied:phase='WAIT_PLACEMENT'
        elif not ready.satisfied:phase='WAIT_READY'
        elif turn_owner is None:phase='WAIT_TURN_OWNER'
        else:phase='TURN_ACTIVE'
        member_tuple=tuple(o for o in obs if o is not None)
        # Required members own party barriers, but optional roster members may
        # still receive pre-turn permits. Their permission-relevant semantics
        # therefore must participate in the opaque generation token; otherwise
        # an optional member's authority can change while permit_generation does
        # not, defeating stale-permit fencing.
        optional_tuple=tuple(
            self._observations[x.account_id]
            for x in self._roster
            if not x.required and x.account_id in self._observations
        )
        semantic_obj={
            'party':self.party_id,'party_generation':self._party_generation,'fight_epoch':fight_epoch,'fight_id':fight_id,'phase':phase,
            'members':[o.semantic_tuple() for o in member_tuple],
            'optional_members':[o.semantic_tuple() for o in optional_tuple],
            'same':same,'owner':turn_owner,
            'join':join.satisfied,'placement':placement.satisfied,'ready':ready.satisfied,
            'missing':sorted(missing),'conflicts':sorted(set(local_conflicts)),
        }
        token=_hash_semantic(semantic_obj)
        return DefinitivePartySnapshot(self.party_id,self._party_generation,self._permit_generation,fight_epoch,fight_id,phase,member_tuple,same,turn_owner,join,placement,ready,tuple(sorted(set(missing))),tuple(sorted(set(local_conflicts))),token)

    def snapshot(self) -> DefinitivePartySnapshot:
        with self._lock:return self._build_snapshot()

    def coherence(self, party_id: str) -> PartyCoherenceFrame:
        with self._lock:
            if party_id != self.party_id:
                raise CoordinationRejected('PARTY_ID_MISMATCH')
            snap=self._build_snapshot()
            members=tuple(MemberCursor(o.account_id,o.client_instance_id,o.canonical_cursor,o.snapshot_revision,o.fight_epoch,o.turn_epoch,o.health=='HEALTHY' and not o.capture_gap) for o in snap.members)
            return PartyCoherenceFrame(self.party_id,snap.fight_epoch,members,snap.same_fight_proven,snap.phase,snap.turn_owner_account_id,snap.permit_generation,snap.missing_evidence,snap.conflicting_evidence)

    def turn_permit(self, party_id: str, account_id: str) -> TurnPermit:
        # Snapshot + member lookup must be one atomic read; otherwise a concurrent
        # observation could pair a permit generation with a different member epoch.
        with self._lock:
            if party_id != self.party_id:
                raise CoordinationRejected('PARTY_ID_MISMATCH')
            if account_id not in self._by_account:
                raise CoordinationRejected('ACCOUNT_NOT_IN_ROSTER')
            snap=self._build_snapshot(); member=self._observations.get(account_id)
            turn_epoch=member.turn_epoch if member is not None else 0
            allowed=True;reason='PERMIT_GRANTED'
            if not snap.same_fight_proven:allowed=False;reason='SAME_FIGHT_UNPROVEN'
            elif not snap.ready_barrier.satisfied:allowed=False;reason='READY_BARRIER_UNSATISFIED'
            elif snap.conflicting_evidence:allowed=False;reason=snap.conflicting_evidence[0]
            elif snap.turn_owner_account_id is None:allowed=False;reason='TURN_OWNER_UNPROVEN'
            elif snap.turn_owner_account_id != account_id:allowed=False;reason='NOT_CURRENT_TURN_OWNER'
            elif member is None or member.health!='HEALTHY' or member.capture_gap:allowed=False;reason='MEMBER_STALE'
            return TurnPermit(self.party_id,account_id,snap.fight_epoch,turn_epoch,snap.permit_generation,allowed,reason,snap.party_generation)
    def action_permit(self, party_id: str, account_id: str, scope: str) -> ActionPermit:
        """Issue only the authority that the current phase can actually prove.

        Pre-turn scopes deliberately do not require a turn owner.  They remain
        generation-bound and require progressively stronger party barriers.
        WORLD is never granted here because Coordination does not own world-route
        intent; a composition-level authority must prove that separately.
        """
        if scope not in ('TURN','PLACEMENT','READY','JOIN','WORLD','FIGHT_ENTRY'):
            raise CoordinationRejected('INVALID_ACTION_PERMIT_SCOPE')
        with self._lock:
            if party_id != self.party_id:
                raise CoordinationRejected('PARTY_ID_MISMATCH')
            if account_id not in self._by_account:
                raise CoordinationRejected('ACCOUNT_NOT_IN_ROSTER')
            snap=self._build_snapshot(); member=self._observations.get(account_id)
            turn_epoch=member.turn_epoch if member is not None else 0
            authoritative_map_id=(snap.members[0].map_id if snap.same_fight_proven and snap.members else None)
            member_matches_fight=(
                member is not None
                and snap.same_fight_proven
                and member.fight_id==snap.fight_id
                and member.fight_epoch==snap.fight_epoch
                and member.map_id==authoritative_map_id
            )

            if scope=='TURN':
                allowed=True;reason='PERMIT_GRANTED'
                if not snap.same_fight_proven:allowed=False;reason='SAME_FIGHT_UNPROVEN'
                elif not snap.ready_barrier.satisfied:allowed=False;reason='READY_BARRIER_UNSATISFIED'
                elif snap.conflicting_evidence:allowed=False;reason=snap.conflicting_evidence[0]
                elif snap.turn_owner_account_id is None:allowed=False;reason='TURN_OWNER_UNPROVEN'
                elif snap.turn_owner_account_id != account_id:allowed=False;reason='NOT_CURRENT_TURN_OWNER'
                elif member is None or member.health!='HEALTHY' or member.capture_gap:allowed=False;reason='MEMBER_STALE'
                evidence=tuple(dict.fromkeys((snap.ready_barrier.evidence_ids if allowed else ()) + (member.evidence_ids if member is not None else ())))
            elif scope=='JOIN':
                allowed=True;reason='PERMIT_GRANTED'
                if not snap.same_fight_proven:allowed=False;reason='SAME_FIGHT_UNPROVEN'
                elif snap.conflicting_evidence:allowed=False;reason=snap.conflicting_evidence[0]
                elif member is None or member.health!='HEALTHY' or member.capture_gap:allowed=False;reason='MEMBER_STALE'
                elif not member_matches_fight:allowed=False;reason='MEMBER_FIGHT_MISMATCH'
                elif member.joined is True:allowed=False;reason='ALREADY_JOINED'
                evidence=tuple(dict.fromkeys(
                    tuple(e for o in snap.members for e in o.evidence_ids)
                    + (member.evidence_ids if member is not None else ())
                )) if allowed else ()
            elif scope=='PLACEMENT':
                allowed=True;reason='PERMIT_GRANTED'
                if not snap.same_fight_proven:allowed=False;reason='SAME_FIGHT_UNPROVEN'
                elif not snap.join_barrier.satisfied:allowed=False;reason='JOIN_BARRIER_UNSATISFIED'
                elif snap.conflicting_evidence:allowed=False;reason=snap.conflicting_evidence[0]
                elif member is None or member.health!='HEALTHY' or member.capture_gap:allowed=False;reason='MEMBER_STALE'
                elif not member_matches_fight:allowed=False;reason='MEMBER_FIGHT_MISMATCH'
                elif member.placed is True:allowed=False;reason='ALREADY_PLACED'
                evidence=tuple(dict.fromkeys(snap.join_barrier.evidence_ids + (member.evidence_ids if member is not None else ()))) if allowed else ()
            elif scope=='READY':
                allowed=True;reason='PERMIT_GRANTED'
                if not snap.same_fight_proven:allowed=False;reason='SAME_FIGHT_UNPROVEN'
                elif not snap.placement_barrier.satisfied:allowed=False;reason='PLACEMENT_BARRIER_UNSATISFIED'
                elif snap.conflicting_evidence:allowed=False;reason=snap.conflicting_evidence[0]
                elif member is None or member.health!='HEALTHY' or member.capture_gap:allowed=False;reason='MEMBER_STALE'
                elif not member_matches_fight:allowed=False;reason='MEMBER_FIGHT_MISMATCH'
                elif member.ready is True:allowed=False;reason='ALREADY_READY'
                evidence=tuple(dict.fromkeys(snap.placement_barrier.evidence_ids + (member.evidence_ids if member is not None else ()))) if allowed else ()
            else:
                allowed=False;reason=('WORLD_AUTHORITY_NOT_OWNED_BY_COORDINATION' if scope=='WORLD' else 'FIGHT_ENTRY_AUTHORITY_NOT_OWNED_BY_COORDINATION');evidence=()

            return ActionPermit(self.party_id,account_id,scope,snap.fight_epoch,turn_epoch,snap.permit_generation,allowed,reason,snap.party_generation,evidence)

