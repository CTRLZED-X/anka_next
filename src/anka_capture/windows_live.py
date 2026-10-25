"""Optional read-only Npcap/Scapy capture adapter for Windows.

Never sends packets, never requests mouse input, never writes raw packets.
Sampled only when start is explicitly configured; live acceptance still PENDING.
"""
from __future__ import annotations
import os
import secrets
import ipaddress
from hashlib import sha256
from time import monotonic, monotonic_ns
from datetime import datetime, timezone
from typing import Callable
from threading import RLock, Condition, Thread, Event
from anka_contracts.capture import CapturePoll
from anka_capture.api import validate_ports
from anka_capture.live import BoundedSegmentQueue, LiveCaptureAudit
from anka_contracts.capture import CapturedTcpSegment


class WindowsLiveCapture:
    def __init__(self, *, interface:str|None, server_ports:tuple[int,...],
                 allowed_flows:tuple[tuple[str,int,str,int],...] = (),
                 source_generation:str|None=None, sniffer_factory=None,
                 max_segments:int=1024, max_bytes:int=4*1024*1024,
                 require_windows:bool=True, evidence_recorder=None,
                 lifecycle_timeout_seconds:float=5.0):
        validate_ports(server_ports)
        if (not isinstance(lifecycle_timeout_seconds,(int,float)) or isinstance(lifecycle_timeout_seconds,bool)
                or not 0.01<=float(lifecycle_timeout_seconds)<=30.0):
            raise ValueError('CAPTURE_LIFECYCLE_TIMEOUT_INVALID')
        self._lifecycle_timeout_seconds=float(lifecycle_timeout_seconds)
        if require_windows and os.name!='nt':raise RuntimeError('LIVE_CAPTURE_WINDOWS_REQUIRED')
        if interface is not None and (not isinstance(interface,str) or not 1<=len(interface)<=255 or interface.strip()!=interface or any(ord(ch)<32 for ch in interface)):
            raise ValueError('CAPTURE_INTERFACE_INVALID')
        self.interface=interface
        self.ports=tuple(server_ports)
        if not isinstance(allowed_flows,tuple) or len(allowed_flows)>64:
            raise ValueError('CAPTURE_FLOW_SCOPE_INVALID')
        checked=[]
        for item in allowed_flows:
            if (not isinstance(item,tuple) or len(item)!=4 or type(item[1]) is not int or type(item[3]) is not int
                    or not (1<=item[1]<=65535 and 1<=item[3]<=65535)):
                raise ValueError('CAPTURE_FLOW_SCOPE_INVALID')
            try:
                client_ip=ipaddress.ip_address(item[0].split('%',1)[0]).compressed
                server_ip=ipaddress.ip_address(item[2].split('%',1)[0]).compressed
            except (ValueError,AttributeError) as exc: raise ValueError('CAPTURE_FLOW_SCOPE_INVALID') from exc
            checked.append((client_ip,item[1],server_ip,item[3]))
        self.allowed_flows=frozenset(checked)
        self.generation=source_generation or secrets.token_hex(12)
        self.queue=BoundedSegmentQueue(source_generation=self.generation,max_segments=max_segments,max_bytes=max_bytes)
        self._flow_salt=secrets.token_bytes(32)
        self._flow_keys:dict[str,tuple[str,int,str,int]]={}
        self._max_flow_keys=4096
        self._sniffer_factory=sniffer_factory
        self._sniffer=None
        self._evidence_recorder=evidence_recorder
        self._raw_evidence_receipt=None
        self._started=False
        self._stopped=False
        self._frame_no=0
        self._rejected_frames=0
        self._unsupported_frames=0
        self._capture_interrupted=False
        # Metadata/callback state is shared between the Scapy callback thread and
        # the lifecycle/consumer thread.  The condition also makes concurrent
        # quiesce/stop callers wait for the one real sniffer shutdown to finish.
        self._state_lock=RLock()
        self._quiesce_condition=Condition(self._state_lock)
        self._starting=False
        self._quiescing=False
        self._quiesced=False
        self._quiesce_error:str|None=None
        self._secondary_cleanup_error:str|None=None
        self._active_callbacks=0

    def _ensure_factory(self):
        if self._sniffer_factory is None:
            try:
                from scapy.all import AsyncSniffer
            except ImportError as exc:
                raise RuntimeError('SCAPY_NOT_INSTALLED_OPTIONAL_CAPTURE_DEPENDENCY') from exc
            # Backend readiness is proved by the bounded AsyncSniffer start, not
            # by Scapy's mutable conf.use_pcap flag (which can be false even when
            # a usable Windows capture provider is available).
            self._sniffer_factory=AsyncSniffer

    def _stop_backend_bounded(self, sniffer, *, timeout_seconds:float,
                              thread_code:str='LIVE_CAPTURE_STOP_THREAD_FAILED',
                              timeout_code:str='LIVE_CAPTURE_STOP_TIMEOUT',
                              failure_code:str='LIVE_CAPTURE_STOP_FAILED')->tuple[str|None,BaseException|None]:
        """Attempt one backend stop without ever blocking the lifecycle indefinitely."""
        backend_error=[]
        done=Event()
        def stop_backend()->None:
            try:sniffer.stop()
            except BaseException as exc:backend_error.append(exc)
            finally:done.set()
        worker=Thread(target=stop_backend,name='anka-capture-sniffer-stop',daemon=True)
        try:worker.start()
        except Exception as exc:
            return thread_code,exc
        if not done.wait(timeout=max(0.0,float(timeout_seconds))):
            return timeout_code,None
        if backend_error:
            return failure_code,backend_error[0]
        return None,None

    def _cleanup_late_start(self, sniffer)->str|None:
        """Bounded cleanup after shutdown timed out while backend start was blocked.

        The stored quiesce error remains authoritative. This helper only records
        whether the secondary cleanup itself could be proven complete.
        """
        deadline=monotonic()+self._lifecycle_timeout_seconds
        code,_exc=self._stop_backend_bounded(
            sniffer,timeout_seconds=max(0.0,deadline-monotonic()),
            thread_code='LIVE_CAPTURE_LATE_START_STOP_THREAD_FAILED',
            timeout_code='LIVE_CAPTURE_LATE_START_STOP_TIMEOUT',
            failure_code='LIVE_CAPTURE_LATE_START_STOP_FAILED')
        if code is not None:
            return code
        with self._quiesce_condition:
            while self._active_callbacks:
                remaining=deadline-monotonic()
                if remaining<=0:
                    return 'LIVE_CAPTURE_LATE_START_CALLBACK_DRAIN_TIMEOUT'
                self._quiesce_condition.wait(timeout=remaining)
        # The original start/quiesce timeout should already have marked evidence
        # incomplete. If that marking itself failed, never seal the recorder:
        # a clean-looking artifact would be stronger than the evidence permits.
        with self._state_lock:
            prior_secondary=self._secondary_cleanup_error
        if prior_secondary=='LIVE_CAPTURE_INTERRUPT_MARK_FAILED':
            return prior_secondary
        if self._evidence_recorder is not None and self._raw_evidence_receipt is None:
            try:
                receipt=self._evidence_recorder.close()
            except Exception:
                return 'LIVE_CAPTURE_LATE_START_EVIDENCE_SEAL_FAILED'
            with self._state_lock:
                if self._raw_evidence_receipt is None:
                    self._raw_evidence_receipt=receipt
        return None

    def _ingest_reserved_fields(self, *, frame_no:int, src:str,dst:str,sport:int,dport:int,seq:int,
                                flags:int,payload:bytes, observed_utc:str|None=None,
                                observed_monotonic_ns:int|None=None):
        """Validate and enqueue one frame whose lifecycle admission is already fixed."""
        try:
            if not (isinstance(src,str) and isinstance(dst,str) and
                    type(sport) is int and type(dport) is int and 0<=sport<=65535 and 0<=dport<=65535):
                raise ValueError('INVALID_ENDPOINT')
            try:
                src=ipaddress.ip_address(src.split('%',1)[0]).compressed
                dst=ipaddress.ip_address(dst.split('%',1)[0]).compressed
            except (ValueError,AttributeError) as exc:
                raise ValueError('INVALID_ENDPOINT') from exc
            direct=(src,sport,dst,dport);reverse=(dst,dport,src,sport)
            if self.allowed_flows:
                if direct in self.allowed_flows:
                    direction='client_to_server';key=direct
                elif reverse in self.allowed_flows:
                    direction='server_to_client';key=reverse
                else:
                    raise ValueError('FLOW_OUTSIDE_DISCOVERED_SCOPE')
            else:
                if (sport in self.ports)==(dport in self.ports):
                    raise ValueError('PORT_DIRECTION_AMBIGUOUS')
                direction='server_to_client' if sport in self.ports else 'client_to_server'
                key=reverse if direction=='server_to_client' else direct
            if type(seq) is not int or not 0<=seq<2**32 or type(flags) is not int or not 0<=flags<=255 or not isinstance(payload,bytes):
                raise ValueError('TCP_FRAME_INVALID')
            if not payload and not (flags & 0x07):return True
            token=sha256(self._flow_salt+repr(key).encode('utf8')).hexdigest()[:24]
            with self._state_lock:
                if token not in self._flow_keys and len(self._flow_keys)>=self._max_flow_keys:
                    raise ValueError('CAPTURE_FLOW_CAPACITY_EXCEEDED')
                self._flow_keys[token]=key
            return self.queue.push(CapturedTcpSegment(token,direction,seq,payload,frame_no,flags,
                observed_utc or datetime.now(timezone.utc).isoformat(), observed_monotonic_ns if observed_monotonic_ns is not None else monotonic_ns(), 'LIVE_CALLBACK'))
        except (ValueError,TypeError):
            with self._state_lock:self._rejected_frames+=1
            self.queue.push(None)  # count as observable loss, not silent skip
            return False

    def ingest_fields(self, *, src:str,dst:str,sport:int,dport:int,seq:int,
                      flags:int,payload:bytes, observed_utc:str|None=None, observed_monotonic_ns:int|None=None):
        """Direct ingress contract used by deterministic tests and adapters.

        Direct callers must cross the lifecycle fence at the moment the frame
        number is reserved. Scapy callbacks use the private reserved path after
        their callback-entry lease has already crossed the same fence.
        """
        with self._state_lock:
            if self._stopped or not self._started:return False
            self._frame_no+=1
            frame_no=self._frame_no
        return self._ingest_reserved_fields(frame_no=frame_no,src=src,dst=dst,sport=sport,dport=dport,
            seq=seq,flags=flags,payload=payload,observed_utc=observed_utc,
            observed_monotonic_ns=observed_monotonic_ns)

    def ingest_packet(self, packet)->None:
        """Scapy callback. Keep imports local; no dependency in offline runs.

        Callback entry is lifecycle-fenced and counted.  Quiesce first prevents new
        callbacks, then proves every callback that crossed this fence has returned
        before raw evidence can be sealed.
        """
        with self._quiesce_condition:
            if self._stopped or not self._started:
                return
            self._active_callbacks+=1
        try:
            from scapy.layers.inet import IP, TCP
            try:
                from scapy.layers.inet6 import IPv6
            except ImportError:
                IPv6=None
            has_v4=bool(packet.haslayer(IP))
            has_v6=bool(IPv6 is not None and packet.haslayer(IPv6))
            if not packet.haslayer(TCP) or not (has_v4 or has_v6):
                with self._state_lock:self._unsupported_frames+=1
                self.queue.push(None)
                if self._evidence_recorder is not None:
                    self._evidence_recorder.mark_incomplete()
                return
            ip=packet[IP] if has_v4 else packet[IPv6];tcp=packet[TCP]
            # This callback already crossed the lifecycle fence above. Reserve
            # its frame ordinal without re-checking _stopped: quiesce may have
            # begun meanwhile, but it must wait for this admitted callback.
            with self._state_lock:
                self._frame_no+=1
                frame_no=self._frame_no
            accepted=self._ingest_reserved_fields(frame_no=frame_no,src=str(ip.src),dst=str(ip.dst),
                               sport=int(tcp.sport),dport=int(tcp.dport),seq=int(tcp.seq),
                               flags=int(tcp.flags),payload=bytes(tcp.payload))
            if self._evidence_recorder is not None:
                if not accepted:
                    self._evidence_recorder.mark_incomplete()
                # Some Npcap interfaces expose IP packets without Ethernet. A
                # synthetic L2 header is explicitly non-origin attestation.
                from scapy.layers.l2 import Ether
                ethertype=b'\x08\x00' if has_v4 else b'\x86\xdd'
                frame=(bytes(packet[Ether]) if packet.haslayer(Ether) else
                       b'\x00'*12 + ethertype + bytes(ip))
                if not self._evidence_recorder.record(frame):
                    self.queue.push(None)  # capture completeness is now uncertain
        except Exception:
            # Unsupported frames or parser exceptions are recorded as a loss,
            # not ignored (including selected-port IPv6 frames).
            with self._state_lock:self._rejected_frames+=1
            self.queue.push(None)
            if self._evidence_recorder is not None:
                self._evidence_recorder.mark_incomplete()
        finally:
            with self._quiesce_condition:
                self._active_callbacks-=1
                self._quiesce_condition.notify_all()

    def mark_capture_interrupted(self)->None:
        """Seal an abnormal observation window as incomplete, at most once.

        A normally drained sample may still be uncertified, but a failed poll,
        consumer, or sniffer shutdown must never leave a zero-gap raw artifact.
        This deliberately does not contain exception details or private data.
        """
        recorder=None
        with self._state_lock:
            if not self._capture_interrupted:
                self._capture_interrupted=True
                recorder=self._evidence_recorder
        if recorder is not None:
            recorder.mark_incomplete()

    def start(self)->None:
        with self._quiesce_condition:
            if self._started or self._starting or self._stopped:raise RuntimeError('CAPTURE_ALREADY_STARTED_OR_STOPPED')
            self._starting=True
            # Mark started before AsyncSniffer.start: a callback can be scheduled
            # immediately by a test/backend. Quiesce waits for _starting to clear.
            self._started=True
        if self.allowed_flows:
            terms=[]
            for client_ip,client_port,server_ip,server_port in sorted(self.allowed_flows):
                terms.append(f'(src host {client_ip} and src port {client_port} and dst host {server_ip} and dst port {server_port})')
                terms.append(f'(src host {server_ip} and src port {server_port} and dst host {client_ip} and dst port {client_port})')
            expression='tcp and ('+' or '.join(terms)+')'
        else:
            expression='tcp and ('+' or '.join('port '+str(p) for p in self.ports)+')'
        sniffer=None
        try:
            self._ensure_factory()
            sniffer=self._sniffer_factory(iface=self.interface,filter=expression,
                                               store=False,prn=self.ingest_packet)
            with self._state_lock:self._sniffer=sniffer
            sniffer.start()
        except Exception as exc:
            with self._quiesce_condition:
                authoritative=self._quiesce_error if self._stopped and self._quiesce_error is not None else None
                self._starting=False
                if authoritative is None:
                    self._started=False
                    self._stopped=True
                    self._quiesced=True
                self._quiesce_condition.notify_all()
            if authoritative is not None:
                # Shutdown already won while start() was blocked. Preserve that
                # exact failure even if backend start now fails or cleanup fails.
                secondary=self._cleanup_late_start(sniffer) if sniffer is not None else None
                with self._state_lock:self._secondary_cleanup_error=secondary
                raise RuntimeError(authoritative) from exc
            self.queue.close()
            if self._evidence_recorder is not None:
                try:
                    self.mark_capture_interrupted()
                    self._raw_evidence_receipt=self._evidence_recorder.close()
                except Exception:
                    pass  # original startup failure remains authoritative
            # Preserve only exact internal dependency tokens. Arbitrary backend
            # exception text must never cross into startup diagnostics.
            code=(str(exc) if isinstance(exc,RuntimeError) and
                  str(exc)=='SCAPY_NOT_INSTALLED_OPTIONAL_CAPTURE_DEPENDENCY'
                  else 'LIVE_CAPTURE_START_FAILED')
            raise RuntimeError(code) from exc

        with self._quiesce_condition:
            authoritative=self._quiesce_error if self._stopped and self._quiesce_error is not None else None
            self._starting=False
            self._quiesce_condition.notify_all()
        if authoritative is not None:
            # A quiesce timeout can occur while sniffer.start() is blocked. Once
            # start finally returns, actively stop that backend through a fresh
            # bounded cleanup window; never convert the original timeout to success.
            secondary=self._cleanup_late_start(sniffer)
            with self._state_lock:self._secondary_cleanup_error=secondary
            raise RuntimeError(authoritative)

    def poll(self, *,max_segments:int,timeout_seconds:float):
        if not self._started:raise RuntimeError('LIVE_CAPTURE_NOT_STARTED')
        return self.queue.poll(max_segments=max_segments,timeout_seconds=timeout_seconds)

    def quiesce(self)->None:
        """Bounded producer shutdown; evidence is sealable only on success.

        No lifecycle condition wait and no backend ``stop()`` call may block the
        operator indefinitely.  A timeout is evidence loss and fails closed; it
        never pretends that callbacks have stopped.
        """
        deadline=monotonic()+self._lifecycle_timeout_seconds
        with self._quiesce_condition:
            while self._starting:
                remaining=deadline-monotonic()
                if remaining<=0:
                    self._stopped=True;self._quiesce_error='LIVE_CAPTURE_START_QUIESCE_TIMEOUT'
                    self.queue.close()
                    try:self.mark_capture_interrupted()
                    except Exception:
                        # Preserve the lifecycle timeout as authoritative while
                        # recording that the raw evidence could not be safely marked.
                        self._secondary_cleanup_error='LIVE_CAPTURE_INTERRUPT_MARK_FAILED'
                    raise RuntimeError(self._quiesce_error)
                self._quiesce_condition.wait(timeout=remaining)
            if self._quiesced:return
            if self._quiesce_error is not None:raise RuntimeError(self._quiesce_error)
            if self._quiescing:
                while self._quiescing and not self._quiesced and self._quiesce_error is None:
                    remaining=deadline-monotonic()
                    if remaining<=0:raise RuntimeError('LIVE_CAPTURE_QUIESCE_WAIT_TIMEOUT')
                    self._quiesce_condition.wait(timeout=remaining)
                if self._quiesced:return
                raise RuntimeError(self._quiesce_error or 'LIVE_CAPTURE_QUIESCE_FAILED')
            self._quiescing=True
            self._stopped=True  # callback-entry fence: no new callback may cross it
            sniffer=self._sniffer
            started=self._started

        error_code=None
        backend_exc=None
        if not started:
            self.mark_capture_interrupted()
        elif sniffer is not None:
            error_code,backend_exc=self._stop_backend_bounded(
                sniffer,timeout_seconds=max(0.0,deadline-monotonic()))

        # Even after backend stop returns, prove callbacks that entered before the
        # fence have completed.  This protects the raw evidence recorder from being
        # finalized while a callback can still mutate it.
        if error_code is None:
            with self._quiesce_condition:
                while self._active_callbacks:
                    remaining=deadline-monotonic()
                    if remaining<=0:
                        error_code='LIVE_CAPTURE_CALLBACK_DRAIN_TIMEOUT';break
                    self._quiesce_condition.wait(timeout=remaining)

        if error_code is not None:
            try:self.mark_capture_interrupted()
            except Exception:
                with self._state_lock:
                    if self._secondary_cleanup_error is None:
                        self._secondary_cleanup_error='LIVE_CAPTURE_INTERRUPT_MARK_FAILED'
        self.queue.close()
        with self._quiesce_condition:
            self._quiescing=False
            if error_code is None:self._quiesced=True
            else:self._quiesce_error=error_code
            self._quiesce_condition.notify_all()
        if error_code is not None:
            raise RuntimeError(error_code) from backend_exc

    def stop(self)->None:
        """Idempotently quiesce and seal evidence only after proven shutdown."""
        self.quiesce()
        # A failed/timeout quiesce raises above, deliberately leaving raw evidence
        # partial/unsealed because a callback may still exist.
        with self._state_lock:
            if self._evidence_recorder is not None and self._raw_evidence_receipt is None:
                self._raw_evidence_receipt=self._evidence_recorder.close()

    def flow_keys_for_attribution(self)->dict[str,tuple[str,int,str,int]]:
        """In-memory only; do NOT serialize, expose to diagnostics or write ZIPs."""
        with self._state_lock:return self._flow_keys.copy()

    def safe_stats(self)->dict:
        stats=self.queue.stats()
        with self._state_lock:
            rejected=self._rejected_frames;unsupported=self._unsupported_frames;raw=self._raw_evidence_receipt
            lifecycle_error=self._quiesce_error;secondary_cleanup=self._secondary_cleanup_error
        return {'accepted_segments':stats.accepted_total,'queued_segments':stats.queued_segments,
                'queue_drop_total':stats.dropped_total,'invalid_frames':stats.invalid_total,
                'rejected_frames':rejected,
                'unsupported_frames':unsupported,
                'driver_loss_visibility':'UNKNOWN','account_binding_verified':False,
                'physical_input_sent':False,
                # Stable internal lifecycle codes only; no backend exception text.
                'lifecycle_error':lifecycle_error,
                'secondary_cleanup_error':secondary_cleanup,
                'raw_evidence':raw}


