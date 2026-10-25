"""P16 deterministic, explicitly synthetic sequence demo composition."""
from __future__ import annotations
from pathlib import Path
from anka_app.decision_offline import reference_kernel
from anka_app.map_research_offline import synthetic_map_scene
from anka_contracts.decision import CastProbe
from anka_contracts.tactical_research import TacticalResearchRequest
from anka_contracts.sequence_research import ResearchCastStep,SequenceResearchRequest
from anka_decision.sequence_research import inspect_sequence_research


def sequence_demo(*,root:Path,observer=None)->dict:
    snapshot,geometry,context=synthetic_map_scene()
    research=TacticalResearchRequest(CastProbe('cra-session','cra',1,'test-fight',8,777,32435,3,229),
                                     123,(215,201),(229,220))
    req=SequenceResearchRequest(research,215,(ResearchCastStep(32435,3,229),ResearchCastStep(32435,3,229)))
    result=inspect_sequence_research(snapshot,req,map_definition=geometry,fight_context=context,
                                      kernel=reference_kernel(root))
    if observer is not None:
        try:observer.record('decision.sequence_research_completed',boundary='decision.sequence_research',
                            payload={'status':result.status,'steps':result.attempted_count,
                                     'physical_input_sent':False,'stopped_on_uncertainty':result.status=='STOPPED_UNCERTAIN'})
        except Exception:pass
    return {'operation':'sequence-demo','status':result.status,'report':result.to_dict(),
            'synthetic_fixture':True,'live_ready':False,'physical_input_sent':False}
