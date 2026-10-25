"""P44 retained native-source integrity check. No compile, install or launch."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path


def audit_bridge_source(root: Path) -> dict:
    """Verify exact supplied native files against the archived handoff receipt.

    A SHA-256 inventory is a tamper check for a known local release, not
    authentication of an unknown download or evidence of a working Unity DLL.
    """
    path = root / 'provenance/P44_native_bridge_source.json'
    try:
        obj = json.loads(path.read_text(encoding='utf8'))
        if obj.get('schema_version') != 1 or obj.get('mode') != 'SOURCE_ONLY_NO_BUILD_NO_INSTALL_NO_INPUT':
            raise ValueError('INVALID_NATIVE_BRIDGE_MANIFEST')
        files = obj['files']
        if type(files) is not list or len(files) < 12:
            raise ValueError('INCOMPLETE_NATIVE_BRIDGE_MANIFEST')
        seen = set()
        root_real = root.resolve()
        for entry in files:
            name = entry['path']
            expected = entry['sha256']
            if type(name) is not str or not name.startswith('native/unity_bridge/') or name in seen:
                raise ValueError('UNSAFE_BRIDGE_SOURCE_PATH')
            seen.add(name)
            file = (root / name).resolve()
            if not file.is_relative_to(root_real / 'native/unity_bridge') or not file.is_file():
                raise ValueError('MISSING_OR_OUTSIDE_BRIDGE_SOURCE')
            if file.suffix not in {'.cs','.csproj','.md'}:
                raise ValueError('UNSUPPORTED_BRIDGE_SOURCE_TYPE')
            if not isinstance(expected,str) or len(expected)!=64 or hashlib.sha256(file.read_bytes()).hexdigest()!=expected:
                raise ValueError('BRIDGE_SOURCE_HASH_MISMATCH')
            if entry.get('legacy_provenance_matches') is False:
                raise ValueError('LEGACY_BRIDGE_SOURCE_DRIFT')
        return {'status':'HISTORICAL_SOURCE_INTEGRITY_PASS','file_count':len(files),
                'compiled':False,'installed':False,'runtime_validated':False,
                'input_certified':False}
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('BRIDGE_SOURCE_AUDIT_FAILED:'+type(exc).__name__) from exc
