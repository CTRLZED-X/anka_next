"""Read-only P14 composition demo: synthetic scene -> preserved kernel -> research."""
from __future__ import annotations
from pathlib import Path
from anka_app.decision_offline import reference_kernel
from anka_app.map_research_offline import synthetic_map_scene
from anka_contracts.decision import CastProbe
from anka_contracts.tactical_research import TacticalResearchRequest
from anka_decision.tactical_research import inspect_tactical_research


def tactical_demo(*,root:Path,observer=None)->dict:
    kernel=reference_kernel(root)
    snapshot,map_definition,context=synthetic_map_scene()
    request=TacticalResearchRequest(
        scope=CastProbe('cra-session','cra',1,'test-fight',8,777,32435,3,229),
        geometry_map_id=123,movement_cells=(215,201,400),target_cells=(229,220),
        spell_sequence=((32435,3),(32435,3)),
    )
    report=inspect_tactical_research(snapshot,request,map_definition=map_definition,
                                     fight_context=context,kernel=kernel)
    if observer is not None:
        try:
            observer.record('decision.synthetic_tactical_research_completed',
                boundary='decision.tactical_research',payload={
                    'status':report.status,'candidates':len(report.candidates),
                    'actionable':False,'physical_input_sent':False})
        except Exception:
            pass
    return {'operation':'tactical-demo','status':report.status,'report':report.to_dict(),
            'historical_static_game_version':'3.6.10.10',
            'live_ready':False,'physical_input_sent':False}
