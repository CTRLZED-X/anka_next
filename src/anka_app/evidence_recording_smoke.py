"""Quick deterministic P64 evidence writer proof in normal offline preflight."""
from __future__ import annotations
import struct
from tempfile import TemporaryDirectory
from pathlib import Path


def evidence_recording_smoke() -> dict:
    from anka_capture.evidence_recording import ConsentedPcapngRecorder
    from anka_capture.api import inspect_pcapng, CaptureRejected
    ip=bytearray(20)
    ip[0]=0x45;ip[2:4]=(44).to_bytes(2,'big')
    ip[8]=64;ip[9]=6
    ip[12:16]=bytes((192,0,2,1));ip[16:20]=bytes((198,51,100,2))
    tcp=bytearray(20)
    tcp[:4]=struct.pack('!HH',51000,40400)
    tcp[12]=0x50;tcp[13]=0x18
    frame=bytes(12)+b'\x08\x00'+bytes(ip)+bytes(tcp)+b'TEST'
    with TemporaryDirectory() as tmp:
        directory=Path(tmp)
        a=ConsentedPcapngRecorder(directory,server_ports=(40400,))
        if not a.record(frame):raise RuntimeError('P64_RECORDING_SMOKE_UNEXPECTED_REJECTION')
        r=a.close()
        parsed=inspect_pcapng(a.final_path,server_ports=(40400,))
        if (parsed.selected_segments != 1 or parsed.source_sha256 != r['sha256'] or
                parsed.live_capture_equivalent or r['driver_loss_visibility']!='UNKNOWN'):
            raise RuntimeError('P64_RECORDING_SMOKE_ROUNDTRIP_FAILED')
        b=ConsentedPcapngRecorder(directory,server_ports=(40400,))
        b.record(frame);b.mark_incomplete();b.close()
        try:inspect_pcapng(b.final_path,server_ports=(40400,))
        except CaptureRejected:pass
        else:raise RuntimeError('P64_RECORDING_SMOKE_LOSS_NOT_DETECTED')
        # P65: abort the observation window after a real file record.
        # A failed downstream poll must be durably visible as PCAPNG loss.
        from anka_capture.windows_live import WindowsLiveCapture,capture_bounded_sample
        class SyntheticSniffer:
            def __init__(self,**_):pass
            def start(self):pass
            def stop(self):pass
        c=ConsentedPcapngRecorder(directory,server_ports=(40400,))
        if not c.record(frame):raise RuntimeError('P65_ABORT_SMOKE_FRAME_REJECTED')
        live=WindowsLiveCapture(interface='synthetic',server_ports=(40400,),
                                require_windows=False,sniffer_factory=SyntheticSniffer,
                                evidence_recorder=c)
        def failed_poll(**_):raise RuntimeError('P65_SYNTHETIC_POLL_INTERRUPTION')
        live.poll=failed_poll
        try:
            capture_bounded_sample(interface='synthetic',server_ports=(40400,),
                                   duration_seconds=1,source=live,require_windows=False)
        except RuntimeError as exc:
            if str(exc)!='P65_SYNTHETIC_POLL_INTERRUPTION':raise
        else:raise RuntimeError('P65_ABORT_SMOKE_EXPECTED_INTERRUPTION')
        sealed=live.safe_stats()['raw_evidence']
        if (sealed is None or sealed['status']!='INCOMPLETE_RECORDED' or
                sealed['known_recording_gaps']!=1):
            raise RuntimeError('P65_ABORT_SMOKE_CLEAN_FILE_FALSE_POSITIVE')
        try:inspect_pcapng(c.final_path,server_ports=(40400,))
        except CaptureRejected:pass
        else:raise RuntimeError('P65_ABORT_SMOKE_LOSS_NOT_PERSISTED')
        # P66: the consumer of the *post-stop drain* fails. The recorder must
        # remain open until the failure is recorded and its loss marker sealed.
        from unittest.mock import patch
        from anka_contracts.capture import CapturedTcpSegment
        d=ConsentedPcapngRecorder(directory,server_ports=(40400,))
        if not d.record(frame):raise RuntimeError('P66_DRAIN_SMOKE_FRAME_REJECTED')
        source=WindowsLiveCapture(interface='synthetic',server_ports=(40400,),
                                  require_windows=False,sniffer_factory=SyntheticSniffer,
                                  evidence_recorder=d)
        source.queue.push(CapturedTcpSegment('synthetic-flow','client_to_server',
                                             1,b'TEST',1,0x18))
        def failed_consumer(_):
            if source._stopped:raise RuntimeError('P66_SYNTHETIC_DRAIN_INTERRUPTION')
        with patch('anka_capture.windows_live.monotonic_ns',side_effect=[0,1_000_000_001]):
            try:
                capture_bounded_sample(interface='synthetic',server_ports=(40400,),
                                       duration_seconds=1,source=source,require_windows=False,
                                       on_poll=failed_consumer)
            except RuntimeError as exc:
                if str(exc)!='P66_SYNTHETIC_DRAIN_INTERRUPTION':raise
            else:raise RuntimeError('P66_DRAIN_SMOKE_EXPECTED_INTERRUPTION')
        sealed=source.safe_stats()['raw_evidence']
        if sealed is None or sealed['status']!='INCOMPLETE_RECORDED' or sealed['known_recording_gaps']!=1:
            raise RuntimeError('P66_DRAIN_SMOKE_UNSEALED_FAILURE')
        try:inspect_pcapng(d.final_path,server_ports=(40400,))
        except CaptureRejected:pass
        else:raise RuntimeError('P66_DRAIN_SMOKE_LOSS_NOT_PERSISTED')
    return {'status':'PASS_SYNTHETIC_ONLY','cases':4,
            'raw_evidence_opt_in_required':True,'driver_loss_visibility':'UNKNOWN',
            'current_build_certified':False,'canonical_commits':0,
            'physical_input_sent':False}
