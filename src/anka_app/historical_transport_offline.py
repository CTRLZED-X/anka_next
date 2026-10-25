"""Fast P48 preflight: real FrameBuffer/ProtocolInspector/P47 synthetic trace.

No historical messages are promoted to Canonical or physical input. Raw packet
bytes are synthetic ephemeral fixtures, not stored or exported.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from anka_contracts.capture import CapturedTcpSegment, CapturePoll
from anka_contracts.historical_lifecycle import LegacyFightScope
from anka_protocol.adapters.historical_lifecycle import BUILD
from anka_app.historical_transport_bridge import replay_historical_capture_polls


def _v(v):
    out=[]
    while v>=128:
        out.append((v & 127) | 128);v>>=7
    out.append(v);return bytes(out)


def _blob(n,b):return _v(n<<3 | 2)+_v(len(b))+b


def historical_transport_smoke(root:Path)->dict:
    flow='p48_synthetic_tcp_flow'
    scope=LegacyFightScope(37,sha256(flow.encode()).hexdigest(),1,BUILD)
    def frame(name,body):
        envelope=_blob(1,('type.ankama.com/'+name).encode())+_blob(2,body)
        return _v(len(envelope))+envelope
    wire=frame('jvj',_v(3<<3)+_v(33))+frame('jup',_v(2<<3)+_v(33))+frame('jwp',b'')
    syn=CapturedTcpSegment(flow,'server_to_client',100,b'',1,2)
    content=CapturedTcpSegment(flow,'server_to_client',101,wire,2)
    def poll(*segments,visibility='AVAILABLE_CLEAN'):
        return (CapturePoll('preflight_fixture',(syn,)+segments,0,False,True,visibility),)
    good=replay_historical_capture_polls(poll(content),scope=scope,root=root)
    gap=replay_historical_capture_polls(poll(content,visibility='UNKNOWN'),scope=scope,root=root)
    incomplete=replay_historical_capture_polls(poll(CapturedTcpSegment(flow,'server_to_client',101,wire[:-5],2)),scope=scope,root=root)
    if not (good.status=='RESEARCH_TRANSPORT_ONLY' and good.selected_server_messages==3 and
            gap.blocking_issue=='P48_CAPTURE_LOSS_OR_DRIVER_VISIBILITY_UNKNOWN' and
            incomplete.blocking_issue=='P48_PROTOCOL_FRAMING_UNTRUSTED' and
            all(x.canonical_commits==0 and not x.physical_input_sent and
                not x.current_client_certified and not x.actionable and
                not x.account_binding_verified and not x.source_completeness_verified
                for x in (good,gap,incomplete))):
        raise RuntimeError('P48_HISTORICAL_CAPTURE_BRIDGE_SMOKE_FAILED')
    return {'status':'PASS_HISTORICAL_RESEARCH_ONLY',
            'research_observations':good.replay.decoded_messages,
            'loss_rejected':gap.blocking_issue,
            'truncated_frame_rejected':incomplete.blocking_issue,
            'live_ready':False,'canonical_commits':0,'physical_input_sent':False}
