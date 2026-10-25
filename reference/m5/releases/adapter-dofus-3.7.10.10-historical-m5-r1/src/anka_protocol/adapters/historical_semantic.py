"""Read-only, STRICT historical 3.7.10.10 semantics for offline research.

Port of narrow R5.198 3.7.10.10 handlers: jtk, jti, kqo. Not a current-build
adapter, not an authority source. Synthetic data never certifies these mappings.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from anka_contracts.protocol import WireMessage
from anka_contracts.canonical import CanonicalDraft,EvidenceRef
from anka_contracts.semantic import SemanticResult
from anka_protocol.wire import parse_fields,WireRejected

ADAPTER_ID='dofus_3_7_10_10_historical_semantics_p7'
BUILD='Dofus 3.7.10.10'
SUPPORTED=frozenset({'jtk','jti','kqo'})

class SchemaMismatch(ValueError):pass

def _fields(raw:bytes)->dict[int,list[int|bytes]]:
    try:return parse_fields(raw)
    except WireRejected as exc:raise SchemaMismatch('PROTOBUF_SHAPE_INVALID') from exc

def _integer(node:dict,field:int,*,signed:bool=False,required:bool=True)->int|None:
    vals=node.get(field,[])
    if not vals and not required:return None
    if len(vals)!=1 or type(vals[0]) is not int:raise SchemaMismatch('FIELD_MISSING_OR_AMBIGUOUS')
    x=vals[0]
    return x-(1<<64) if signed and x>=1<<63 else x

def _bytes(node:dict,field:int,*,required:bool=True)->bytes|None:
    vals=node.get(field,[])
    if not vals and not required:return None
    if len(vals)!=1 or not isinstance(vals[0],bytes):raise SchemaMismatch('FIELD_MISSING_OR_AMBIGUOUS')
    return vals[0]

def _signed(x:int)->int:return x-(1<<64) if x>=1<<63 else x

def _char_total(row:dict[int,list[int|bytes]])->int:
    # Mirrors the R5.198 historical strict branch rules; never infer zero
    # when a previously-unseen length-delimited branch appears.
    branches=[k for k,values in row.items() if any(isinstance(x,bytes) for x in values)]
    if any(k not in (1,3,5) for k in branches) or len(branches)>1:
        raise SchemaMismatch('CHARACTERISTIC_BRANCH_DRIFT')
    if not branches:return 0
    branch=branches[0]
    nested=_fields(_bytes(row,branch))
    allowed=(1,2,3,4,5,6) if branch==1 else (1,2,3,4,5,7)
    admissible=(*allowed,7) if branch==1 else allowed
    if any(isinstance(val,bytes) for vals in nested.values() for val in vals):
        raise SchemaMismatch('CHARACTERISTIC_COMPOSITION_DRIFT')
    # Historical decoder ignored unknown integers, but fail closed in the new
    # research adapter to avoid converting new fields to deceptively valid values.
    if any(field not in admissible for field in nested):raise SchemaMismatch('CHARACTERISTIC_COMPOSITION_DRIFT')
    return sum(_signed(v) for f in allowed for v in nested.get(f,[]) if isinstance(v,int))

@dataclass(frozen=True,slots=True)
class HistoricalContext:
    """External context: never invented from a window title or client request."""
    local_actor_id: int|None = None
    fight_active: bool = False
    identity_verified: bool = False

class HistoricalSemanticAdapter:
    def __init__(self,*,requested_build:str):
        self.build=requested_build

    def decode(self,msg:WireMessage,*,context:HistoricalContext|None=None)->SemanticResult:
        base=dict(adapter_id=ADAPTER_ID,protocol_build=self.build,wire_name=msg.name)
        if self.build!=BUILD:return SemanticResult('BUILD_MISMATCH',**base)
        if msg.name not in SUPPORTED:return SemanticResult('NO_SEMANTIC_MAPPING',**base)
        if msg.direction!='server_to_client':return SemanticResult('QUARANTINED',failure_code='UNTRUSTED_MESSAGE_DIRECTION',**base)
        provenance=EvidenceRef(BUILD,ADAPTER_ID,msg.name,msg.packet_number,msg.generation,sha256(msg.flow_key.encode('utf8')).hexdigest(),message_index=msg.message_index)
        try:
            node=_fields(msg.body)
            drafts=[]
            if msg.name=='jtk':
                actor=_integer(node,2,signed=True)
                root=_fields(_bytes(node,1))
                raws=root.get(4,[])
                if len(raws)>200:raise SchemaMismatch('CHARACTERISTIC_ROW_LIMIT')
                if not raws:raise SchemaMismatch('CHARACTERISTIC_ROWS_ABSENT')
                found=set()
                for raw in raws:
                    if not isinstance(raw,bytes):raise SchemaMismatch('CHARACTERISTIC_ROW_INVALID')
                    row=_fields(raw)
                    cid=_integer(row,2)
                    if cid in found:raise SchemaMismatch('CHARACTERISTIC_ID_DUPLICATE')
                    found.add(cid)
                    resource={1:'AP',23:'MP',19:'RANGE'}.get(cid)
                    if resource is not None:
                        drafts.append(CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',actor,provenance,resource=resource,value=_char_total(row)))
                if not drafts:return SemanticResult('NO_SEMANTIC_MAPPING',**base)
            elif msg.name=='jti':
                actor=_integer(node,2,signed=True)
                entries=[]
                raw_rows=node.get(4,[])
                if len(raw_rows)>200:raise SchemaMismatch('COOLDOWN_ROW_LIMIT')
                for raw in raw_rows:
                    if not isinstance(raw,bytes):raise SchemaMismatch('COOLDOWN_ROW_INVALID')
                    row=_fields(raw)
                    spell=_integer(row,3)
                    remain=_integer(row,2,required=False)
                    entries.append((spell,0 if remain is None else remain))
                drafts.append(CanonicalDraft('ACTOR_COOLDOWN_SNAPSHOT',actor,provenance,cooldowns=tuple(entries)))
            elif msg.name=='kqo':
                if context is None or not context.fight_active or not context.identity_verified or context.local_actor_id is None:
                    return SemanticResult('CONTEXT_MISSING',**base)
                max_hp=_integer(node,1)
                hp=_integer(node,3)
                drafts.append(CanonicalDraft('ACTOR_HP_ABSOLUTE',context.local_actor_id,provenance,value=hp,maximum=max_hp))
            return SemanticResult('CANDIDATES_ONLY',candidates=tuple(drafts),**base)
        except (SchemaMismatch,ValueError,TypeError,OverflowError) as exc:
            # A novel schema or implausible value is quarantined, never decoded
            # as zero or partially emitted to consumers.
            return SemanticResult('QUARANTINED',failure_code=('CANONICAL_RANGE_OR_VALUE_INVALID' if not isinstance(exc,SchemaMismatch) else str(exc)),**base)
