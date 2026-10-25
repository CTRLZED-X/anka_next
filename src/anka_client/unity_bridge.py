"""P44 read-only, fail-closed client for the archived Unity coordinate bridge.

A successful health match is a process/window generation *observation*, not proof
of player character identity, gameplay authority, slot binding, or input rights.
Native source is retained separately; nothing in this module installs the bridge.
"""
from __future__ import annotations
import http.client
import json
from typing import Any
from anka_contracts.client import WindowObservation
from anka_contracts.bridge import (BridgeEvidenceReader, BridgeIdentityReport,
                                   BridgeMapReport, CellProjection)

MAX_REPLY_BYTES = 2_000_000
MAX_MAP_CELLS = 560
_ALLOWED_ROUTES = frozenset({'/health', '/coordinates'})


class BridgeTransportRejected(ValueError):
    """A bridge response is unavailable, malformed or exceeds the byte budget."""


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for k, value in items:
        if k in result:
            raise BridgeTransportRejected('DUPLICATE_BRIDGE_JSON_FIELD')
        result[k] = value
    return result


class LocalLoopbackBridgeReader:
    """GET only, 127.0.0.1 only, no proxy, no executable code or game input."""
    def __init__(self, *, timeout_seconds: float = 2.0):
        if not (0 < timeout_seconds <= 5):
            raise ValueError('INVALID_BRIDGE_TIMEOUT')
        self.timeout_seconds = timeout_seconds

    def get_json(self, port: int, route: str) -> dict[str, Any]:
        if type(port) is not int or not (1 <= port <= 65535):
            raise BridgeTransportRejected('INVALID_BRIDGE_PORT')
        if route not in _ALLOWED_ROUTES:
            raise BridgeTransportRejected('BRIDGE_ROUTE_NOT_READ_ONLY')
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=self.timeout_seconds)
        try:
            conn.request('GET', route, headers={'Accept':'application/json','Connection':'close'})
            resp = conn.getresponse()
            if resp.status != 200:
                raise BridgeTransportRejected('BRIDGE_HTTP_STATUS_'+str(resp.status))
            length = resp.getheader('Content-Length')
            if length is not None:
                if not length.isdecimal() or int(length) > MAX_REPLY_BYTES:
                    raise BridgeTransportRejected('BRIDGE_REPLY_TOO_LARGE')
            body = resp.read(MAX_REPLY_BYTES+1)
            if len(body) > MAX_REPLY_BYTES:
                raise BridgeTransportRejected('BRIDGE_REPLY_TOO_LARGE')
            obj = json.loads(body.decode('utf-8'), object_pairs_hook=_pairs,
                             parse_constant=lambda _: (_ for _ in ()).throw(BridgeTransportRejected('BRIDGE_NONFINITE_JSON')))
            if type(obj) is not dict:
                raise BridgeTransportRejected('BRIDGE_NON_OBJECT_JSON')
            return obj
        except (OSError, TimeoutError, UnicodeError, json.JSONDecodeError, http.client.HTTPException) as exc:
            raise BridgeTransportRejected('BRIDGE_COMMUNICATION_FAILED:'+type(exc).__name__) from exc
        finally:
            conn.close()


def _int(obj: dict, key: str, *, minimum: int = 0) -> int:
    v = obj.get(key)
    if type(v) is not int or v < minimum:
        raise ValueError('INVALID_'+key.upper())
    return v


def _bool(obj: dict, key: str) -> bool:
    v = obj.get(key)
    if type(v) is not bool:
        raise ValueError('INVALID_'+key.upper())
    return v