def capture_bounded_sample(*,interface:str|None, server_ports:tuple[int,...],
                           allowed_flows:tuple[tuple[str,int,str,int],...] = (),
                           duration_seconds:int=10, observer=None,
                           factory=None,require_windows:bool=True,
                           source=None, on_poll:Callable[[CapturePoll],None]|None=None)->dict:
    if type(duration_seconds) is not int or not 1<=duration_seconds<=60:
        raise ValueError('CAPTURE_DURATION_INVALID')
    live=source or WindowsLiveCapture(interface=interface,server_ports=server_ports,allowed_flows=allowed_flows,
                                        sniffer_factory=factory,require_windows=require_windows)
    audit=LiveCaptureAudit()
    try:
        live.start()
        deadline=monotonic_ns()+duration_seconds*1_000_000_000
        while monotonic_ns()<deadline:
            interval=min(.25,max(0,(deadline-monotonic_ns())/1e9))
            poll=live.poll(max_segments=256,timeout_seconds=interval)
            audit.observe(poll)
            if on_poll is not None:on_poll(poll)
        # The sniffer is stopped, but the recorder stays open until all
        # buffered observations and their consumers have been audited. If a
        # final poll fails, the P65 interruption seal can still be persisted.
        quiesce=getattr(live,'quiesce',None)
        if callable(quiesce):
            quiesce()
        else:
            live.stop()  # legacy/test source without split shutdown
        # WindowsLiveCapture's queue is capped at 4096 segments and poll drains
        # up to 256 at a time. After quiesce there can be no new producer, so a
        # healthy source must exhaust within a small bounded number of polls.
        # Keep margin for one drop-only/exhaustion observation; never hang start
        # forever if a source violates its shutdown contract.
        for _drain_poll in range(20):
            poll=live.poll(max_segments=256,timeout_seconds=0)
            audit.observe(poll)
            if on_poll is not None:on_poll(poll)
            if poll.exhausted:break
        else:
            raise RuntimeError('CAPTURE_FINAL_DRAIN_DID_NOT_EXHAUST')
    except BaseException as primary_exc:
        # A failed read or downstream consumer can cut the observation window
        # short. The primary failure is diagnostically more important than any
        # later best-effort evidence-marking or shutdown failure, so secondary
        # cleanup faults are attached as notes instead of replacing it.
        mark=getattr(live,'mark_capture_interrupted',None)
        if callable(mark):
            try:
                mark()
            except BaseException as mark_exc:
                primary_exc.add_note('CAPTURE_INTERRUPT_MARK_FAILED:'+type(mark_exc).__name__)
        try:
            live.stop()
        except BaseException as stop_exc:
            primary_exc.add_note('CAPTURE_CLEANUP_FAILED:'+type(stop_exc).__name__)
        raise
    else:
        # On the successful path, cleanup failure is itself the authoritative
        # failure and must remain visible to the caller.
        live.stop()
    receipt=audit.receipt()
    receipt['capture_source']='WINDOWS_NPCAP_EXPERIMENTAL'
    receipt['live_capture_equivalent']=False
    receipt['driver_loss_visibility']='UNKNOWN'
    receipt['host_acceptance']='PENDING'
    receipt.update(live.safe_stats())
    if observer is not None:
        try:
            observer.record('capture.live_sample_completed',boundary='capture.read_only_live',
                            payload=receipt)
        except Exception:
            # Observability is never capture authority. The bounded sample and
            # its integrity receipt remain authoritative when a diagnostic sink
            # is unavailable or faulty.
            pass
    return receipt
