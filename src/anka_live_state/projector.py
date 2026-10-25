"""Definitive M7 pure immutable Live State projector.

Only committed CanonicalEventEnvelope objects are accepted. Missing values stay
unknown; stale evidence remains visible with its provenance instead of becoming 0.
"""
from __future__ import annotations
from dataclasses import replace
from hashlib import sha256
import json

from anka_contracts.canonical import CanonicalEventEnvelope
from anka_contracts.state import FieldValueProof,ActorLiveSnapshot,LiveStateSnapshot

class LiveStateProjectionError(ValueError): pass

_FIELDS=('cell','hp','max_hp','ap','mp','range','cooldowns','ready')

def _unknown(name:str,cursor:int,reason:str,*,fight_epoch=None,turn_epoch=None)->FieldValueProof:
    return FieldValueProof(name,None,'UNKNOWN',(),cursor,fight_epoch,turn_epoch,invalidation_reason=reason)

def _known(name:str,value,event:CanonicalEventEnvelope,*,fight_epoch=None,turn_epoch=None)->FieldValueProof:
    return FieldValueProof(name,value,'KNOWN',(event.event_id,),event.canonical_cursor,fight_epoch,turn_epoch)

def _stale(p:FieldValueProof,cursor:int,reason:str,*,fight_epoch=None,turn_epoch=None)->FieldValueProof:
    return FieldValueProof(p.field_name,p.value,'STALE',p.source_event_ids,cursor,fight_epoch,turn_epoch,invalidation_reason=reason)

def _actor_unknown(actor_id:int,cursor:int,fight_epoch:int,turn_epoch:int)->ActorLiveSnapshot:
    vals={n:_unknown(n,cursor,'NOT_OBSERVED_IN_CURRENT_FIGHT',fight_epoch=fight_epoch,turn_epoch=turn_epoch) for n in _FIELDS}
    return ActorLiveSnapshot(actor_id,vals['cell'],vals['hp'],vals['max_hp'],vals['ap'],vals['mp'],vals['range'],vals['cooldowns'],vals['ready'])

def _actor_map(actor:ActorLiveSnapshot)->dict[str,FieldValueProof]:
    return {n:getattr(actor,n) for n in _FIELDS}

def _build_actor(actor_id:int,fields:dict[str,FieldValueProof])->ActorLiveSnapshot:
    return ActorLiveSnapshot(actor_id,*(fields[n] for n in _FIELDS))

def _payload(event:CanonicalEventEnvelope)->dict[str,str]:
    out={}
    for k,v in event.payload:
        if k in out: raise LiveStateProjectionError('STATE_DUPLICATE_PAYLOAD_KEY')
        out[k]=v
    return out

def _integer(data:dict[str,str],key:str,*,minimum:int|None=None,maximum:int|None=None)->int:
    if key not in data:raise LiveStateProjectionError('STATE_REQUIRED_PAYLOAD_MISSING:'+key)
    try:value=int(data[key])
    except Exception as exc:raise LiveStateProjectionError('STATE_INTEGER_PAYLOAD_INVALID:'+key) from exc
    if minimum is not None and value<minimum or maximum is not None and value>maximum:raise LiveStateProjectionError('STATE_INTEGER_PAYLOAD_RANGE:'+key)
    return value

def _boolean(data:dict[str,str],key:str)->bool:
    value=data.get(key,'').lower()
    if value not in ('true','false','1','0'):raise LiveStateProjectionError('STATE_BOOLEAN_PAYLOAD_INVALID:'+key)
    return value in ('true','1')

def _proof_from_dict(obj:dict)->FieldValueProof:
    return FieldValueProof(**obj)

def snapshot_from_dict(obj:dict)->LiveStateSnapshot:
    actors=[]
    for row in obj['actors']:
        actors.append(ActorLiveSnapshot(row['actor_id'],*(_proof_from_dict(row[n]) for n in _FIELDS)))
    return LiveStateSnapshot(obj['snapshot_id'],obj['account_id'],obj['client_instance_id'],obj['canonical_cursor'],obj['snapshot_revision'],
        obj['world_epoch'],obj['fight_epoch'],obj['turn_epoch'],_proof_from_dict(obj['world_map']),_proof_from_dict(obj['fight_id']),
        _proof_from_dict(obj['fight_phase']),_proof_from_dict(obj['turn_owner']),_proof_from_dict(obj['fight_map']),tuple(actors),obj['semantic_sha256'])

