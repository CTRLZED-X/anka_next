"""Validate inherited geometry as reference data; never authorize a click."""
from pathlib import Path
import json
from hashlib import sha256


def audit_calibration(path:Path,legacy_yaml:Path)->dict:
    data=json.loads(path.read_text(encoding='utf8'))
    w=data['client_size']['width'];h=data['client_size']['height']
    slots=data['spell_slots']
    if len(slots)!=22 or set(slots)!={str(x) for x in range(1,23)}:
        raise ValueError('INVALID_SPELL_SLOT_COUNT')
    if set(data['controls'])!={'JOIN_FIGHT','PHASE_BUTTON'}:
        raise ValueError('MISSING_PHASE_OR_JOIN_BUTTON')
    if data['source_sha256']!=sha256(legacy_yaml.read_bytes()).hexdigest():
        raise ValueError('SOURCE_CALIBRATION_HASH_MISMATCH')
    for key,item in list(slots.items())+list(data['controls'].items())+list(data['directions'].items()):
        if type(item.get('x')) is not int or type(item.get('y')) is not int or not (0<=item['x']<w and 0<=item['y']<h):
            raise ValueError('POINT_OUT_OF_BOUNDS:'+key)
        if item.get('verified') is not True:raise ValueError('UNVERIFIED_REFERENCE_POINT:'+key)
    return {'status':'HISTORICAL_COORDINATES_VALID','live_certified':False,'spell_slots':len(slots),
            'controls':sorted(data['controls']), 'source_sha256':data['source_sha256']}
