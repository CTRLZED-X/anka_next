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
    source_digest=data.get('source_sha256')
    if (type(source_digest) is not str or len(source_digest)!=64
            or any(ch not in '0123456789abcdef' for ch in source_digest)):
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
    status=data.get('status','UNKNOWN')
    if type(status) is not str or not status:
        raise ValueError('INVALID_CALIBRATION_STATUS')
    # Historical status cannot be silently promoted into a current certification.
    historical=status=='HISTORICAL_COORDINATES_NOT_LIVE_CERTIFIED'
    if current_client_certified and historical:
        raise ValueError('HISTORICAL_CALIBRATION_CANNOT_SELF_CERTIFY_CURRENT_CLIENT')
    if current_client_certified and source_path is None:
        raise ValueError('CURRENT_CALIBRATION_SOURCE_PROVENANCE_REQUIRED')
    # The evidence generation must change when authority-relevant external
    # calibration evidence changes even if the JSON profile bytes are identical.
    generation_material=(
        digest+'|dpi='+(str(expected_dpi) if expected_dpi is not None else 'NONE')
        +'|current='+('1' if current_client_certified else '0')
    ).encode('ascii')
    evidence_generation=max(1,int(sha256(generation_material).hexdigest()[:15],16))
    return CalibrationProfileEvidence(
        profile_id=f"cal-{digest[:20]}", profile_sha256=digest, source_sha256=source_digest,
        generation=evidence_generation, width=size['width'], height=size['height'],
        expected_dpi=expected_dpi, spell_slots=_point_tuple(slots,numeric_key=True),
        controls=_point_tuple(controls), directions=_point_tuple(directions),
        status=status, current_client_certified=current_client_certified)
