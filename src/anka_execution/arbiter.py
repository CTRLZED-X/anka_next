"""Host-wide M11 physical-input arbiter."""
from __future__ import annotations
from hashlib import sha256
from threading import Lock
import time
from anka_contracts.execution import InputLease

class InputLeaseBusy(RuntimeError):pass
class InputLeaseInvalid(RuntimeError):pass

class HostInputArbiter:
    """One injected instance serializes every focus/mouse/keyboard external boundary."""
    def __init__(self):
        self._guard=Lock();self._active:InputLease|None=None;self._epoch=0
    @property
    def active(self)->InputLease|None:
        with self._guard:return self._active
    def acquire(self,action_id:str,account_id:str,*,now_ns:int|None=None)->InputLease:
        now=time.monotonic_ns() if now_ns is None else now_ns
        with self._guard:
            if self._active is not None:raise InputLeaseBusy('HOST_INPUT_LEASE_BUSY')
            self._epoch+=1
            lid='lease-'+sha256(f'{self._epoch}:{action_id}:{account_id}:{now}'.encode()).hexdigest()[:32]
            self._active=InputLease(lid,self._epoch,action_id,account_id,now)
            return self._active
    def release(self,lease:InputLease)->None:
        with self._guard:
            if self._active is None or self._active!=lease:raise InputLeaseInvalid('INPUT_LEASE_NOT_CURRENT')
            self._active=None
