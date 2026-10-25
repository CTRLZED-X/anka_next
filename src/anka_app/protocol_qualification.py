"""Application composition for P10: protocol fixture qualification only.

The builder wires a specific historical adapter to independently authored
synthetic golden cases; never registers it for live execution.
"""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
from anka_protocol.qualification import run_suite
from anka_protocol.adapters.historical_semantic import HistoricalSemanticAdapter,ADAPTER_ID,BUILD

FIXTURE=Path('qualification/historical_3_7_10_10_synthetic.json')
ADAPTER=Path('src/anka_protocol/adapters/historical_semantic.py')


def qualify_historical(*,root:Path, requested_build:str=BUILD, observer=None) -> dict:
    root=Path(root)
    report=run_suite(root/FIXTURE,requested_build=requested_build,
                     adapter_factory=HistoricalSemanticAdapter, adapter_id=ADAPTER_ID,
                     historical_build=BUILD,adapter_sha256=sha256((root/ADAPTER).read_bytes()).hexdigest())
    if observer is not None:
        observer.record('protocol.synthetic_qualification_completed',
                        boundary='protocol.adapter_qualification',
                        payload={'status':report.status,'total_cases':len(report.cases),
                                 'passed_cases':sum(c.passed for c in report.cases),
                                 'fixture_digest':report.fixture_sha256,
                                 'candidate_build_matches_reference':requested_build==BUILD,
                                 'live_semantic_certified':False,'physical_input_sent':False})
    result=report.to_dict()
    result.update({'operation':'protocol-qualify','evidence_class':'SYNTHETIC_REFERENCE_ONLY',
                   'no_current_client_capture_supplied':True,'live_ready':False,
                   'gameplay_capabilities_certified':False,'physical_input_sent':False})
    return result
