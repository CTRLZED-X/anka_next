"""P54 synthetic integration smoke: jnj identity -> historical fight actor continuity.

Uses the recovered historical decoders end-to-end.  It is deliberately offline,
historical, non-authoritative and sends no operating-system input.
"""
from __future__ import annotations

from hashlib import sha256

from anka_contracts.historical_identity import HistoricalIdentityScope
from anka_contracts.historical_lifecycle import LegacyFightScope
from anka_contracts.protocol import WireMessage
from anka_protocol.adapters.historical_identity import HistoricalIdentityDecoder, BUILD
from anka_protocol.adapters.historical_lifecycle import HistoricalLifecycleDecoder
from anka_protocol.adapters.historical_combat import HistoricalCombatDecoder
from anka_protocol.historical_actor_continuity import audit_historical_actor_continuity
from anka_app.ingress_readiness import historical_process_character_actor_topology
from anka_capture.windows_flows import TcpEndpoint
from anka_contracts.client import WindowObservation, WindowScan


def _v(n:int)->bytes:
    if n < 0:n=(1<<64)+n
    out=[]
    while n>=128:
        out.append((n&127)|128);n>>=7
    out.append(n);return bytes(out)

def _i(field:int,value:int)->bytes:return _v(field<<3)+_v(value)
def _b(field:int,value:bytes)->bytes:return _v(field<<3|2)+_v(len(value))+value

def _entity(actor:int,cell:int,name:str)->bytes:
    ident=_b(1,_b(3,_b(5,name.encode('utf8'))))
    return _i(1,actor)+_b(2,_i(3,cell))+_b(3,ident)

def _jnj(map_id:int,actor:int,cell:int,name:str)->bytes:
    return _b(3,_entity(actor,cell,name))+_i(10,map_id)

def _cast(actor:int,spell:int=123,level:int=456,cell:int=250)->bytes:
    inner=_b(2,_i(1,level)+_i(2,spell))+_i(5,cell)
    return _i(22,300)+_i(36,actor)+_b(2,inner)


def historical_actor_continuity_smoke()->dict:
    token='p54-history-flow';generation=4;fight_id=901;actor=41
    digest=sha256(token.encode()).hexdigest()
    identity_scope=HistoricalIdentityScope(digest,generation,BUILD,'Curseni')
    fight_scope=LegacyFightScope(fight_id,digest,generation,BUILD)
    identity_decoder=HistoricalIdentityDecoder(requested_build=BUILD)
    life=HistoricalLifecycleDecoder(requested_build=BUILD)
    combat=HistoricalCombatDecoder(requested_build=BUILD)

    identity_result=identity_decoder.decode(
        WireMessage('server_to_client','jnj',_jnj(777,actor,301,'Curseni'),1,token,generation,0),
        scope=identity_scope)
    if identity_result.status!='OBSERVATIONS_ONLY' or len(identity_result.observations)!=1:
        raise RuntimeError('P54_IDENTITY_DECODE_SMOKE_FAILED')
    owner=life.decode(WireMessage('server_to_client','jvj',_i(3,actor),2,token,generation,0),scope=fight_scope)
    cast=combat.decode(WireMessage('server_to_client','jsq',_cast(actor),3,token,generation,0),scope=fight_scope)
    end=life.decode(WireMessage('server_to_client','jup',_i(2,actor),4,token,generation,0),scope=fight_scope)
    if any(x.status!='OBSERVATIONS_ONLY' or len(x.observations)!=1 for x in (owner,cast,end)):
        raise RuntimeError('P54_FIGHT_DECODE_SMOKE_FAILED')
    audit=audit_historical_actor_continuity(identity_result.observations[0],(
        owner.observations[0],cast.observations[0],end.observations[0]))
    if not (audit.status=='RESEARCH_ACTOR_CONTINUITY_ONLY' and audit.local_actor_references==3 and
            audit.local_turn_owner_records==1 and audit.local_cast_records==1 and
            audit.local_turn_end_records==1 and not audit.current_client_certified and
            not audit.account_binding_verified and audit.canonical_commits==0 and
            not audit.actionable and not audit.physical_input_sent):
        raise RuntimeError('P54_ACTOR_CONTINUITY_SMOKE_FAILED')

    # Same flow/build but a different actor must never be misreported as local continuity.
    foreign=life.decode(WireMessage('server_to_client','jvj',_i(3,99),2,token,generation,0),scope=fight_scope)
    partial=audit_historical_actor_continuity(identity_result.observations[0],(foreign.observations[0],))
    if not (partial.status=='PARTIAL_EVIDENCE' and partial.first_issue=='P54_LOCAL_ACTOR_NOT_SEEN_IN_FIGHT'):
        raise RuntimeError('P54_ACTOR_MISMATCH_SMOKE_FAILED')
    # Exercise the complete P51/P53/P54 composition with two independent flows.
    flows={'p54-cra':('127.0.0.1',45201,'198.51.100.7',40400),
           'p54-enu':('127.0.0.1',45202,'198.51.100.7',40400)}
    ids={};fight_by_flow={}
    for i,(flow,name,aid) in enumerate((('p54-cra','Curseni',41),('p54-enu','Sosoking',42)),1):
        d=sha256(flow.encode()).hexdigest()
        ids[flow]=identity_decoder.decode(
            WireMessage('server_to_client','jnj',_jnj(777,aid,300+i,name),10*i,flow,generation,0),
            scope=HistoricalIdentityScope(d,generation,BUILD,name)).observations[0]
        fs=LegacyFightScope(900+i,d,generation,BUILD)
        fight_by_flow[flow]=(combat.decode(
            WireMessage('server_to_client','jsq',_cast(aid),10*i+1,flow,generation,0),scope=fs).observations[0],)
    windows=(
        WindowObservation(601,201,1201,'Dofus.exe','Dofus',1280,649,96,False),
        WindowObservation(602,202,1202,'Dofus.exe','Dofus',1280,649,96,False),
    )
    before=WindowScan(10_000,windows);after=WindowScan(20_000,windows)
    tcp=(TcpEndpoint(*flows['p54-cra'],201,5),TcpEndpoint(*flows['p54-enu'],202,5))
    chain=historical_process_character_actor_topology(before,after,tcp,tcp,flows,ids,fight_by_flow,
        expected_character_names=('Curseni','Sosoking'))
    if not (chain.get('status')=='HISTORICAL_ACTOR_CANDIDATES_ONLY' and
            chain.get('actor_continuity_verified')==2 and
            chain.get('historical_process_character_candidates')==2 and
            chain.get('cross_flow_ordering_verified') is False and
            chain.get('account_binding_verified') is False and
            chain.get('current_build_certified') is False and
            chain.get('actionable') is False):
        raise RuntimeError('P54_FULL_HISTORICAL_CHAIN_SMOKE_FAILED')
    return {
        'status':'PASS_HISTORICAL_ACTOR_CONTINUITY_RESEARCH_ONLY',
        'identity_witnesses':2,'fight_observations':2,'local_actor_references':2,
        'stable_process_character_actor_candidates':2,
        'cross_flow_ordering_verified':False,
        'current_client_certified':False,'account_binding_verified':False,
        'canonical_commits':0,'actionable':False,'physical_input_sent':False,
    }
