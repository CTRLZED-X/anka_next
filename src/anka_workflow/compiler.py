"""Compile strict mission intent against internal, provenance-bound route assets."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path

from anka_contracts.workflow import EffectiveMissionPlan, MissionConfigSpec, RoutePlan


class MissionCompileError(ValueError):
    pass


def load_route_plan(asset_path: Path, route_id: str) -> RoutePlan:
    try:
        raw=Path(asset_path).read_bytes(); data=json.loads(raw)
    except (OSError,UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise MissionCompileError(f'ROUTE_ASSET_INVALID:{type(exc).__name__}') from exc
    if not isinstance(data,dict) or data.get('schema_version')!=1 or set(data)!={'schema_version','routes'} or not isinstance(data['routes'],dict):
        raise MissionCompileError('ROUTE_ASSET_SCHEMA_INVALID')
    route=data['routes'].get(route_id)
    if not isinstance(route,dict):raise MissionCompileError('ROUTE_NOT_FOUND')
    required={'start','steps','loop','legacy_source_member','legacy_source_sha256','authority'}
    if set(route)!=required or route.get('authority')!='HISTORICAL_ROUTE_REFERENCE_ONLY':
        raise MissionCompileError('ROUTE_ASSET_ENTRY_INVALID')
    start=route['start'];steps=route['steps']
    if not isinstance(start,list) or len(start)!=2 or any(type(x) is not int for x in start):
        raise MissionCompileError('ROUTE_START_INVALID')
    if not isinstance(steps,list) or not steps or any(x not in ('U','D','L','R') for x in steps) or len(steps)>512:
        raise MissionCompileError('ROUTE_STEPS_INVALID')
    if type(route['loop']) is not bool:
        raise MissionCompileError('ROUTE_LOOP_INVALID')
    legacy_hash=route['legacy_source_sha256']
    if type(legacy_hash) is not str or len(legacy_hash)!=64 or any(c not in '0123456789abcdef' for c in legacy_hash):
        raise MissionCompileError('ROUTE_PROVENANCE_INVALID')
    return RoutePlan(route_id,start[0],start[1],tuple(steps),route['loop'],sha256(raw).hexdigest())


def compile_mission(config: MissionConfigSpec, route_asset_path: Path, *, watchdog_budget_ticks: int = 5, recovery_budget: int = 2) -> EffectiveMissionPlan:
    if not isinstance(config,MissionConfigSpec):raise MissionCompileError('MISSION_CONFIG_CONTRACT_REQUIRED')
    route=load_route_plan(route_asset_path,config.route_id)
    if type(watchdog_budget_ticks) is not int or not 1<=watchdog_budget_ticks<=100000:raise MissionCompileError('WATCHDOG_BUDGET_INVALID')
    if type(recovery_budget) is not int or not 0<=recovery_budget<=100:raise MissionCompileError('RECOVERY_BUDGET_INVALID')
    identity=sha256(json.dumps({'config':config.config_sha256,'route':route.source_sha256,'watchdog':watchdog_budget_ticks,'recovery':recovery_budget},sort_keys=True,separators=(',',':')).encode()).hexdigest()[:24]
    return EffectiveMissionPlan('missionplan-'+identity,config,route,watchdog_budget_ticks,recovery_budget)
