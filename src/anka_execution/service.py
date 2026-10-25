"""Definitive M11 sole action admission / external-boundary authority."""
from __future__ import annotations
from hashlib import sha256
from threading import Lock
import json,time
from anka_contracts.action import ActionCommand,ActionOutcome
from anka_contracts.execution import ExecutionAdmission,ExecutionClientAttestation,ExecutionOutcomeEvidence
from anka_execution.arbiter import HostInputArbiter,InputLeaseBusy
from anka_execution.definitive_ledger import DefinitiveExecutionLedger,DefinitiveExecutionLedgerRejected
from anka_execution.drivers.fake_input import InputDriverFailure
from anka_execution.outcomes import validates_minimum_outcome_policy

class ExecutionServiceRejected(RuntimeError):pass

def _target_fingerprint(command:ActionCommand)->str:
    return sha256(json.dumps(list(command.semantic_target),sort_keys=True,separators=(',',':')).encode()).hexdigest()

def _attempt_id(command,lease):return 'attempt-'+sha256(f'{command.action_id}:{lease.lease_id}:{lease.lease_epoch}'.encode()).hexdigest()[:32]

class DefinitiveExecutionService:
    """Only this system may call a physical input driver.

    The service starts disarmed. A caller may arm a run only when the durable ledger
    has no unresolved external side effects. The driver itself may still enforce a
    stricter current-build/action-scope gate.
    """
    def __init__(self,*,run_id:str,run_generation:int,ledger:DefinitiveExecutionLedger,arbiter:HostInputArbiter,
                 state_reader,client,mechanics,coordination,driver,clock_ns=None,observer=None):
        if not run_id.startswith('run-') or type(run_generation) is not int or run_generation<=0:raise ExecutionServiceRejected('INVALID_EXECUTION_RUN')
        self.run_id=run_id;self.run_generation=run_generation;self.ledger=ledger;self.arbiter=arbiter;self.state_reader=state_reader;self.client=client;self.mechanics=mechanics;self.coordination=coordination;self.driver=driver;self.clock_ns=clock_ns or time.monotonic_ns;self._observer=observer
        self._armed=False;self._authority_generation=0;self.physical_input_count=0;self._last_safety_fault=None
        self._settlement_lock=Lock()
        # Never recover or arm from an unchecked projection.  The durable event
        # chain is the authority; a coherently-looking actions row may have been
        # corrupted or partially rewritten after a crash/disk fault.
        try:
            self.ledger.audit()
            self.ledger.recover_after_restart()
            self.ledger.audit()
        except Exception as exc:
            raise ExecutionServiceRejected('EXECUTION_LEDGER_BOOTSTRAP_INTEGRITY_FAILED:'+type(exc).__name__) from exc
    def _record(self,name:str,command:ActionCommand|None=None,**kwargs)->None:
        if self._observer is None:return
        if command is not None:
            kwargs.setdefault('account_id',command.account_id);kwargs.setdefault('fight_epoch',command.fight_epoch);kwargs.setdefault('turn_epoch',command.turn_epoch);kwargs.setdefault('action_id',command.action_id)
            if command.trace_id is not None:kwargs.setdefault('trace_id',command.trace_id)
        try:self._observer.record(name,owner_system='anka_execution',**kwargs)
        except Exception:pass

    def _physical_state(self,delivery:str,physical_count:int|None=None)->str:
        """Describe actual OS-input risk, independently of logical driver delivery."""
        mode=getattr(self.driver,'mode',None)
        if mode=='FAKE_ONLY':return 'NOT_SENT'
        if delivery=='NOT_SENT':return 'NOT_SENT'
        if delivery=='SEND_STARTED':return 'SEND_STARTED' if mode=='WINDOWS_PHYSICAL' else 'UNKNOWN'
        if delivery=='MAY_HAVE_SENT':return 'MAY_HAVE_SENT' if mode=='WINDOWS_PHYSICAL' or (physical_count or 0)>0 else 'UNKNOWN'
        if delivery=='SENT':return 'SENT' if (physical_count or 0)>0 or mode=='WINDOWS_PHYSICAL' else 'UNKNOWN'
        return 'UNKNOWN'
    @property
    def authority_generation(self):return self._authority_generation
    @property
    def armed(self):return self._armed
    @property
    def last_safety_fault(self):return self._last_safety_fault
    def arm(self,*,authority_generation:int):
        if type(authority_generation) is not int or authority_generation<=0:raise ExecutionServiceRejected('INVALID_INPUT_AUTHORITY_GENERATION')
        # A host-wide arbitration failure is stronger than an ordinary unresolved
        # action fence: this service instance itself is no longer trusted to own
        # physical input. Surface that root cause first and require reconstruction.
        if self._last_safety_fault is not None:raise ExecutionServiceRejected('SAFETY_FAULT_REQUIRES_NEW_SERVICE_INSTANCE')
        # Re-audit immediately before granting authority so corruption that occurs
        # after service construction cannot turn an unresolved send into an
        # apparently settled/retryable action.
        try:self.ledger.audit()
        except Exception as exc:
            self._last_safety_fault='EXECUTION_LEDGER_INTEGRITY_FAILED:'+type(exc).__name__;self._armed=False
            raise ExecutionServiceRejected(self._last_safety_fault) from exc
        if self.ledger.unresolved():raise ExecutionServiceRejected('UNRESOLVED_ACTIONS_BLOCK_ARM')
        self._authority_generation=authority_generation;self._armed=True
    def disarm(self,reason='DISARM_REQUESTED'):
        self._armed=False;self._authority_generation+=1
    def _reject(self,command,reason):
        self._record('execution.rejected',command,boundary='execution.pre_input_authorization',failure_code=reason,severity='WARNING',payload={'scope':command.authority_scope,'kind':command.kind})
        try:self.ledger.record_rejected(command,self.run_generation,self._authority_generation,reason)
        except DefinitiveExecutionLedgerRejected:pass
        return ActionOutcome(command.action_id,None,'REJECTED_NOT_SENT',(),True,(),reason)
    @staticmethod
    def _durable_outcome(action,attempt_id,*,retry_if_proven_not_sent=False):
        """Project the already-durable ledger state into the API result.

        Once SEND_STARTED is durable, asynchronous Canonical outcome evidence may
        settle the action before the synchronous driver call returns.  The caller
        must never replace that stronger durable state with a hard-coded transport
        label such as REJECTED_NOT_SENT or UNCERTAIN.
        """
        retry=bool(retry_if_proven_not_sent and action.status=='REJECTED_NOT_SENT')
        return ActionOutcome(action.action_id,attempt_id,action.status,action.evidence_ids,
                             retry,action.unresolved_obligations,action.reason)
    def _admit(self,command:ActionCommand,*,ignore_unresolved_action_id:str|None=None)->ExecutionAdmission:
        if not isinstance(command,ActionCommand):return ExecutionAdmission('REJECTED','ACTION_COMMAND_REQUIRED',None,None,None,None)
        if not self._armed:return ExecutionAdmission('REJECTED','INPUT_AUTHORITY_DISARMED',None,None,None,None)
        if command.run_id!=self.run_id:return ExecutionAdmission('REJECTED','RUN_ID_MISMATCH',None,None,None,None)
        if command.deadline_monotonic_ns is not None and self.clock_ns()>command.deadline_monotonic_ns:return ExecutionAdmission('REJECTED','ACTION_DEADLINE_EXPIRED',None,None,None,None)
        unresolved=[x for x in self.ledger.unresolved() if x.action_id!=ignore_unresolved_action_id]
        if unresolved:return ExecutionAdmission('REJECTED','UNRESOLVED_ACTION_FENCE',None,None,None,None)
        try:state=self.state_reader.current_for_action(command)
        except Exception:return ExecutionAdmission('REJECTED','LATEST_STATE_UNAVAILABLE',None,None,None,None)
        if state.account_id!=command.account_id or state.client_instance_id!=command.client_instance_id:return ExecutionAdmission('REJECTED','LATEST_STATE_SCOPE_MISMATCH',None,None,None,None)
        if state.health!='HEALTHY':return ExecutionAdmission('REJECTED','LATEST_STATE_NOT_HEALTHY',None,None,None,None)
        if state.fight_epoch!=command.fight_epoch or state.turn_epoch!=command.turn_epoch:return ExecutionAdmission('REJECTED','ACTION_EPOCH_STALE',None,None,None,None)
        if state.canonical_cursor<command.basis_canonical_cursor:return ExecutionAdmission('REJECTED','ACTION_BASIS_CURSOR_AHEAD_OF_STATE',None,None,None,None)
        if state.invalidating_change_since_basis:return ExecutionAdmission('REJECTED','ACTION_BASIS_INVALIDATED',None,None,None,None)
        if command.actor_id is not None and state.actor_id!=command.actor_id:return ExecutionAdmission('REJECTED','ACTION_ACTOR_MISMATCH',None,None,None,None)
        bad=tuple(k for k,v in state.required_proofs if v!='KNOWN')
        if bad:return ExecutionAdmission('REJECTED','REQUIRED_STATE_PROOF_UNAVAILABLE:'+','.join(bad),None,None,None,None)
        if command.authority_scope=='TURN' and command.kind in ('CAST','MOVE','END_TURN') and (state.actor_id is None or state.turn_owner_actor_id!=state.actor_id):return ExecutionAdmission('REJECTED','TURN_OWNER_NOT_PROVEN_FOR_ACTOR',None,None,None,None)
        if not validates_minimum_outcome_policy(command):return ExecutionAdmission('REJECTED','EXECUTION_OUTCOME_POLICY_UNDERSPECIFIED',None,None,None,None)
        if command.party_id is None:return ExecutionAdmission('REJECTED','PARTY_SCOPE_REQUIRED',None,None,None,None)
        try:permit=self.coordination.permit_for_action(command)
        except Exception:return ExecutionAdmission('REJECTED','COORDINATION_PERMIT_UNAVAILABLE',None,None,None,None)
        if not permit.allowed:return ExecutionAdmission('REJECTED','COORDINATION_'+permit.reason,None,None,None,None)
        if (permit.party_id,permit.account_id)!=(command.party_id,command.account_id):return ExecutionAdmission('REJECTED','COORDINATION_PERMIT_SCOPE_MISMATCH',None,None,None,None)
        if command.authority_scope=='JOIN':
            try:target_epoch=int(dict(command.semantic_target)['target_fight_epoch'])
            except (KeyError,TypeError,ValueError):return ExecutionAdmission('REJECTED','JOIN_TARGET_FIGHT_EPOCH_INVALID',None,None,None,None)
            if permit.fight_epoch!=target_epoch:return ExecutionAdmission('REJECTED','COORDINATION_PERMIT_TARGET_FIGHT_EPOCH_MISMATCH',None,None,None,None)
        elif permit.fight_epoch!=command.fight_epoch:
            return ExecutionAdmission('REJECTED','COORDINATION_PERMIT_SCOPE_MISMATCH',None,None,None,None)
        if getattr(permit,'scope','TURN')!=command.authority_scope:return ExecutionAdmission('REJECTED','COORDINATION_AUTHORITY_SCOPE_MISMATCH',None,None,None,None)
        if command.authority_scope=='TURN' and permit.turn_epoch!=command.turn_epoch:return ExecutionAdmission('REJECTED','COORDINATION_TURN_EPOCH_MISMATCH',None,None,None,None)
        if command.basis_party_generation is not None and (permit.party_generation!=command.basis_party_generation or permit.permit_generation!=command.basis_permit_generation):return ExecutionAdmission('REJECTED','COORDINATION_PERMIT_GENERATION_STALE',None,None,None,None)
        try:client=self.client.attest_for_action(command)
        except Exception:return ExecutionAdmission('REJECTED','CLIENT_ATTESTATION_UNAVAILABLE',None,None,None,None)
        if (client.account_id,client.client_instance_id)!=(command.account_id,command.client_instance_id):return ExecutionAdmission('REJECTED','CLIENT_ATTESTATION_SCOPE_MISMATCH',None,None,None,None)
        common=(client.identity_proven,client.class_proven,client.foreground_proven,client.visible_proven,client.geometry_proven,client.projection_proven)
        if not all(common):return ExecutionAdmission('REJECTED','CLIENT_PREREQUISITES_NOT_PROVEN',None,None,None,None)
        if command.kind=='CAST' and (not client.loadout_binding_proven or client.loadout_generation is None):return ExecutionAdmission('REJECTED','CAST_LOADOUT_BINDING_NOT_PROVEN',None,None,None,None)
        if client.semantic_target_fingerprint!=_target_fingerprint(command):return ExecutionAdmission('REJECTED','PROJECTION_TARGET_MISMATCH',None,None,None,None)
        try:legality=self.mechanics.validate_action(command,state)
        except Exception:return ExecutionAdmission('REJECTED','KERNEL_REVALIDATION_UNAVAILABLE',None,None,None,None)
        if legality.status!='LEGAL':return ExecutionAdmission('REJECTED','KERNEL_'+legality.status+(':'+legality.reason if legality.reason else ''),None,None,None,None)
        evid=tuple(dict.fromkeys(client.evidence_ids+permit.evidence_ids))
        return ExecutionAdmission('ADMITTED','ALL_FINAL_GUARDS_PROVEN',state,client,permit.party_generation,permit.permit_generation,evid)
    @staticmethod
    def _same_external_context(a:ExecutionAdmission,b:ExecutionAdmission)->bool:
        if a.status!='ADMITTED' or b.status!='ADMITTED':return False
        ca,cb=a.client,b.client
        assert ca and cb and a.state and b.state
        return (ca.observed_client_build,ca.pid,ca.process_created_100ns,ca.hwnd,ca.window_generation,ca.projection_generation,ca.calibration_generation,ca.loadout_generation,ca.pixel_x,ca.pixel_y,
                a.party_generation,a.permit_generation,a.state.fight_epoch,a.state.turn_epoch)==(
                cb.observed_client_build,cb.pid,cb.process_created_100ns,cb.hwnd,cb.window_generation,cb.projection_generation,cb.calibration_generation,cb.loadout_generation,cb.pixel_x,cb.pixel_y,
                b.party_generation,b.permit_generation,b.state.fight_epoch,b.state.turn_epoch)
    def submit(self,command:ActionCommand)->ActionOutcome:
        initial=self._admit(command)
        if initial.status!='ADMITTED':return self._reject(command,initial.reason)
        self._record('execution.admitted',command,boundary='execution.pre_input_authorization',payload={'scope':command.authority_scope,'kind':command.kind,'party_generation':initial.party_generation,'permit_generation':initial.permit_generation})
        try:pref,_=self.ledger.prepare(command,self.run_generation,self._authority_generation)
        except DefinitiveExecutionLedgerRejected as exc:
            reason=str(exc) or 'EXECUTION_LEDGER_PREPARE_REJECTED'
            self._record('execution.ledger_prepare_rejected',command,boundary='execution.durable_prepare',
                         severity='WARNING',failure_code=reason,payload={'scope':command.authority_scope,'kind':command.kind})
            return ActionOutcome(command.action_id,None,'REJECTED_NOT_SENT',(),True,(),reason)
        try:lease=self.arbiter.acquire(command.action_id,command.account_id,now_ns=self.clock_ns())
        except InputLeaseBusy:
            self.ledger.cancel_pre_send(command.action_id,'HOST_INPUT_LEASE_BUSY')
            self._record('execution.input_lease_rejected',command,boundary='execution.input_arbitration',
                         severity='WARNING',failure_code='HOST_INPUT_LEASE_BUSY')
            return ActionOutcome(command.action_id,None,'REJECTED_NOT_SENT',(),True,(),'HOST_INPUT_LEASE_BUSY')
        except Exception as exc:
            reason='INPUT_ARBITER_ACQUIRE_FAILED:'+type(exc).__name__
            try:self.ledger.cancel_pre_send(command.action_id,reason)
            except Exception:pass
            self._last_safety_fault=reason;self.disarm(reason)
            self._record('execution.safety_fault',command,boundary='execution.input_arbitration',severity='SAFETY',failure_code=reason)
            return ActionOutcome(command.action_id,None,'REJECTED_NOT_SENT',(),True,(),reason)
        attempt=None;driver_invoked=False
        try:
            final=self._admit(command,ignore_unresolved_action_id=command.action_id)
            if not self._same_external_context(initial,final):
                reason=final.reason if final.status!='ADMITTED' else 'EXTERNAL_CONTEXT_CHANGED_AFTER_PREPARE'
                self.ledger.cancel_pre_send(command.action_id,reason)
                self._record('execution.final_guard_rejected',command,boundary='execution.pre_input_revalidation',
                             severity='WARNING',failure_code=reason,payload={'scope':command.authority_scope,'kind':command.kind})
                return ActionOutcome(command.action_id,None,'REJECTED_NOT_SENT',(),True,(),reason)
            assert final.client is not None
            attempt=_attempt_id(command,lease);self.ledger.mark_send_started(command.action_id,attempt);self._record('execution.send_started',command,boundary='execution.external_boundary',attempt_id=attempt,severity='SAFETY',physical_input_state=self._physical_state('SEND_STARTED'),payload={'scope':command.authority_scope,'kind':command.kind})
            expected=final
            def guard():
                current=self._admit(command,ignore_unresolved_action_id=command.action_id)
                return self._same_external_context(expected,current)
            driver_invoked=True
            try:receipt=self.driver.send(command,final.client,lease,guard)
            except InputDriverFailure as exc:
                if exc.may_have_sent:
                    self._record('execution.input_may_have_sent',command,boundary='execution.external_boundary',attempt_id=attempt,severity='SAFETY',failure_code=exc.code,physical_input_state=self._physical_state('MAY_HAVE_SENT'),payload={'scope':command.authority_scope,'kind':command.kind})
                    a=self.ledger.mark_uncertain(command.action_id,exc.code);return self._durable_outcome(a,attempt)
                self._record('execution.input_not_sent',command,boundary='execution.external_boundary',attempt_id=attempt,severity='WARNING',failure_code=exc.code,physical_input_state='NOT_SENT',payload={'scope':command.authority_scope,'kind':command.kind})
                a=self.ledger.mark_not_sent(command.action_id,exc.code);return self._durable_outcome(a,attempt,retry_if_proven_not_sent=True)
            self.physical_input_count+=receipt.physical_input_count
            if receipt.delivery=='NOT_SENT':
                self._record('execution.input_not_sent',command,boundary='execution.external_boundary',attempt_id=attempt,severity='WARNING',physical_input_state='NOT_SENT',payload={'scope':command.authority_scope,'kind':command.kind,'detail':receipt.detail})
                a=self.ledger.mark_not_sent(command.action_id,receipt.detail);return self._durable_outcome(a,attempt,retry_if_proven_not_sent=True)
            if receipt.delivery=='MAY_HAVE_SENT':
                self._record('execution.input_may_have_sent',command,boundary='execution.external_boundary',attempt_id=attempt,severity='SAFETY',physical_input_state=self._physical_state('MAY_HAVE_SENT',receipt.physical_input_count),payload={'scope':command.authority_scope,'kind':command.kind,'detail':receipt.detail})
                a=self.ledger.mark_uncertain(command.action_id,receipt.detail);return self._durable_outcome(a,attempt)
            a=self.ledger.mark_sent(command.action_id,receipt.detail)
            self._record('execution.input_sent',command,boundary='execution.external_boundary',attempt_id=attempt,physical_input_state=self._physical_state('SENT',receipt.physical_input_count),payload={'scope':command.authority_scope,'kind':command.kind,'detail':receipt.detail,'physical_input_count':receipt.physical_input_count})
            return self._durable_outcome(a,attempt)
        except Exception as exc:
            if attempt is not None:
                reason='EXECUTION_EXCEPTION_AFTER_SEND_STARTED:'+type(exc).__name__
                self._record('execution.exception_after_send_started',command,boundary='execution.external_boundary',
                             attempt_id=attempt,severity='SAFETY',failure_code=reason,physical_input_state=self._physical_state('MAY_HAVE_SENT'))
                try:
                    a=self.ledger.mark_uncertain(command.action_id,reason)
                    return self._durable_outcome(a,attempt)
                except Exception as ledger_exc:
                    # SEND_STARTED is already durable whenever attempt exists. Even
                    # if the driver call itself has not yet begun, losing the ledger
                    # now means a safe NOT_SENT transition can no longer be proven.
                    prefix=('EXECUTION_LEDGER_UNAVAILABLE_AFTER_DRIVER:' if driver_invoked
                            else 'EXECUTION_LEDGER_UNAVAILABLE_AFTER_SEND_STARTED:')
                    reason=prefix+type(ledger_exc).__name__
                    self._last_safety_fault=reason;self.disarm(reason)
                    self._record('execution.safety_fault',command,boundary='execution.durable_settlement',
                                 attempt_id=attempt,severity='CRITICAL',failure_code=reason,physical_input_state=self._physical_state('MAY_HAVE_SENT'))
                    marker='exec-failsafe-'+sha256(f'{command.action_id}:{attempt}:{reason}'.encode()).hexdigest()[:32]
                    return ActionOutcome(command.action_id,attempt,'UNCERTAIN',(marker,),False,(),reason)
            reason='EXECUTION_EXCEPTION_BEFORE_SEND:'+type(exc).__name__
            try:self.ledger.cancel_pre_send(command.action_id,reason)
            except Exception:pass
            self._record('execution.exception_before_send',command,boundary='execution.external_boundary',
                         severity='ERROR',failure_code=reason,physical_input_state='NOT_SENT')
            return ActionOutcome(command.action_id,attempt,'REJECTED_NOT_SENT',(),True,(),reason)
        finally:
            try:self.arbiter.release(lease)
            except Exception as exc:
                # Losing host-wide input arbitration is a run-level safety fault.
                # Preserve the action's durable outcome, but permanently disarm
                # this service instance so no later action can bypass serialization.
                self._last_safety_fault='INPUT_ARBITER_RELEASE_FAILED:'+type(exc).__name__
                self.disarm(self._last_safety_fault)
                self._record('execution.safety_fault',command,boundary='execution.input_arbitration',
                             attempt_id=attempt,severity='CRITICAL',failure_code=self._last_safety_fault,
                             physical_input_state=self._physical_state('MAY_HAVE_SENT') if attempt is not None else 'NOT_SENT')
    def reconcile(self,action_id:str,evidence:ExecutionOutcomeEvidence)->ActionOutcome:
        # Same-instance serialization is retained as a cheap local guard, but the
        # correctness boundary is the shared SQLite ledger: settle_outcome performs
        # durable read -> correlate -> append/update under one BEGIN IMMEDIATE.
        with self._settlement_lock:
            command=self.ledger.get_command(action_id)
            a,settlement_reason,mutated=self.ledger.settle_outcome(action_id,evidence)
            if not mutated:
                if settlement_reason=='TERMINAL_ACTION_ALREADY_RESOLVED':
                    return ActionOutcome(action_id,a.attempt_id,a.status,a.evidence_ids,False,a.unresolved_obligations,settlement_reason)
                self._record('execution.outcome_ignored',command,boundary='execution.outcome_correlation',
                             attempt_id=a.attempt_id,severity='WARNING',failure_code=settlement_reason,
                             payload={'evidence_id':evidence.evidence_id,'current_status':a.status,
                                      'evidence_result':evidence.result,'evidence_cursor':evidence.canonical_cursor,
                                      'evidence_authoritative':evidence.authoritative,
                                      'evidence_proofs':list(evidence.proofs),
                                      'evidence_correlated_action_id':evidence.correlated_action_id})
                return ActionOutcome(action_id,a.attempt_id,a.status,a.evidence_ids or ('exec-ignore-'+evidence.evidence_id,),False,a.unresolved_obligations,settlement_reason)
            self._record('execution.outcome_settled',command,boundary='execution.outcome_settlement',attempt_id=a.attempt_id,severity='SETTLEMENT',payload={'status':a.status,'reason':a.reason,'evidence_id':evidence.evidence_id})
            return ActionOutcome(action_id,a.attempt_id,a.status,a.evidence_ids,False,a.unresolved_obligations,a.reason)
    def terminalize_unresolved(self,action_id:str,reason='OUTCOME_COULD_NOT_BE_RESOLVED_SAFELY')->ActionOutcome:
        with self._settlement_lock:
            command=self.ledger.get_command(action_id)
            a=self.ledger.mark_terminal_unresolved(action_id,reason)
            self._record('execution.outcome_terminal_unresolved',command,boundary='execution.outcome_settlement',
                         attempt_id=a.attempt_id,severity='SAFETY',failure_code=reason,physical_input_state=self._physical_state('MAY_HAVE_SENT'))
            return self._durable_outcome(a,a.attempt_id)
