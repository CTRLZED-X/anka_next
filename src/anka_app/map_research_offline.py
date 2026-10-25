"""Composition-only P13 offline fixture. Synthetic, never a gameplay input source."""
from __future__ import annotations
from pathlib import Path
from anka_contracts.decision import CastProbe
from anka_contracts.map_research import MapResearchRequest
from anka_decision.map_research import inspect_map_research
from anka_app.decision_offline import reference_kernel, synthetic_decision_snapshot
from anka_game_kernel.contexts.fight import FightContext
from anka_game_kernel.contexts.turn_history import TurnActionHistory
from anka_game_kernel.domain.actors import ActorState, SpellCooldown
from anka_game_kernel.domain.combat_stats import ActorCombatStats
from anka_game_kernel.domain.ids import ActorId, CellId, MapId, SpellId, TeamId
from anka_game_kernel.domain.maps import MapDefinition, MapNeighbors, MapCellDefinition
from anka_game_kernel.domain.provenance import Provenance, SourceKind, VerificationStatus


def synthetic_map_scene(*, blocked_los: tuple[int, ...] = (),
                        non_walkable: tuple[int, ...] = (), opponent_cell: int = 229):
    """Return immutable 560-cell map and fight context built purely in-memory."""
    snapshot=synthetic_decision_snapshot()
    cell=CellId(215)
    caster=ActorState(ActorId(777),team_id=TeamId(1),cell_id=cell,
        current_ap=11,current_mp=5,current_hp=2800,max_hp=3200,
        cooldowns=(SpellCooldown(SpellId(32435),0),),cooldowns_complete=True,
        active_state_ids=frozenset(),combat_stats=ActorCombatStats(range_bonus=0))
    enemy=ActorState(ActorId(888),team_id=TeamId(2),cell_id=CellId(opponent_cell),
        current_hp=2000,max_hp=2000,alive=True)
    provenance=Provenance(SourceKind.HISTORICAL_REFERENCE, 'P13_SYNTHETIC_FIXTURE',
        'offline',None,None,None,VerificationStatus.UNVERIFIED)
    cells=tuple(MapCellDefinition(CellId(i),0,i not in non_walkable,
        i in blocked_los,False,0,0,0,0,False,False) for i in range(560))
    map_definition=MapDefinition(MapId(123),MapNeighbors(None,None,None,None),cells,False,provenance)
    context=FightContext(actors=(caster,enemy),active_actor_id=caster.actor_id,
        round_number=1,map_id=MapId(123),current_turn=TurnActionHistory(caster.actor_id,1),
        global_turn_casts=())
    return snapshot,map_definition,context


def map_demo(*,root:Path,observer=None)->dict:
    kernel=reference_kernel(root)
    snap,map_definition,context=synthetic_map_scene()
    request=MapResearchRequest(CastProbe('cra-session','cra',1,'test-fight',8,777,32435,3,229),
        123,(229,220,201),201)
    result=inspect_map_research(snap,request,map_definition=map_definition,
                                fight_context=context,kernel=kernel)
    if observer is not None:
        try:observer.record('decision.synthetic_map_research_completed',boundary='decision.map_research',
            payload={'status':result.status,'evaluated_count':len(result.evaluated_cells),
                     'reachability_count':len(result.reachable_cells),'actionable':False})
        except Exception:pass
    return {'operation':'map-demo','status':result.status,'report':result.to_dict(),
        'historical_static_game_version':'3.6.10.10','live_ready':False,'physical_input_sent':False}