def _semantic_obj(*,account_id,client_instance_id,cursor,revision,world_epoch,fight_epoch,turn_epoch,world_map,fight_id,fight_phase,turn_owner,fight_map,actors):
    def p(x):
        return {'field_name':x.field_name,'value':x.value,'status':x.status,'source_event_ids':list(x.source_event_ids),'canonical_cursor':x.canonical_cursor,
                'fight_epoch':x.fight_epoch,'turn_epoch':x.turn_epoch,'authority':x.authority,'invalidation_reason':x.invalidation_reason}
    return {'account_id':account_id,'client_instance_id':client_instance_id,'canonical_cursor':cursor,'snapshot_revision':revision,'world_epoch':world_epoch,
            'fight_epoch':fight_epoch,'turn_epoch':turn_epoch,'world_map':p(world_map),'fight_id':p(fight_id),'fight_phase':p(fight_phase),'turn_owner':p(turn_owner),
            'fight_map':p(fight_map),'actors':[{'actor_id':a.actor_id,**{n:p(getattr(a,n)) for n in _FIELDS}} for a in sorted(actors,key=lambda a:a.actor_id)]}

def _snapshot(**kw)->LiveStateSnapshot:
    obj=_semantic_obj(**kw);raw=json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode();digest=sha256(raw).hexdigest()
    return LiveStateSnapshot('snap-'+digest[:32],kw['account_id'],kw['client_instance_id'],kw['cursor'],kw['revision'],kw['world_epoch'],kw['fight_epoch'],kw['turn_epoch'],
                             kw['world_map'],kw['fight_id'],kw['fight_phase'],kw['turn_owner'],kw['fight_map'],tuple(sorted(kw['actors'],key=lambda a:a.actor_id)),digest)

