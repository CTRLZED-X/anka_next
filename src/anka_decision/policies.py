"""M8 strategy profiles with provenance-bound historical priorities.

Priorities are strategy preferences, never live evidence. A spell is considered
only when the DecisionFrame independently proves it is currently available.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json

@dataclass(frozen=True,slots=True)
class ClassPolicy:
    policy_id:str
    class_id:int
    class_name:str
    spell_priority:tuple[tuple[int,int,int],...]  # spell, grade, priority
    source_authority:str

    def __post_init__(self):
        if not self.policy_id or self.class_id<=0 or not self.class_name:raise ValueError('INVALID_CLASS_POLICY')
        if len({(s,g) for s,g,_ in self.spell_priority})!=len(self.spell_priority):raise ValueError('DUPLICATE_CLASS_POLICY_SPELL')


def load_legacy_profiles(asset:Path)->dict[str,ClassPolicy]:
    obj=json.loads(Path(asset).read_text())
    if obj.get('authority')!='HISTORICAL_STRATEGY_REFERENCE_ONLY':raise ValueError('DECISION_POLICY_AUTHORITY_INVALID')
    ids={'cra':(9,'Crâ'),'enu':(3,'Enutrof')};out={}
    for key,(cid,name) in ids.items():
        rows=obj['profiles'][key]['spells']
        out[key]=ClassPolicy('legacy-r5198-'+key,cid,name,tuple((int(x['spell_id']),int(x['grade']),int(x['priority'])) for x in rows),obj['authority'])
    return out

def order_proven_spells(frame_spells,policy:ClassPolicy|None):
    proven=tuple(frame_spells)
    if policy is None:return proven
    rank={(s,g):-p for s,g,p in policy.spell_priority}
    return tuple(sorted(proven,key=lambda x:(rank.get(tuple(x),0),x[0],x[1])))
