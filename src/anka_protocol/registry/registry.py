"""Explicit exact-build adapter registry and promotion boundary."""
from __future__ import annotations
from dataclasses import dataclass, replace
from typing import Callable
from threading import RLock
from anka_contracts.protocol import AdapterReleaseDescriptor

_ORDER=('STAGED','STRUCTURALLY_VALID','REPLAY_CERTIFIED','OBSERVATION_CERTIFIED','ACTION_SCOPED_CERTIFIED','ACTIVE')
class ProtocolAdapterNotFound(LookupError): pass
class ProtocolActivationRejected(RuntimeError): pass

@dataclass(frozen=True,slots=True)
class RegisteredAdapter:
    descriptor: AdapterReleaseDescriptor
    factory: Callable[...,object]

class ProtocolRegistry:
    def __init__(self):
        self._entries:dict[str,RegisteredAdapter]={}; self._active_by_build:dict[str,str]={}; self._lock=RLock()
    def register(self,descriptor:AdapterReleaseDescriptor,factory:Callable[...,object])->None:
        with self._lock:
            if descriptor.adapter_release_id in self._entries: raise ValueError('PROTOCOL_ADAPTER_ALREADY_REGISTERED')
            if not callable(factory): raise TypeError('PROTOCOL_ADAPTER_FACTORY_REQUIRED')
            # Merely registering even an accidentally ACTIVE descriptor must not activate it.
            if descriptor.lifecycle=='ACTIVE': raise ValueError('PROTOCOL_REGISTER_ACTIVE_FORBIDDEN')
            self._entries[descriptor.adapter_release_id]=RegisteredAdapter(descriptor,factory)
    def descriptor(self,release_id:str)->AdapterReleaseDescriptor:
        with self._lock:
            try:return self._entries[release_id].descriptor
            except KeyError as exc: raise ProtocolAdapterNotFound(release_id) from exc
    def releases(self)->tuple[AdapterReleaseDescriptor,...]:
        with self._lock:
            return tuple(self._entries[k].descriptor for k in sorted(self._entries))
    def promote(self,release_id:str,target:str,*,evidence_ok:bool)->AdapterReleaseDescriptor:
        with self._lock:
            row=self._entries.get(release_id)
            if row is None: raise ProtocolAdapterNotFound(release_id)
            current=row.descriptor.lifecycle
            if current in ('QUARANTINED','RETIRED'): raise ProtocolActivationRejected('PROTOCOL_TERMINAL_RELEASE')
            if target not in _ORDER or current not in _ORDER: raise ProtocolActivationRejected('PROTOCOL_PROMOTION_INVALID')
            if _ORDER.index(target)!=_ORDER.index(current)+1: raise ProtocolActivationRejected('PROTOCOL_PROMOTION_MUST_BE_STEPWISE')
            if not evidence_ok: raise ProtocolActivationRejected('PROTOCOL_PROMOTION_EVIDENCE_REQUIRED')
            if target=='ACTIVE': raise ProtocolActivationRejected('PROTOCOL_USE_ACTIVATE_METHOD')
            desc=replace(row.descriptor,lifecycle=target)
            self._entries[release_id]=RegisteredAdapter(desc,row.factory);return desc
    def quarantine(self,release_id:str)->AdapterReleaseDescriptor:
        with self._lock:
            row=self._entries.get(release_id)
            if row is None: raise ProtocolAdapterNotFound(release_id)
            desc=replace(row.descriptor,lifecycle='QUARANTINED')
            self._entries[release_id]=RegisteredAdapter(desc,row.factory)
            if self._active_by_build.get(desc.observed_client_build)==release_id:self._active_by_build.pop(desc.observed_client_build,None)
            return desc
    def activate(self,release_id:str,*,physical_input_disarmed:bool,unresolved_may_have_sent:bool,fresh_connection_generation:bool)->AdapterReleaseDescriptor:
        with self._lock:
            row=self._entries.get(release_id)
            if row is None: raise ProtocolAdapterNotFound(release_id)
            d=row.descriptor
            if d.lifecycle!='ACTION_SCOPED_CERTIFIED': raise ProtocolActivationRejected('PROTOCOL_ACTION_SCOPE_CERTIFICATION_REQUIRED')
            if not physical_input_disarmed: raise ProtocolActivationRejected('PROTOCOL_PROMOTION_REQUIRES_DISARM')
            if unresolved_may_have_sent: raise ProtocolActivationRejected('PROTOCOL_UNRESOLVED_SEND_BLOCKS_PROMOTION')
            if not fresh_connection_generation: raise ProtocolActivationRejected('PROTOCOL_FRESH_CONNECTION_REQUIRED')
            existing=self._active_by_build.get(d.observed_client_build)
            if existing and existing!=release_id: raise ProtocolActivationRejected('PROTOCOL_BUILD_ALREADY_HAS_ACTIVE_RELEASE')
            desc=replace(d,lifecycle='ACTIVE')
            self._entries[release_id]=RegisteredAdapter(desc,row.factory);self._active_by_build[d.observed_client_build]=release_id
            return desc
    def select_active_exact(self,observed_client_build:str,**factory_kwargs):
        with self._lock:
            release=self._active_by_build.get(observed_client_build)
            if release is None: raise ProtocolAdapterNotFound('PROTOCOL_NO_EXACT_ACTIVE_ADAPTER')
            row=self._entries[release]
            if row.descriptor.observed_client_build!=observed_client_build or row.descriptor.lifecycle!='ACTIVE': raise ProtocolAdapterNotFound('PROTOCOL_ACTIVE_INDEX_INVALID')
            return row.factory(**factory_kwargs)