class StateProjector:
    reducer_revision='m7-r1'

    def validate_snapshot(self,snapshot:LiveStateSnapshot)->None:
        """Recompute the semantic identity of a deserialized snapshot.

        The SQLite row hash protects serialized bytes. This independent check
        protects the *meaning* of the snapshot and prevents a coherently
        rewritten row/hash pair from becoming runtime authority without matching
        the deterministic reducer identity.
        """
        if not isinstance(snapshot,LiveStateSnapshot):
            raise LiveStateProjectionError('STATE_SNAPSHOT_TYPE_INVALID')
        obj=_semantic_obj(account_id=snapshot.account_id,client_instance_id=snapshot.client_instance_id,
            cursor=snapshot.canonical_cursor,revision=snapshot.snapshot_revision,
            world_epoch=snapshot.world_epoch,fight_epoch=snapshot.fight_epoch,turn_epoch=snapshot.turn_epoch,
            world_map=snapshot.world_map,fight_id=snapshot.fight_id,fight_phase=snapshot.fight_phase,
            turn_owner=snapshot.turn_owner,fight_map=snapshot.fight_map,actors=snapshot.actors)
        raw=json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()
        digest=sha256(raw).hexdigest()
        if snapshot.semantic_sha256!=digest or snapshot.snapshot_id!='snap-'+digest[:32]:
            raise LiveStateProjectionError('STATE_SNAPSHOT_SEMANTIC_HASH_MISMATCH')

    def prepare(self,previous:LiveStateSnapshot|None,batch:tuple[CanonicalEventEnvelope,...])->LiveStateSnapshot:
        if not isinstance(batch,tuple) or not batch or any(not isinstance(e,CanonicalEventEnvelope) for e in batch):raise LiveStateProjectionError('STATE_COMMITTED_BATCH_REQUIRED')
        if previous is None:
            first=batch[0];account=first.account_id;client=first.client_instance_id;cursor=0;revision=0;world_epoch=0;fight_epoch=0;turn_epoch=0
            world_map=_unknown('world_map',0,'NOT_OBSERVED');fight_id=_unknown('fight_id',0,'NO_ACTIVE_FIGHT');fight_phase=_unknown('fight_phase',0,'NO_ACTIVE_FIGHT')
            turn_owner=_unknown('turn_owner',0,'NO_ACTIVE_TURN');fight_map=_unknown('fight_map',0,'NO_ACTIVE_FIGHT');actors=[]
        else:
            account=previous.account_id;client=previous.client_instance_id;cursor=previous.canonical_cursor;revision=previous.snapshot_revision
            world_epoch=previous.world_epoch;fight_epoch=previous.fight_epoch;turn_epoch=previous.turn_epoch
            world_map=previous.world_map;fight_id=previous.fight_id;fight_phase=previous.fight_phase;turn_owner=previous.turn_owner;fight_map=previous.fight_map;actors=list(previous.actors)
        amap={a.actor_id:a for a in actors}
        for e in batch:
            if (e.account_id,e.client_instance_id)!=(account,client):raise LiveStateProjectionError('STATE_ACCOUNT_CLIENT_SCOPE_MISMATCH')
            if e.canonical_cursor<=cursor:raise LiveStateProjectionError('STATE_CANONICAL_CURSOR_REORDER_OR_DUPLICATE')
            data=_payload(e);kind=e.semantic_kind
            if kind=='WORLD_MAP_OBSERVED':
                mid=_integer(data,'map_id',minimum=1);world_epoch=e.world_epoch if e.world_epoch is not None else world_epoch+(1 if world_map.value!=mid else 0)
                world_map=_known('world_map',mid,e)
            elif kind=='FIGHT_STARTED':
                fid=data.get('fight_id');
                if not fid:raise LiveStateProjectionError('STATE_FIGHT_ID_REQUIRED')
                fight_epoch=e.fight_epoch if e.fight_epoch is not None else fight_epoch+1;turn_epoch=0
                fight_id=_known('fight_id',fid,e,fight_epoch=fight_epoch);fight_phase=_known('fight_phase','ACTIVE',e,fight_epoch=fight_epoch)
                turn_owner=_unknown('turn_owner',e.canonical_cursor,'NO_TURN_OWNER_YET',fight_epoch=fight_epoch,turn_epoch=turn_epoch)
                fight_map=_known('fight_map',_integer(data,'map_id',minimum=1),e,fight_epoch=fight_epoch) if 'map_id' in data else _unknown('fight_map',e.canonical_cursor,'FIGHT_MAP_NOT_OBSERVED',fight_epoch=fight_epoch)
                amap={}
            elif kind=='FIGHT_MAP_OBSERVED':
                if fight_phase.status!='KNOWN' or fight_phase.value!='ACTIVE':raise LiveStateProjectionError('STATE_FIGHT_NOT_ACTIVE')
                fight_map=_known('fight_map',_integer(data,'map_id',minimum=1),e,fight_epoch=fight_epoch)
            elif kind=='ACTOR_SEEN':
                aid=_integer(data,'actor_id');
                if aid==0:raise LiveStateProjectionError('STATE_ACTOR_INVALID')
                amap.setdefault(aid,_actor_unknown(aid,e.canonical_cursor,fight_epoch,turn_epoch))
            elif kind in ('ACTOR_RESOURCE_ABSOLUTE','ACTOR_HP_ABSOLUTE','ACTOR_CELL_OBSERVED','ACTOR_COOLDOWN_SNAPSHOT','READY_OBSERVED'):
                aid=_integer(data,'actor_id');
                if aid not in amap:raise LiveStateProjectionError('STATE_ACTOR_UNKNOWN')
                fields=_actor_map(amap[aid])
                if kind=='ACTOR_RESOURCE_ABSOLUTE':
                    resource=data.get('resource','').upper();name={'AP':'ap','MP':'mp','RANGE':'range'}.get(resource)
                    if name is None:raise LiveStateProjectionError('STATE_RESOURCE_INVALID')
                    fields[name]=_known(name,_integer(data,'value',minimum=0,maximum=1000),e,fight_epoch=fight_epoch,turn_epoch=turn_epoch)
                elif kind=='ACTOR_HP_ABSOLUTE':
                    hp=_integer(data,'value',minimum=0);maximum=_integer(data,'maximum',minimum=0)
                    if hp>maximum:raise LiveStateProjectionError('STATE_HP_RANGE_INVALID')
                    fields['hp']=_known('hp',hp,e,fight_epoch=fight_epoch,turn_epoch=turn_epoch);fields['max_hp']=_known('max_hp',maximum,e,fight_epoch=fight_epoch,turn_epoch=turn_epoch)
                elif kind=='ACTOR_CELL_OBSERVED':fields['cell']=_known('cell',_integer(data,'cell_id',minimum=0,maximum=100000),e,fight_epoch=fight_epoch,turn_epoch=turn_epoch)
                elif kind=='ACTOR_COOLDOWN_SNAPSHOT':fields['cooldowns']=_known('cooldowns',data.get('cooldowns','[]'),e,fight_epoch=fight_epoch,turn_epoch=turn_epoch)
                else:fields['ready']=_known('ready',_boolean(data,'ready'),e,fight_epoch=fight_epoch,turn_epoch=turn_epoch)
                amap[aid]=_build_actor(aid,fields)
            elif kind=='TURN_STARTED':
                aid=_integer(data,'actor_id');
                if aid not in amap:raise LiveStateProjectionError('STATE_TURN_ACTOR_UNKNOWN')
                if turn_owner.status=='KNOWN':raise LiveStateProjectionError('STATE_TURN_ALREADY_ACTIVE')
                turn_epoch=e.turn_epoch if e.turn_epoch is not None else turn_epoch+1
                turn_owner=_known('turn_owner',aid,e,fight_epoch=fight_epoch,turn_epoch=turn_epoch)
                # Do NOT stale absolute AP/MP simply because TURN_STARTED arrived.
                # A valid same-fight absolute snapshot just before this event can remain usable.
            elif kind=='TURN_ENDED':
                aid=_integer(data,'actor_id')
                if turn_owner.status!='KNOWN' or turn_owner.value!=aid:raise LiveStateProjectionError('STATE_TURN_END_OWNER_MISMATCH')
                fields=_actor_map(amap[aid])
                for name in ('ap','mp','cooldowns'):
                    if fields[name].status=='KNOWN':fields[name]=_stale(fields[name],e.canonical_cursor,'TURN_ENDED',fight_epoch=fight_epoch,turn_epoch=turn_epoch)
                amap[aid]=_build_actor(aid,fields);turn_owner=_unknown('turn_owner',e.canonical_cursor,'TURN_ENDED',fight_epoch=fight_epoch,turn_epoch=turn_epoch)
            elif kind=='FIGHT_ENDED':
                if fight_phase.status!='KNOWN' or fight_phase.value!='ACTIVE':raise LiveStateProjectionError('STATE_FIGHT_NOT_ACTIVE')
                fight_phase=_known('fight_phase','ENDED',e,fight_epoch=fight_epoch);turn_owner=_unknown('turn_owner',e.canonical_cursor,'FIGHT_ENDED',fight_epoch=fight_epoch,turn_epoch=turn_epoch)
                if fight_map.status=='KNOWN':fight_map=_stale(fight_map,e.canonical_cursor,'FIGHT_ENDED',fight_epoch=fight_epoch,turn_epoch=turn_epoch)
                for aid,a in list(amap.items()):
                    fields=_actor_map(a)
                    for name in _FIELDS:
                        if fields[name].status=='KNOWN':fields[name]=_stale(fields[name],e.canonical_cursor,'FIGHT_ENDED',fight_epoch=fight_epoch,turn_epoch=turn_epoch)
                    amap[aid]=_build_actor(aid,fields)
            elif kind=='WORLD_REENTRY':
                mid=_integer(data,'map_id',minimum=1);world_epoch=e.world_epoch if e.world_epoch is not None else world_epoch+1
                world_map=_known('world_map',mid,e);fight_id=_unknown('fight_id',e.canonical_cursor,'WORLD_REENTRY');fight_phase=_unknown('fight_phase',e.canonical_cursor,'WORLD_REENTRY')
                turn_owner=_unknown('turn_owner',e.canonical_cursor,'WORLD_REENTRY');fight_map=_unknown('fight_map',e.canonical_cursor,'WORLD_REENTRY');amap={}
            else:raise LiveStateProjectionError('STATE_SEMANTIC_KIND_UNSUPPORTED:'+kind)
            cursor=e.canonical_cursor;revision+=1
        return _snapshot(account_id=account,client_instance_id=client,cursor=cursor,revision=revision,world_epoch=world_epoch,fight_epoch=fight_epoch,turn_epoch=turn_epoch,
                         world_map=world_map,fight_id=fight_id,fight_phase=fight_phase,turn_owner=turn_owner,fight_map=fight_map,actors=tuple(amap.values()))
