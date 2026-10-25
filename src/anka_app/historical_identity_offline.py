"""P53 fast synthetic smoke for historical identity + host-flow composition.

Runs during `check`/`setup`.  No Win32, network, Canonical state, or input calls.
"""
from __future__ import annotations

from hashlib import sha256

from anka_app.ingress_readiness import historical_character_process_topology
from anka_capture.windows_flows import TcpEndpoint
from anka_contracts.client import WindowObservation, WindowScan
from anka_contracts.historical_identity import HistoricalIdentityScope
from anka_contracts.protocol import WireMessage
from anka_protocol.adapters.historical_identity import HistoricalIdentityDecoder, BUILD


def _v(n:int)->bytes:
    if n < 0:n=(1<<64)+n
    out=[]
    while n>=128:
        out.append((n&127)|128);n>>=7
    out.append(n);return bytes(out)


def _i(field:int,value:int)->bytes:return _v(field<<3)+_v(value)
def _b(field:int,value:bytes)->bytes:return _v(field<<3|2)+_v(len(value))+value


def _entity(actor:int,cell:int,name:str)->bytes:
    identity=_b(1,_b(3,_b(5,name.encode('utf8'))))
    return _i(1,actor)+_b(2,_i(3,cell))+_b(3,identity)


def _jnj(map_id:int,actor:int,cell:int,name:str)->bytes:
    return _b(3,_entity(actor,cell,name))+_i(10,map_id)


def historical_identity_topology_smoke()->dict:
    decoder=HistoricalIdentityDecoder(requested_build=BUILD)
    flows={'p53-cra':('127.0.0.1',45101,'198.51.100.7',40400),
           'p53-enu':('127.0.0.1',45102,'198.51.100.7',40400)}
    witnesses={}
    for index,(token,name,actor,cell) in enumerate((
            ('p53-cra','Curseni',41,301),('p53-enu','Sosoking',42,302)),1):
        scope=HistoricalIdentityScope(sha256(token.encode()).hexdigest(),1,BUILD,name)
        message=WireMessage('server_to_client','jnj',_jnj(777,actor,cell,name),index,token,1,0)
        result=decoder.decode(message,scope=scope)
        if result.status!='OBSERVATIONS_ONLY' or len(result.observations)!=1:
            raise RuntimeError('P53_HISTORICAL_IDENTITY_SMOKE_DECODE_FAILED')
        witnesses[token]=result.observations[0]
    # P53 must preserve the historical source/registry disagreement.
    jns=decoder.decode(WireMessage('server_to_client','jns',b'\xff',3,'p53-cra',1,0),
        scope=HistoricalIdentityScope(sha256(b'p53-cra').hexdigest(),1,BUILD,'Curseni'))
    if jns.status!='CAPABILITY_UNDECLARED':
        raise RuntimeError('P53_JNS_REGISTRY_DISCREPANCY_NOT_PRESERVED')
    windows=(
        WindowObservation(501,101,1001,'Dofus.exe','Dofus',1280,649,96,False),
        WindowObservation(502,102,1002,'Dofus.exe','Dofus',1280,649,96,False),
    )
    before=WindowScan(10_000,windows);after=WindowScan(20_000,windows)
    tcp=(TcpEndpoint(*flows['p53-cra'],101,5),TcpEndpoint(*flows['p53-enu'],102,5))
    good=historical_character_process_topology(before,after,tcp,tcp,flows,witnesses,
        expected_character_names=('Curseni','Sosoking'))
    conflict=historical_character_process_topology(before,after,
        (tcp[0],tcp[1],TcpEndpoint(*flows['p53-cra'],999,5)),tcp,flows,witnesses,
        expected_character_names=('Curseni','Sosoking'))
    if not (good.get('status')=='HISTORICAL_CANDIDATES_ONLY' and
            good.get('matched_process_character_candidates')==2 and
            good.get('distinct_candidate_processes')==2 and
            good.get('historical_identity_only') is True and
            good.get('account_binding_verified') is False and
            good.get('current_build_certified') is False and
            conflict.get('status')=='PARTIAL_CANDIDATES' and
            conflict.get('host_ambiguous_flows')==1):
        raise RuntimeError('P53_HISTORICAL_IDENTITY_TOPOLOGY_SMOKE_FAILED')
    return {'status':'PASS_HISTORICAL_IDENTITY_RESEARCH_ONLY',
            'historical_identity_witnesses':2,
            'stable_process_character_candidates':2,
            'jnj_registry_declared_identity':True,
            'jns_registry_discrepancy_guarded':True,
            'historical_build_verified':True,
            'independent_current_character_witnesses':0,
            'account_binding_verified':False,'current_build_certified':False,
            'canonical_commits':0,'physical_input_sent':False}
