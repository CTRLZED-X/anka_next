"""Windows pointer driver with an evidence-bound external-input transaction.

Importing this module does not enable physical input.  The production driver can
only be constructed on Windows with an explicitly enabled, exact-build action
scope that is bound to the current release, effective config, Q12 acceptance
receipt, and run generation.  The pure ``PointerTransaction`` remains separately
testable with a fake API so Q7 can verify mid-click focus/context loss without
issuing OS input.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import json,os
from anka_contracts.action import ActionCommand
from anka_contracts.execution import DriverSendReceipt,ExecutionClientAttestation,InputLease


def _hash64(value:str|None)->bool:
    return (type(value) is str and len(value)==64 and
            all(c in '0123456789abcdef' for c in value))


@dataclass(frozen=True,slots=True)
class WindowsActionScopeEnablement:
    scope_id:str
    observed_client_build:str
    allowed_kinds:frozenset[str]
    enabled:bool=False
    release_manifest_sha256:str|None=None
    effective_config_sha256:str|None=None
    acceptance_receipt_sha256:str|None=None
    run_id:str|None=None
    run_generation:int|None=None

    def __post_init__(self):
        if (not self.scope_id.startswith('actionscope-') or not self.observed_client_build or
                not self.allowed_kinds or any(type(k) is not str or not k for k in self.allowed_kinds)):
            raise ValueError('INVALID_WINDOWS_ACTION_SCOPE')
        # Disabled scope descriptors may be used by offline tests without live
        # evidence.  Enabling is deliberately impossible with only a boolean.
        if self.enabled:
            if not all(_hash64(x) for x in (self.release_manifest_sha256,
                                            self.effective_config_sha256,
                                            self.acceptance_receipt_sha256)):
                raise ValueError('WINDOWS_ACTION_SCOPE_EVIDENCE_HASHES_REQUIRED')
            if type(self.run_id) is not str or not self.run_id.startswith('run-'):
                raise ValueError('WINDOWS_ACTION_SCOPE_RUN_REQUIRED')
            if type(self.run_generation) is not int or self.run_generation<=0:
                raise ValueError('WINDOWS_ACTION_SCOPE_RUN_GENERATION_REQUIRED')


class WindowsInputDisabled(RuntimeError):pass


class _CtypesPointerApi:
    def __init__(self):
        import ctypes
        self._user32=ctypes.windll.user32
    def set_cursor(self,x:int,y:int)->bool:
        return bool(self._user32.SetCursorPos(x,y))
    def left_down(self)->bool:
        self._user32.mouse_event(0x0002,0,0,0,0);return True
    def left_up(self)->bool:
        self._user32.mouse_event(0x0004,0,0,0,0);return True


class PointerTransaction:
    """One pointer/click transaction with guard checks around every dangerous edge."""
    def __init__(self,api):self.api=api
    def execute(self,action_id:str,x:int,y:int,guard)->DriverSendReceipt:
        if not guard():return DriverSendReceipt(action_id,'NOT_SENT',0,'FINAL_GUARD_REJECTED_BEFORE_POINTER_MOVE')
        try:
            moved=bool(self.api.set_cursor(x,y))
        except Exception:
            # The native pointer API has already been invoked.  An exception cannot
            # prove that the cursor did not move before control returned to Python,
            # so this boundary is ambiguous and must never become retryable NOT_SENT.
            return DriverSendReceipt(action_id,'MAY_HAVE_SENT',1,'SET_CURSOR_DELIVERY_AMBIGUOUS')
        if not moved:return DriverSendReceipt(action_id,'NOT_SENT',0,'SET_CURSOR_FAILED_BEFORE_CLICK')
        # Cursor motion is an external side effect.  If context changes now we do
        # not click, but remain conservative about retrying the whole physical action.
        if not guard():return DriverSendReceipt(action_id,'MAY_HAVE_SENT',1,'GUARD_CHANGED_AFTER_POINTER_MOVE')

        down_attempted=False
        up_attempted=False
        try:
            down_attempted=True
            if not bool(self.api.left_down()):
                # A false return cannot prove that button-down did not occur. Best
                # effort release avoids leaving the host pointer logically held.
                try:
                    up_attempted=True;self.api.left_up()
                finally:
                    return DriverSendReceipt(action_id,'MAY_HAVE_SENT',2,'LEFT_DOWN_DELIVERY_AMBIGUOUS')
            if not guard():
                try:
                    up_attempted=True;self.api.left_up()
                finally:
                    return DriverSendReceipt(action_id,'MAY_HAVE_SENT',3,'GUARD_CHANGED_AFTER_MOUSE_DOWN')
            up_attempted=True
            if not bool(self.api.left_up()):
                return DriverSendReceipt(action_id,'MAY_HAVE_SENT',3,'LEFT_UP_DELIVERY_AMBIGUOUS')
            return DriverSendReceipt(action_id,'SENT',3,'WINDOWS_SPLIT_CLICK_API_ACCEPTED')
        except Exception:
            # If down may have happened, best-effort release before returning an
            # ambiguous result.  Never classify an exception after down as NOT_SENT.
            if down_attempted and not up_attempted:
                try:self.api.left_up()
                except Exception:pass
            return DriverSendReceipt(action_id,'MAY_HAVE_SENT',2 if down_attempted else 1,'WINDOWS_CLICK_BOUNDARY_EXCEPTION')


class WindowsPointerInputDriver:
    mode='WINDOWS_PHYSICAL'
    def __init__(self,enablement:WindowsActionScopeEnablement,*,
                 current_release_manifest_sha256:str|None=None,
                 current_config_sha256:str|None=None,
                 current_acceptance_receipt_sha256:str|None=None,
                 current_run_id:str|None=None,
                 current_run_generation:int|None=None):
        self.enablement=enablement
        if not enablement.enabled:raise WindowsInputDisabled('WINDOWS_INPUT_SCOPE_DISABLED')
        if os.name!='nt':raise WindowsInputDisabled('WINDOWS_INPUT_REQUIRES_WINDOWS')
        if not (_hash64(current_release_manifest_sha256) and _hash64(current_config_sha256) and
                _hash64(current_acceptance_receipt_sha256)):
            raise WindowsInputDisabled('WINDOWS_INPUT_CURRENT_EVIDENCE_HASHES_REQUIRED')
        if (enablement.release_manifest_sha256!=current_release_manifest_sha256 or
                enablement.effective_config_sha256!=current_config_sha256 or
                enablement.acceptance_receipt_sha256!=current_acceptance_receipt_sha256):
            raise WindowsInputDisabled('WINDOWS_INPUT_SCOPE_EVIDENCE_MISMATCH')
        if (current_run_id!=enablement.run_id or current_run_generation!=enablement.run_generation):
            raise WindowsInputDisabled('WINDOWS_INPUT_SCOPE_RUN_MISMATCH')
        self._transaction=PointerTransaction(_CtypesPointerApi())
    def send(self,command:ActionCommand,client:ExecutionClientAttestation,lease:InputLease,guard):
        if command.kind not in self.enablement.allowed_kinds:raise WindowsInputDisabled('ACTION_KIND_NOT_ACCEPTED_IN_SCOPE')
        if command.run_id!=self.enablement.run_id:raise WindowsInputDisabled('ACTION_SCOPE_RUN_MISMATCH')
        if (lease.action_id,lease.account_id)!=(command.action_id,command.account_id):
            raise WindowsInputDisabled('ACTION_SCOPE_INPUT_LEASE_MISMATCH')
        if (client.account_id,client.client_instance_id)!=(command.account_id,command.client_instance_id):
            raise WindowsInputDisabled('ACTION_SCOPE_CLIENT_MISMATCH')
        if client.observed_client_build!=self.enablement.observed_client_build:raise WindowsInputDisabled('ACTION_SCOPE_BUILD_MISMATCH')
        proofs=(client.identity_proven,client.class_proven,client.foreground_proven,client.visible_proven,
                client.geometry_proven,client.projection_proven)
        if not all(proofs):raise WindowsInputDisabled('ACTION_SCOPE_CLIENT_PROOFS_MISSING')
        if command.kind=='CAST' and (not client.loadout_binding_proven or client.loadout_generation is None):
            raise WindowsInputDisabled('ACTION_SCOPE_LOADOUT_PROOF_MISSING')
        target=sha256(json.dumps(list(command.semantic_target),sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if client.semantic_target_fingerprint!=target:raise WindowsInputDisabled('ACTION_SCOPE_TARGET_MISMATCH')
        return self._transaction.execute(command.action_id,client.pixel_x,client.pixel_y,guard)