class ReadOnlyBridgeInspector:
    def __init__(self, reader: BridgeEvidenceReader):
        self.reader = reader

    def inspect_identity(self, window: WindowObservation, port: int) -> BridgeIdentityReport:
        try:
            health = self.reader.get_json(port, '/health')
            pid = _int(health, 'processId', minimum=1)
            created = _int(health, 'processStartTime', minimum=1)
            bridge_port = _int(health, 'bridgePort', minimum=1)
            if pid != window.pid or created != window.process_created_100ns or bridge_port != port:
                raise ValueError('BRIDGE_WINDOW_GENERATION_MISMATCH')
            if window.hwnd <= 0 or window.minimized or min(window.client_width, window.client_height) <= 0:
                raise ValueError('WINDOW_NOT_USABLE')
            if health.get('source') != 'unity_bridge' or not _bool(health, 'available'):
                raise ValueError('BRIDGE_HEALTH_UNTRUSTED')
            m = health.get('loadedMapId')
            mg = health.get('mapGeneration')
            cg = health.get('coordinateGeneration')
            # It is legitimate for a bridge to be attached before a map loads;
            # that is a matching process, NOT a ready projection.
            return BridgeIdentityReport('PROCESS_MATCHED', 'WINDOW_GENERATION_MATCH_ONLY',
                pid, created, bridge_port, m if type(m) is int else None,
                mg if type(mg) is int else None, cg if type(cg) is int else None,
                window_process_matched=True)
        except (BridgeTransportRejected, ValueError, TypeError, KeyError, AttributeError) as exc:
            code = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            return BridgeIdentityReport('BLOCKED', code[:110])

    def inspect_coordinates(self, window: WindowObservation, port: int, *,
                            map_id: int, expected_generation: int | None = None) -> BridgeMapReport:
        """Health-read/map-read/health-read prevents stale window/map pairs.

        Returns research coordinates only, never a valid physical input target.
        """
        try:
            if type(map_id) is not int or map_id <= 0:
                raise ValueError('INVALID_EXPECTED_MAP')
            if expected_generation is not None and (type(expected_generation) is not int or expected_generation <= 0):
                raise ValueError('INVALID_EXPECTED_GENERATION')
            # Both reads must be scoped to the *same* verified OS generation.
            health0=self.reader.get_json(port, '/health')
            obs=self._health_keys(health0, window, port)
            snapshot=self.reader.get_json(port, '/coordinates')
            health1=self.reader.get_json(port, '/health')
            if self._health_keys(health1, window, port) != obs:
                raise ValueError('BRIDGE_GENERATION_CHANGED_DURING_READ')
            if obs[3] != map_id:
                raise ValueError('BRIDGE_WRONG_MAP')
            if expected_generation is not None and obs[4] != expected_generation:
                raise ValueError('BRIDGE_STALE_MAP_GENERATION')
            if snapshot.get('status') != 'MAP_COORDINATES_READY':
                raise ValueError('BRIDGE_COORDINATES_NOT_READY')
            for key, expected in zip(('projectionSignature','windowFingerprint','cameraFingerprint','cellGeometryFingerprint'), obs[6:]):
                if snapshot.get(key) != expected:
                    raise ValueError('COORDINATE_PROJECTION_SIGNATURE_MISMATCH')
            if _int(snapshot,'mapId',minimum=1) != map_id:
                raise ValueError('COORDINATE_MAP_MISMATCH')
            if _int(snapshot,'mapGeneration',minimum=1) != obs[4] or _int(snapshot,'coordinateGeneration',minimum=1) != obs[5]:
                raise ValueError('COORDINATE_GENERATION_MISMATCH')
            if not _bool(snapshot,'sourceVerified'):
                raise ValueError('COORDINATE_SOURCE_UNVERIFIED')
            w = _int(snapshot,'sourceClientWidth',minimum=1)
            h = _int(snapshot,'sourceClientHeight',minimum=1)
            if (w,h) != (window.client_width,window.client_height):
                raise ValueError('COORDINATE_WINDOW_SIZE_MISMATCH')
            cells=snapshot.get('cells')
            if type(cells) is not list or len(cells) != MAX_MAP_CELLS:
                raise ValueError('INVALID_COORDINATE_CELLS')
            if (_int(snapshot, 'totalMapCells') != MAX_MAP_CELLS or
                    _int(snapshot, 'projectableCellCount') != MAX_MAP_CELLS or
                    _int(snapshot, 'generatedCoordinateCount') != len(cells)):
                raise ValueError('COORDINATE_COUNT_MISMATCH')
            parsed=[];seen=set()
            for c in cells:
                if type(c) is not dict:
                    raise ValueError('INVALID_COORDINATE_ENTRY')
                i=_int(c,'cellId')
                if i >= MAX_MAP_CELLS or i in seen:
                    raise ValueError('DUPLICATE_OR_INVALID_CELL')
                seen.add(i)
                is_inside=_bool(c,'insideCameraViewport')
                projected=_bool(c,'projectable')
                verified=_bool(c,'sourceVerified')
                cx=c.get('clientX'); cy=c.get('clientY')
                if projected and is_inside and verified:
                    if type(cx) is not int or type(cy) is not int or not (0 <= cx < w and 0 <= cy < h):
                        raise ValueError('INVALID_CLIENT_COORDINATES')
                elif type(cx) is not int or type(cy) is not int:
                    cx=-1;cy=-1
                parsed.append(CellProjection(i,cx,cy,is_inside,verified,projected))
            return BridgeMapReport('RESEARCH_PROJECTION_ONLY','WINDOW_AND_COORDINATE_SCOPE_MATCH',
                map_id,obs[4],obs[5],(w,h),tuple(sorted(parsed,key=lambda c:c.cell_id)),True)
        except (BridgeTransportRejected, ValueError, TypeError, KeyError, AttributeError) as exc:
            code=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
            return BridgeMapReport('BLOCKED',code[:110])

    @staticmethod
    def _health_keys(h: dict, w: WindowObservation, port: int) -> tuple[int,...]:
        pid=_int(h,'processId',minimum=1)
        creation=_int(h,'processStartTime',minimum=1)
        bridge_port=_int(h,'bridgePort',minimum=1)
        map_id=_int(h,'loadedMapId',minimum=1)
        map_gen=_int(h,'mapGeneration',minimum=1)
        coord_gen=_int(h,'coordinateGeneration',minimum=1)
        if (pid,creation,bridge_port)!=(w.pid,w.process_created_100ns,port):
            raise ValueError('BRIDGE_WINDOW_GENERATION_MISMATCH')
        if w.hwnd <= 0 or w.minimized or min(w.client_width,w.client_height)<=0:
            raise ValueError('WINDOW_NOT_USABLE')
        if (h.get('status') != 'MAP_COORDINATES_READY' or h.get('source') != 'unity_bridge'
                or not _bool(h,'available') or not _bool(h,'sourceVerified')):
            raise ValueError('BRIDGE_SOURCE_UNVERIFIED')
        # The Unity bridge may have different client/window metrics after a UI
        # resize. Never map old coordinates onto a new window.
        if _int(h,'sourceClientWidth',minimum=1)!=w.client_width or _int(h,'sourceClientHeight',minimum=1)!=w.client_height:
            raise ValueError('BRIDGE_WINDOW_SIZE_MISMATCH')
        # The bridge can refresh a camera projection without changing the map.
        # Its signatures are part of the coherence fence across three reads.
        signatures = []
        for name in ('projectionSignature','windowFingerprint','cameraFingerprint','cellGeometryFingerprint'):
            value = h.get(name)
            if type(value) is not str or not value:
                raise ValueError('BRIDGE_PROJECTION_SIGNATURE_MISSING')
            signatures.append(value)
        return (pid,creation,bridge_port,map_id,map_gen,coord_gen,*signatures)
