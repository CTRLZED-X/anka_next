"""Narrow research-only Dofus 3.7.10.10 fight lifecycle mapping.

Based on archived R5.198 fight handlers `_jvi/_jvj/_jup/_jxd`.
No R5.198 imports, no live adapter registration and no state mutation.
"""
from __future__ import annotations
from hashlib import sha256
from anka_contracts.canonical import EvidenceRef
from anka_contracts.historical_lifecycle import LegacyFightScope, LegacyFightObservation, LegacyFightResult
from anka_contracts.protocol import WireMessage
from anka_protocol.wire import parse_fields, WireRejected

BUILD = 'Dofus 3.7.10.10'
ADAPTER_ID = 'dofus_3_7_10_10_p45_lifecycle_history'
NAMES = {'jvi':'ROUND_OBSERVED', 'jvj':'TURN_OWNER_OBSERVED',
         'jup':'TURN_END_OBSERVED','jxd':'FIGHT_READY_OBSERVED'}


def _scalar(node:dict, number:int, *, required=True, signed=False)->int|None:
    values=node.get(number, ())
    if not values and not required:
        return None
    if len(values)!=1 or type(values[0]) is not int:
        raise ValueError('P45_REQUIRED_SCALAR_MISSING_OR_REPEATED')
    v=values[0]
    return v-(1<<64) if signed and v>=1<<63 else v


class HistoricalLifecycleDecoder:
    """Pure decoder; caller must supply correct independent account/fight binding."""
    def __init__(self, *, requested_build:str):
        self.build=requested_build

    def decode(self, message:WireMessage, *, scope:LegacyFightScope|None)->LegacyFightResult:
        meta=dict(adapter_id=ADAPTER_ID,protocol_build=self.build,wire_name=message.name)
        if self.build != BUILD:
            return LegacyFightResult('BUILD_MISMATCH',**meta)
        if message.name not in NAMES:
            return LegacyFightResult('NO_MAPPING',**meta)
        if message.direction!='server_to_client':
            return LegacyFightResult('QUARANTINED',failure_code='P45_UNTRUSTED_DIRECTION',**meta)
        digest=sha256(message.flow_key.encode('utf8')).hexdigest()
        if (not message.flow_key or not isinstance(scope,LegacyFightScope) or scope.protocol_build != BUILD or
            scope.generation != message.generation or scope.flow_digest != digest):
            return LegacyFightResult('SCOPE_UNVERIFIED',**meta)
        try:
            fields=parse_fields(message.body)
            kind=NAMES[message.name]
            data={}
            if kind=='ROUND_OBSERVED':
                data['round_number']=_scalar(fields,1)
            elif kind=='TURN_OWNER_OBSERVED':
                data['actor_id']=_scalar(fields,3,signed=True)
                data['round_number']=_scalar(fields,7,required=False)
                data['wire_turn_index']=_scalar(fields,6,required=False)
            elif kind=='TURN_END_OBSERVED':
                data['actor_id']=_scalar(fields,2,signed=True)
            else:
                data['actor_id']=_scalar(fields,2,signed=True)
                ready=_scalar(fields,3)
                if ready not in (0,1):
                    raise ValueError('P45_READY_VALUE_NOT_BOOLEAN')
                data['ready']=bool(ready)
            evidence=EvidenceRef(BUILD,ADAPTER_ID,message.name,message.packet_number,
                                 message.generation,digest,message_index=message.message_index)
            observation=LegacyFightObservation(kind,evidence,scope.fight_id,**data)
            return LegacyFightResult('OBSERVATIONS_ONLY',observations=(observation,),**meta)
        except (ValueError,TypeError,WireRejected,OverflowError):
            return LegacyFightResult('QUARANTINED',failure_code='P45_SCHEMA_OR_VALUE_DRIFT',**meta)
