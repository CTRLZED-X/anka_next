"""Consumer-driven semantic diff/impact assessment."""
from __future__ import annotations
from dataclasses import dataclass
from anka_contracts.protocol import SemanticImpact

_CONSUMERS={
 'WORLD_MAP_OBSERVED':(('anka_live_state','anka_workflow'),('route','fight_entry')),
 'FIGHT_STARTED':(('anka_live_state','anka_coordination','anka_workflow'),('ready','fight')),
 'TURN_OWNER_OBSERVED':(('anka_live_state','anka_coordination','anka_execution'),('cast','move','end_turn')),
 'ACTOR_RESOURCE_ABSOLUTE':(('anka_live_state','anka_decision','anka_execution'),('cast','move')),
 'ACTOR_HP_ABSOLUTE':(('anka_live_state','anka_decision'),('fight','targeting')),
 'ACTOR_CELL_OBSERVED':(('anka_live_state','anka_decision','anka_execution'),('move','cast')),
 'SPELL_CAST_OBSERVED':(('anka_live_state','anka_execution'),('cast_settlement',)),
 'FIGHT_ENDED':(('anka_live_state','anka_coordination','anka_workflow'),('fight_end','world_reentry')),
}

@dataclass(frozen=True,slots=True)
class ProtocolSemanticDiff:
    status:str
    impacts:tuple[SemanticImpact,...]
    changed_kinds:tuple[str,...]
    blocks_build:bool

def semantic_impact_report(expected:dict[str,tuple[tuple[str,str],...]],actual:dict[str,tuple[tuple[str,str],...]])->ProtocolSemanticDiff:
    impacts=[];changed=[]
    for kind in sorted(set(expected)|set(actual)):
        if kind not in expected: change='ADDED'
        elif kind not in actual: change='REMOVED'
        elif expected[kind]==actual[kind]: change='UNCHANGED'
        else: change='CHANGED'
        consumers,actions=_CONSUMERS.get(kind,(('anka_live_state',),()))
        if change=='UNCHANGED': effect='NONE'
        elif change=='ADDED' and not consumers: effect='OBSERVE_ONLY'
        else: effect='BLOCK_BUILD'
        impacts.append(SemanticImpact(kind,change,tuple(consumers),tuple(actions),effect))
        if change!='UNCHANGED': changed.append(kind)
    return ProtocolSemanticDiff('EQUIVALENT' if not changed else 'DIFFERENT',tuple(impacts),tuple(changed),any(x.safety_effect=='BLOCK_BUILD' for x in impacts))
