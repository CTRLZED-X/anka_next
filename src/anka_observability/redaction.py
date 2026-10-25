"""Defense-in-depth sanitization before disk and before export.

This is not proof of perfect secrecy: only allowlisted diagnostic attributes should
be emitted. Never pass raw packets, tokens or arbitrary environment dumps to it.
"""
from __future__ import annotations
import re
import math
from typing import Any

SENSITIVE_KEYS={'password','passwd','secret','token','credential','authorization','cookie','session_key','api_key','raw_packet','pcap','private_key'}
SENSITIVE_KEY_COMPACT={'password','passwd','secret','token','credential','credentials','authorization','authorizationheader',
    'authorizationtoken','cookie','cookies','privatekey','sessionkey','apikey','accesstoken','refreshtoken','idtoken','authtoken','rawpacket','pcap'}
SENSITIVE_KEY_SUFFIXES=('password','passwd','secret','credential','token','privatekey','sessionkey','apikey')
_REDACTIONS=(
    (re.compile(r'(?i)(?:[a-z]:\\|/)(?:users|home)\\?/?[^\\/\s\"\']+'), '[LOCAL_USER_PATH]'),
    (re.compile(r'(?i)\b(?:bearer\s+)[a-z0-9._~+/-]+'), '[AUTH_TOKEN]'),
    (re.compile(r'(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b'), '[EMAIL]'),
    (re.compile(r'(?i)\b(?:password|token|api[_-]?key|authorization|secret)\s*[=:]\s*[^\s,;]+'), '[REDACTED_CREDENTIAL]'),
)


def _sensitive_key(key:Any)->bool:
    text=str(key).casefold()
    if text in SENSITIVE_KEYS:return True
    compact=re.sub(r'[^a-z0-9]+','',text)
    return compact in SENSITIVE_KEY_COMPACT or compact.endswith(SENSITIVE_KEY_SUFFIXES)


def sanitize(obj:Any, depth:int=0)->Any:
    """Bound arbitrary producer data before it enters the recorder.

    Collection truncation is explicit on the containing mapping so homogeneous
    lists (for example action rows) are never polluted with a marker of another
    type.
    """
    if depth>5:return '[NESTING_LIMIT]'
    if isinstance(obj,dict):
        items=list(obj.items())
        out={}
        truncation={}
        for k,v in items[:50]:
            key=str(k)[:64]
            if _sensitive_key(k):
                out[key]='[REDACTED]'
                continue
            if isinstance(v,(list,tuple)) and len(v)>40:
                truncation[key]=len(v)-40
            out[key]=sanitize(v,depth+1)
        if len(items)>50:truncation['__mapping_items__']=len(items)-50
        if truncation:out['__diagnostic_truncation__']=truncation
        return out
    if isinstance(obj,(list,tuple)):
        return [sanitize(x,depth+1) for x in list(obj)[:40]]
    if isinstance(obj,str):
        truncated=len(obj)>1024
        value=obj[:1024]
        for pattern,replacement in _REDACTIONS:value=pattern.sub(replacement,value)
        return value+('[DIAGNOSTIC_TRUNCATED]' if truncated else '')
    if type(obj) is float and not math.isfinite(obj):return '[NONFINITE_FLOAT]'
    if obj is None or type(obj) in (int,float,bool):return obj
    return '[UNSERIALIZABLE]'


def sanitize_export(obj:Any, depth:int=0)->Any:
    """Second-pass redaction for already-bounded internal forensic artifacts.

    Unlike :func:`sanitize`, this preserves collection cardinality so export does
    not silently change schemas such as ``actions[]`` after analysis. Inputs to
    this function are recorder rows/internal reports, not unbounded external data.
    """
    if depth>8:return '[NESTING_LIMIT]'
    if isinstance(obj,dict):
        return {str(k)[:64]:('[REDACTED]' if _sensitive_key(k) else sanitize_export(v,depth+1)) for k,v in obj.items()}
    if isinstance(obj,(list,tuple)):
        return [sanitize_export(x,depth+1) for x in obj]
    if isinstance(obj,str):
        truncated=len(obj)>4096
        value=obj[:4096]
        for pattern,replacement in _REDACTIONS:value=pattern.sub(replacement,value)
        return value+('[DIAGNOSTIC_TRUNCATED]' if truncated else '')
    if type(obj) is float and not math.isfinite(obj):return '[NONFINITE_FLOAT]'
    if obj is None or type(obj) in (int,float,bool):return obj
    return '[UNSERIALIZABLE]'


def has_diagnostic_truncation(obj:Any, depth:int=0)->bool:
    """Return whether bounded sanitization removed part of the value."""
    if depth>8:return False
    if isinstance(obj,dict):
        if '__diagnostic_truncation__' in obj:return True
        return any(has_diagnostic_truncation(v,depth+1) for v in obj.values())
    if isinstance(obj,(list,tuple)):
        return any(has_diagnostic_truncation(v,depth+1) for v in obj)
    if isinstance(obj,str):
        return obj=='[NESTING_LIMIT]' or obj.endswith('[DIAGNOSTIC_TRUNCATED]')
    return False


def safe_exception_frames(exc: BaseException, project_root, *, limit: int = 16) -> list[dict[str, Any]]:
    """Return location-only traceback evidence without source text or local values.

    Paths under the project are made relative. External paths are reduced to the
    basename so a diagnostic bundle cannot expose a Windows username/home path.
    """
    from pathlib import Path
    import traceback
    if not isinstance(exc, BaseException) or type(limit) is not int or limit < 1:
        return []
    try:
        root=Path(project_root).resolve()
        extracted=traceback.extract_tb(exc.__traceback__)[-min(limit,32):]
    except Exception:
        return []
    out=[]
    for frame in extracted:
        try:
            path=Path(frame.filename).resolve()
            try:file_name=path.relative_to(root).as_posix()
            except ValueError:file_name='<external>/'+path.name[:96]
            function=re.sub(r'[^A-Za-z0-9_.<>-]','_',str(frame.name))[:96]
            line=int(frame.lineno)
            if line<0:continue
            out.append({'file':file_name[:192],'function':function,'line':line})
        except Exception:
            continue
    return out
