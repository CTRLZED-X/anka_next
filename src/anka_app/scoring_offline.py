"""Read-only P15 demonstration; all target/risk priorities invented as TEST inputs."""
from __future__ import annotations
from pathlib import Path
from anka_app.decision_offline import reference_kernel
from anka_app.map_research_offline import synthetic_map_scene
from anka_contracts.decision import CastProbe
from anka_contracts.tactical_research import TacticalResearchRequest
from anka_contracts.tactical_scoring import (
    TacticalScoringRequest,SyntheticTargetPriority,SyntheticPositionRisk)
from anka_decision.tactical_scoring import inspect_tactical_scoring


def scoring_demo(*, root:Path, observer=None, policy:str='CRA_DAMAGE_RESEARCH') -> dict:
    snap,map_definition,context=synthetic_map_scene()
    tactical = TacticalResearchRequest(
        CastProbe('cra-session','cra',1,'test-fight',8,777,32435,3,229),
        123,(215,201,400),(229,220))
    research = TacticalScoringRequest(
        tactical, policy,
        (SyntheticTargetPriority(229,5,1),SyntheticTargetPriority(220,1,5)),
        (SyntheticPositionRisk(215,3),SyntheticPositionRisk(201,1),
         SyntheticPositionRisk(400,0)))
    report = inspect_tactical_scoring(snap,research,map_definition=map_definition,
                                      fight_context=context,kernel=reference_kernel(root))
    if observer is not None:
        try:
            observer.record('decision.synthetic_scoring_completed',
                boundary='decision.tactical_scoring', payload={
                    'policy':policy,'count':report.evaluated_count,
                    'scored_count':sum(x.score is not None for x in report.ranked),
                    'input_authority':False,'physical_input_sent':False})
        except Exception:pass
    return {'operation':'scoring-demo','status':report.status,'report':report.to_dict(),
            'synthetic_priority_fixture':True,'live_ready':False,
            'physical_input_sent':False}
