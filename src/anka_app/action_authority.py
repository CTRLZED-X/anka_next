"""Composition-owned routing of semantic action authority.

No subsystem is allowed to grant authority that it does not own.  Coordination
owns party/fight phase permits; Workflow owns world-route and encounter intent.
This adapter combines those independent proofs for the controller/Execution ports
without moving either authority into Decision or Execution.
"""
from __future__ import annotations
from hashlib import sha256

from anka_contracts.coordination import ActionPermit
from anka_contracts.execution import ExecutionCoordinationPermit


class CompositeActionAuthority:
    def __init__(self, coordinator, workflow, observer=None):
        self._coord=coordinator;self._workflow=workflow;self._observer=observer

    def _record(self,name:str,**kwargs)->None:
        if self._observer is None:return
        try:self._observer.record(name,owner_system='anka_app',**kwargs)
        except Exception:pass

    def _identity_probe(self,party_id:str,account_id:str)->None:
        # Coordination validates stable party/account membership even though it
        # intentionally refuses to grant Workflow-owned scopes.
        self._coord.action_permit(party_id,account_id,'WORLD')

    @staticmethod
    def _target(plan_or_command)->dict[str,str]:
        return dict(plan_or_command.semantic_target)

    def _workflow_permit(self,party_id:str,account_id:str,scope:str,*,fight_epoch:int,turn_epoch:int,
                         action_key:str,semantic_target)->ActionPermit:
        self._identity_probe(party_id,account_id)
        snap=self._workflow.snapshot();target=dict(semantic_target)
        allowed=False;reason='WORKFLOW_SCOPE_NOT_AUTHORIZED'
        if snap.pending_action_id is not None:
            reason='WORKFLOW_ACTION_ALREADY_PENDING'
        elif scope=='WORLD':
            if snap.phase!='WORLD':reason='WORKFLOW_NOT_IN_WORLD_PHASE'
            elif fight_epoch!=0:reason='WORLD_ACTION_REQUIRES_NO_ACTIVE_FIGHT'
            else:
                expected=self._workflow.next_route_step()
                if target.get('route_step')!=expected:reason='WORLD_ROUTE_STEP_MISMATCH'
                else:allowed=True;reason='PERMIT_GRANTED'
        elif scope=='FIGHT_ENTRY':
            if snap.phase!='ENCOUNTER_SELECTED':reason='WORKFLOW_NOT_IN_FIGHT_ENTRY_INTENT_PHASE'
            elif fight_epoch!=0:reason='FIGHT_ENTRY_REQUIRES_WORLD_BASIS'
            elif snap.selected_encounter_id is None or snap.selected_encounter_map_id is None:
                reason='WORKFLOW_SELECTED_ENCOUNTER_UNBOUND'
            elif target.get('encounter_id')!=snap.selected_encounter_id or target.get('map_id')!=str(snap.selected_encounter_map_id):
                reason='WORKFLOW_SELECTED_ENCOUNTER_MISMATCH'
            else:allowed=True;reason='PERMIT_GRANTED'
        else:
            reason='WORKFLOW_SCOPE_NOT_OWNED'
        proof=()
        if allowed:
            digest=sha256((snap.progress_token+'|'+scope+'|'+account_id+'|'+action_key+'|'+repr(sorted(target.items()))).encode()).hexdigest()
            proof=('workflow-authority-'+digest[:40],)
        permit=ActionPermit(party_id,account_id,scope,fight_epoch,turn_epoch,snap.progress_generation,allowed,reason,
                           self._coord.party_generation,proof)
        self._record('authority.permit_evaluated',boundary='composition.action_authority',account_id=account_id,
                     fight_epoch=fight_epoch if fight_epoch>0 else None,turn_epoch=turn_epoch,
                     evidence_class='AUTHORITY_COMMITTED' if allowed else 'DERIVED',
                     payload={'scope':scope,'allowed':allowed,'reason':reason,'workflow_phase':snap.phase,
                              'workflow_progress_generation':snap.progress_generation,'action_key':action_key})
        return permit

    def _join_permit(self,party_id:str,account_id:str,semantic_target)->ActionPermit:
        """Bind JOIN authority to the exact fight identity Decision selected.

        Coordination can prove that the party observations describe one fight, but
        a bare JOIN permit does not contain the command's target fight ID.  Without
        this composition-level binding, a stale/malformed plan could keep the same
        fight epoch while pointing the Client projection at another fight.  The
        check is repeated for the ActionCommand immediately before input.
        """
        base=self._coord.action_permit(party_id,account_id,'JOIN')
        if not base.allowed:return base
        try:
            target=dict(semantic_target)
            target_id=target['target_fight_id']
            target_epoch=int(target['target_fight_epoch'])
            target_map=int(target['map_id']) if 'map_id' in target else None
        except (KeyError,TypeError,ValueError):
            return ActionPermit(base.party_id,base.account_id,base.scope,base.fight_epoch,base.turn_epoch,
                base.permit_generation,False,'JOIN_TARGET_IDENTITY_INVALID',base.party_generation,())
        snap=self._coord.snapshot()
        reason=None
        if target_epoch!=snap.fight_epoch:
            reason='JOIN_TARGET_FIGHT_EPOCH_MISMATCH'
        elif snap.fight_id is None or target_id!=snap.fight_id:
            reason='JOIN_TARGET_FIGHT_ID_MISMATCH'
        elif target_map is not None:
            observed_maps={m.map_id for m in snap.members if m.map_id is not None}
            if len(observed_maps)!=1 or target_map not in observed_maps:
                reason='JOIN_TARGET_MAP_MISMATCH'
        if reason is not None:
            return ActionPermit(base.party_id,base.account_id,base.scope,base.fight_epoch,base.turn_epoch,
                base.permit_generation,False,reason,base.party_generation,())
        return base

    def permit_for_plan(self,party_id,frame,plan,scope:str)->ActionPermit:
        if scope in ('WORLD','FIGHT_ENTRY'):
            return self._workflow_permit(party_id,frame.account_id,scope,fight_epoch=frame.fight_epoch,
                turn_epoch=frame.turn_epoch,action_key=plan.action_key,semantic_target=plan.semantic_target)
        if scope=='JOIN':
            return self._join_permit(party_id,frame.account_id,plan.semantic_target)
        return self._coord.action_permit(party_id,frame.account_id,scope)

    def permit_for_action(self,command)->ExecutionCoordinationPermit:
        scope=command.authority_scope
        if scope in ('WORLD','FIGHT_ENTRY'):
            p=self._workflow_permit(command.party_id,command.account_id,scope,fight_epoch=command.fight_epoch,
                turn_epoch=command.turn_epoch,action_key=command.action_key,semantic_target=command.semantic_target)
        elif scope=='JOIN':
            p=self._join_permit(command.party_id,command.account_id,command.semantic_target)
        else:
            p=self._coord.action_permit(command.party_id,command.account_id,scope)
        return ExecutionCoordinationPermit(p.party_id,p.account_id,p.fight_epoch,p.turn_epoch,p.party_generation,
            p.permit_generation,p.allowed,p.reason,p.evidence_ids,p.scope)
