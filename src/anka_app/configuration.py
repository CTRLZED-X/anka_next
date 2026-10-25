"""Strict, dependency-free user JSON compiler; no ambiguous mission-file precedence."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
import json
import re

class ConfigurationError(ValueError):
    pass


def _pairs(pairs: list[tuple[str,Any]]) -> dict[str,Any]:
    out={}
    for key,value in pairs:
        if key in out: raise ConfigurationError(f'DUPLICATE_JSON_KEY:{key}')
        out[key]=value
    return out


def _keys(data: Any, allowed: set[str], context: str) -> None:
    if not isinstance(data, dict): raise ConfigurationError(f'NOT_OBJECT:{context}')
    extras=set(data)-allowed
    if extras: raise ConfigurationError(f'UNKNOWN_KEYS:{context}:{",".join(sorted(extras))}')


def _integer(value:Any, name:str, lo:int, hi:int)->int:
    if type(value) is not int or not lo<=value<=hi:
        raise ConfigurationError(f'INVALID_INTEGER:{name}:{lo}..{hi}')
    return value


@dataclass(frozen=True,slots=True)
class Player:
    name: str
    role: str


@dataclass(frozen=True,slots=True)
class Mission:
    route_id: str
    min_monsters: int
    max_monsters: int
    target_wins: int
    max_attempts: int
    stop_on_loss: bool
    stop_on_unknown: bool


@dataclass(frozen=True,slots=True)
class CaptureConfiguration:
    server_ports: tuple[int,...]
    interface: str | None = None
    duration_seconds: int = 10
    save_raw_evidence: bool = False


@dataclass(frozen=True,slots=True)
class RunConfiguration:
    schema_version: int
    players: tuple[Player,...]
    mission: Mission
    capture: CaptureConfiguration
    sha256: str


def load_user_config(path: Path) -> RunConfiguration:
    try:
        raw=Path(path).read_bytes()
        data=json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=lambda x: (_ for _ in ()).throw(ConfigurationError('INVALID_JSON_CONSTANT')))
    except (OSError,UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise ConfigurationError(f'INVALID_JSON:{type(exc).__name__}') from exc
    _keys(data, {'schema_version','players','mission','capture'},'root')
    if data.get('schema_version') != 1 or type(data.get('schema_version')) is not int: raise ConfigurationError('UNSUPPORTED_CONFIG_SCHEMA')
    users=data.get('players')
    if not isinstance(users,list) or not 1<=len(users)<=8:raise ConfigurationError('INVALID_PLAYER_COUNT')
    names=set(); players=[]; leaders=0
    for idx,item in enumerate(users):
        _keys(item, {'name','role'}, f'players[{idx}]')
        name=item.get('name');role=item.get('role')
        if not isinstance(name,str) or not (2<=len(name)<=40) or any(ord(c)<32 or c in '/\\' for c in name) or not name.strip():
            raise ConfigurationError(f'INVALID_PLAYER_NAME:{idx}')
        if role not in ('leader','follower'):raise ConfigurationError(f'INVALID_ROLE:{idx}')
        norm=name.strip().casefold()
        if norm in names: raise ConfigurationError(f'DUPLICATE_PLAYER:{idx}')
        names.add(norm);players.append(Player(name.strip(),role)); leaders+= role=='leader'
    if leaders!=1:raise ConfigurationError('REQUIRES_EXACTLY_ONE_LEADER')
    m=data.get('mission');_keys(m,{'route_id','min_monsters','max_monsters','target_wins','max_attempts','stop_on_loss','stop_on_unknown'},'mission')
    route=m.get('route_id')
    if not isinstance(route,str) or not re.fullmatch(r'[a-z][a-z0-9_-]{1,63}',route):raise ConfigurationError('INVALID_ROUTE_ID')
    low=_integer(m.get('min_monsters'),'min_monsters',1,8)
    high=_integer(m.get('max_monsters'),'max_monsters',1,8)
    if low>high:raise ConfigurationError('INVALID_MONSTER_RANGE')
    wins=_integer(m.get('target_wins'),'target_wins',1,100)
    attempts=_integer(m.get('max_attempts'),'max_attempts',1,1000)
    if wins>attempts:raise ConfigurationError('WINS_EXCEED_ATTEMPTS')
    for k in ('stop_on_loss','stop_on_unknown'):
        if type(m.get(k)) is not bool:raise ConfigurationError('MISSING_EXPLICIT_SAFETY_POLICY:'+k)
    capture=data.get('capture', {'server_ports':[]})
    _keys(capture,{'server_ports','interface','duration_seconds','save_raw_evidence'},'capture')
    ports=capture.get('server_ports',[])
    if not isinstance(ports,list) or len(ports)>32:
        raise ConfigurationError('INVALID_CAPTURE_PORTS')
    if any(type(x) is not int or not 1<=x<=65535 for x in ports) or len(set(ports))!=len(ports):
        raise ConfigurationError('INVALID_CAPTURE_PORTS')
    interface=capture.get('interface')
    if interface is not None and (not isinstance(interface,str) or not 1<=len(interface)<=255 or any(ord(c)<32 for c in interface) or interface.strip()!=interface):
        raise ConfigurationError('INVALID_CAPTURE_INTERFACE')
    duration=_integer(capture.get('duration_seconds',10),'duration_seconds',1,60)
    save_raw = capture.get('save_raw_evidence', False)
    if type(save_raw) is not bool: raise ConfigurationError('CAPTURE_RAW_EVIDENCE_CONSENT_INVALID')
    return RunConfiguration(1,tuple(players), Mission(route,low,high,wins,attempts,m['stop_on_loss'],m['stop_on_unknown']), CaptureConfiguration(tuple(ports),interface,duration,save_raw),sha256(raw).hexdigest())
