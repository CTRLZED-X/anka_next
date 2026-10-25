"""Versioned calibration evidence loader for the Client system.

Historical points are useful reference evidence but never become current-client
input authority merely because their file and provenance hashes still match.
"""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
from anka_contracts.client import CalibrationProfileEvidence


def _point_tuple(items: dict, *, numeric_key: bool=False):
    result=[]
    for key,value in sorted(items.items(),key=lambda kv: int(kv[0]) if numeric_key else kv[0]):
        if type(value.get('x')) is not int or type(value.get('y')) is not int:
            raise ValueError('INVALID_CALIBRATION_POINT_TYPE')
        name=int(key) if numeric_key else str(key)
        result.append((name,value['x'],value['y']))
    return tuple(result)


def load_calibration_profile(path: Path, *, source_path: Path | None=None,
                             current_client_certified: bool=False,
                             expected_dpi: int | None=None) -> CalibrationProfileEvidence:
    raw=path.read_bytes(); digest=sha256(raw).hexdigest()
    data=json.loads(raw.decode('utf-8'))
    if (type(data) is not dict or type(data.get('schema_version')) is not int
            or data.get('schema_version') != 1):
        raise ValueError('UNSUPPORTED_CALIBRATION_SCHEMA')
    source_digest=str(data.get('source_sha256',''))
    if len(source_digest)!=64:
        raise ValueError('CALIBRATION_SOURCE_HASH_MISSING')
    if source_path is not None and sha256(source_path.read_bytes()).hexdigest()!=source_digest:
        raise ValueError('CALIBRATION_SOURCE_HASH_MISMATCH')
    size=data.get('client_size',{})
    if (type(size) is not dict or type(size.get('width')) is not int
            or type(size.get('height')) is not int):
        raise ValueError('INVALID_CALIBRATION_GEOMETRY_TYPE')
    slots=data.get('spell_slots',{}); controls=data.get('controls',{}); directions=data.get('directions',{})
    for group in (slots,controls,directions):
        if type(group) is not dict: raise ValueError('INVALID_CALIBRATION_POINTS')
        if any(type(v) is not dict or v.get('verified') is not True for v in group.values()):
            raise ValueError('UNVERIFIED_CALIBRATION_POINT')
    # Historical status cannot be silently promoted into a current certification.
    historical=data.get('status')=='HISTORICAL_COORDINATES_NOT_LIVE_CERTIFIED'
    if current_client_certified and historical:
        raise ValueError('HISTORICAL_CALIBRATION_CANNOT_SELF_CERTIFY_CURRENT_CLIENT')
    return CalibrationProfileEvidence(
        profile_id=f"cal-{digest[:20]}", profile_sha256=digest, source_sha256=source_digest,
        generation=max(1,int(digest[:15],16)), width=size['width'], height=size['height'],
        expected_dpi=expected_dpi, spell_slots=_point_tuple(slots,numeric_key=True),
        controls=_point_tuple(controls), directions=_point_tuple(directions),
        status=str(data.get('status','UNKNOWN')), current_client_certified=current_client_certified)
