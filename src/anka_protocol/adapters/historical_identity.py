"""P53 narrow historical Dofus 3.7.10.10 world-character identity research.

R5.198 explicitly registered `jnj` for LOCAL_ACTOR and matched the configured
character name inside each world entity.  Its `jns` implementation also performs
a similar match, but the handler registry did not declare LOCAL_ACTOR for jns.
P53 preserves that disagreement: only jnj can emit a historical identity
observation; jns is reported as CAPABILITY_UNDECLARED.
"""
from __future__ import annotations

from hashlib import sha256

from anka_contracts.canonical import EvidenceRef
from anka_contracts.historical_identity import (
    HistoricalIdentityScope, HistoricalIdentityObservation, HistoricalIdentityResult,
)
from anka_contracts.protocol import WireMessage
from anka_protocol.wire import parse_fields, WireRejected

BUILD='Dofus 3.7.10.10'
ADAPTER_ID='dofus_3_7_10_10_p53_world_identity_history'
RECOGNIZED=frozenset({'jnj','jns'})


class _ShapeError(ValueError):
    pass


def _one_int(node:dict, field:int, *, signed:bool=False)->int:
    vals=node.get(field,())
    if len(vals)!=1 or type(vals[0]) is not int:
        raise _ShapeError('P53_REQUIRED_INT_MISSING_OR_REPEATED')
    value=vals[0]
    return value-(1<<64) if signed and value>=1<<63 else value


def _one_bytes(node:dict, field:int)->bytes:
    vals=node.get(field,())
    if len(vals)!=1 or type(vals[0]) is not bytes:
        raise _ShapeError('P53_REQUIRED_CHILD_MISSING_OR_REPEATED')
    return vals[0]


def _child(node:dict, *path:int)->dict:
    cur=node
    for field in path:
        cur=parse_fields(_one_bytes(cur,field))
    return cur


def _name_matches(observed:str, expected:str)->bool:
    observed=observed.strip().casefold();expected=expected.strip().casefold()
    if not observed or not expected:return False
    return observed==expected or (observed.startswith(expected+'-[') and observed.endswith(']'))


def _entity(raw:bytes)->tuple[int,int,str|None]:
    node=parse_fields(raw)
    actor=_one_int(node,1,signed=True)
    pose=_child(node,2)
    cell=_one_int(pose,3)
    name=None
    try:
        identity=_child(node,3,1,3)
        raw_name=_one_bytes(identity,5)
        name=raw_name.decode('utf8',errors='strict').strip() or None
    except (_ShapeError,WireRejected,UnicodeDecodeError):
        name=None
    return actor,cell,name


class HistoricalIdentityDecoder:
    """Pure historical identity decoder; never creates CharacterEvidence."""
    def __init__(self, *, requested_build:str):
        self.build=requested_build

    def decode(self, message:WireMessage, *, scope:HistoricalIdentityScope|None)->HistoricalIdentityResult:
        base=dict(adapter_id=ADAPTER_ID,protocol_build=self.build,wire_name=message.name)
        if self.build != BUILD:
            return HistoricalIdentityResult('BUILD_MISMATCH',**base)
        if message.name not in RECOGNIZED:
            return HistoricalIdentityResult('NO_MAPPING',**base)
        if message.name == 'jns':
            # Deliberately before payload parsing: R5.198 registry metadata does
            # not declare LOCAL_ACTOR capability for this handler.
            return HistoricalIdentityResult('CAPABILITY_UNDECLARED',failure_code='P53_JNS_LOCAL_ACTOR_NOT_REGISTRY_DECLARED',**base)
        if message.direction != 'server_to_client':
            return HistoricalIdentityResult('QUARANTINED',failure_code='P53_UNTRUSTED_DIRECTION',**base)
        try:
            encoded=message.flow_key.encode('utf8',errors='strict')
        except (AttributeError,UnicodeError):
            return HistoricalIdentityResult('SCOPE_UNVERIFIED',**base)
        digest=sha256(encoded).hexdigest()
        if (not message.flow_key or not isinstance(scope,HistoricalIdentityScope) or
                scope.protocol_build != BUILD or scope.generation != message.generation or
                scope.flow_digest != digest):
            return HistoricalIdentityResult('SCOPE_UNVERIFIED',**base)
        try:
            root=parse_fields(message.body)
            map_id=_one_int(root,10)
            matches=[]
            for raw in root.get(3,()):
                if type(raw) is not bytes:
                    raise _ShapeError('P53_WORLD_ENTITY_WRONG_WIRE_TYPE')
                actor,cell,name=_entity(raw)
                if name is not None and _name_matches(name,scope.expected_character_name):
                    matches.append((actor,cell))
            if not matches:
                return HistoricalIdentityResult('NO_MATCH',**base)
            if len(matches)!=1:
                return HistoricalIdentityResult('QUARANTINED',failure_code='P53_CHARACTER_IDENTITY_AMBIGUOUS',**base)
            actor,cell=matches[0]
            evidence=EvidenceRef(BUILD,ADAPTER_ID,message.name,message.packet_number,
                                 message.generation,digest,message_index=message.message_index)
            obs=HistoricalIdentityObservation(evidence,scope.expected_character_name,actor,cell,map_id)
            return HistoricalIdentityResult('OBSERVATIONS_ONLY',observations=(obs,),**base)
        except (_ShapeError,WireRejected,ValueError,TypeError,OverflowError,UnicodeError):
            return HistoricalIdentityResult('QUARANTINED',failure_code='P53_WORLD_IDENTITY_SCHEMA_OR_VALUE_DRIFT',**base)
