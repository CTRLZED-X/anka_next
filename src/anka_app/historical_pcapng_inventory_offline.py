"""P50 synthetic, non-authoritative flow-inventory setup regression fixture."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from anka_app.historical_pcapng_offline import _frame, _synthetic_pcap, _var
from anka_app.historical_pcapng_inventory import (
    inspect_pcapng_flow_inventory, replay_inventoried_pcapng_flow,
)
from anka_capture.pcapng import read_pcapng_tcp_segments
from anka_contracts.historical_lifecycle import LegacyFightScope
from anka_protocol.adapters.historical_lifecycle import BUILD


def historical_flow_inventory_smoke(root: Path) -> dict:
    wire = (_frame('jvj', _var(3 << 3) + _var(33)) +
            _frame('jup', _var(2 << 3) + _var(33)) +
            _frame('jwp', b''))
    with TemporaryDirectory(prefix='anka_p50_flow_') as work:
        source=Path(work)/'synthetic.pcapng'
        source.write_bytes(_synthetic_pcap(wire))
        candidate=read_pcapng_tcp_segments(source,server_ports={40400})[0]
        scope=LegacyFightScope(37,sha256(candidate.flow_id.encode()).hexdigest(),1,BUILD)
        inventory=inspect_pcapng_flow_inventory(source,ports=(40400,))
        report=replay_inventoried_pcapng_flow(source,root=root,ports=(40400,),
                                              inventory=inventory,scope=scope)
    if not (inventory.status == 'CANDIDATES_ONLY' and len(inventory.flows)==1 and
            inventory.flows[0].flow_digest==scope.flow_digest and
            report.reason=='P50_RESEARCH_ONLY' and report.research is not None and
            report.research.observed_historical_events==3 and
            not inventory.account_binding_verified and not report.actionable and
            not inventory.current_client_certified and not report.physical_input_sent and
            report.canonical_commits==0):
        raise RuntimeError('P50_HISTORICAL_FLOW_DISCOVERY_SMOKE_FAILED')
    return {'status':'PASS_CANDIDATE_FLOW_ONLY','candidate_flows':len(inventory.flows),
            'historical_messages':report.research.observed_historical_events,
            'account_binding_verified':False,'capture_complete':False,
            'canonical_commits':0,'physical_input_sent':False}
