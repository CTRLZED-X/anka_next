"""Pure action-specific authoritative outcome correlation for M11.

Correlation is monotonic.  A later weak/inconclusive observation cannot erase
already-proven action consequences, and separate authoritative observations may
satisfy different outcome obligations over time.
"""
from __future__ import annotations
from dataclasses import dataclass
from anka_contracts.action import ActionCommand
from anka_contracts.execution import ExecutionOutcomeEvidence

MINIMUM_OUTCOME_PROOFS: dict[str, tuple[str, ...]] = {
    "CAST": ("SPELL_CAST_CONFIRMED", "RESOURCE_DELTA_OR_TURN_PROGRESS"),
    "MOVE": ("ACTOR_CELL_CHANGED",),
    "READY": ("READY_OR_PHASE_CONFIRMED",),
    "END_TURN": ("TURN_OWNER_CHANGED",),
    "JOIN_FIGHT": ("FIGHT_JOIN_CONFIRMED",),
    "WORLD_MOVE": ("WORLD_MAP_OR_CELL_CHANGED",),
    "START_FIGHT": ("FIGHT_ENTRY_CONFIRMED",),
}

def required_outcome_proofs(command: ActionCommand) -> tuple[str, ...]:
    minimum = MINIMUM_OUTCOME_PROOFS[command.kind]
    return tuple(dict.fromkeys(minimum + tuple(command.expected_outcome_proofs)))

def validates_minimum_outcome_policy(command: ActionCommand) -> bool:
    return set(MINIMUM_OUTCOME_PROOFS[command.kind]).issubset(command.expected_outcome_proofs)

@dataclass(frozen=True,slots=True)
class OutcomeVerdict:
    status:str
    reason:str
    unresolved:tuple[str,...]


def correlate(
    command:ActionCommand,
    evidence:ExecutionOutcomeEvidence,
    *,
    current_status:str='PENDING',
    unresolved_obligations:tuple[str,...]|None=None,
)->OutcomeVerdict:
    """Correlate one observation without regressing already-established truth.

    ``unresolved_obligations`` is the durable remainder from earlier matching
    observations.  This is what lets proof A and a later proof B settle an action
    that requires both A+B; no single observation is required to repeat all proof.
    """
    outstanding=tuple(required_outcome_proofs(command) if unresolved_obligations is None else unresolved_obligations)
    preserve='UNCERTAIN' if current_status=='UNCERTAIN' else ('CONFIRMED_UNSETTLED' if current_status=='CONFIRMED_UNSETTLED' else 'PENDING')

    if not evidence.authoritative:return OutcomeVerdict('IGNORE','OUTCOME_NOT_AUTHORITATIVE',outstanding)
    if evidence.correlated_action_id is not None and evidence.correlated_action_id!=command.action_id:return OutcomeVerdict('IGNORE','OUTCOME_ACTION_ID_MISMATCH',outstanding)
    if (evidence.account_id,evidence.client_instance_id)!=(command.account_id,command.client_instance_id):return OutcomeVerdict('IGNORE','OUTCOME_SCOPE_MISMATCH',outstanding)
    # START_FIGHT and JOIN_FIGHT are boundary-crossing actions: their authoritative
    # consequence is expected in a *new/target* fight epoch, not the current world
    # state epoch on which the click was based.  Other actions remain exact-epoch.
    if command.kind=='START_FIGHT':
        if evidence.fight_epoch<=command.fight_epoch:return OutcomeVerdict('IGNORE','OUTCOME_FIGHT_ENTRY_EPOCH_NOT_NEW',outstanding)
    elif command.kind=='JOIN_FIGHT':
        target=dict(command.semantic_target).get('target_fight_epoch')
        try:target_epoch=int(target)
        except (TypeError,ValueError):return OutcomeVerdict('IGNORE','OUTCOME_JOIN_TARGET_EPOCH_INVALID',outstanding)
        if evidence.fight_epoch!=target_epoch:return OutcomeVerdict('IGNORE','OUTCOME_JOIN_TARGET_EPOCH_MISMATCH',outstanding)
    elif evidence.fight_epoch!=command.fight_epoch:
        return OutcomeVerdict('IGNORE','OUTCOME_SCOPE_MISMATCH',outstanding)
    if evidence.canonical_cursor<=command.basis_canonical_cursor:return OutcomeVerdict('IGNORE','OUTCOME_NOT_CAUSALLY_NEWER',outstanding)
    if command.actor_id is not None and evidence.actor_id is not None and evidence.actor_id!=command.actor_id:return OutcomeVerdict('IGNORE','OUTCOME_ACTOR_MISMATCH',outstanding)
    # Turn may advance for END_TURN / fight lifecycle consequences, but older-turn evidence never settles.
    if evidence.observed_turn_epoch<command.turn_epoch:return OutcomeVerdict('IGNORE','OUTCOME_TURN_REGRESSION',outstanding)

    if evidence.result=='FAILURE':return OutcomeVerdict('PROVEN_FAILURE','AUTHORITATIVE_ACTION_FAILURE',())
    if evidence.result=='INCONCLUSIVE':return OutcomeVerdict(preserve,'OUTCOME_INCONCLUSIVE',outstanding)

    seen=set(evidence.proofs)
    missing=tuple(x for x in outstanding if x not in seen)
    if not missing:return OutcomeVerdict('SETTLED_SUCCESS','EXPECTED_OUTCOME_PROOFS_SATISFIED',())

    newly_satisfied=tuple(x for x in outstanding if x in seen)
    if newly_satisfied or current_status=='CONFIRMED_UNSETTLED':
        return OutcomeVerdict('CONFIRMED_UNSETTLED','PARTIAL_OUTCOME_PROOF',missing)
    if current_status=='UNCERTAIN':
        return OutcomeVerdict('UNCERTAIN','NO_EXPECTED_OUTCOME_PROOF_WHILE_SEND_UNCERTAIN',outstanding)
    return OutcomeVerdict('PENDING','NO_EXPECTED_OUTCOME_PROOF',outstanding)
