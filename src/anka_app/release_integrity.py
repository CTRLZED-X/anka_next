"""Fast fail-closed release integrity checks for setup/start.

The user-owned ``config/user.json`` is intentionally mutable and is validated
separately by the strict configuration compiler. Runtime outputs and virtual
environments are outside release integrity. Runtime integrity deliberately verifies only files that can affect execution or
authority. Documentation, tests and sealed verification receipts are package
evidence and are verified by ``tools/verify_release_offline.py`` instead. This
prevents a regenerated non-runtime receipt from becoming gameplay/startup authority.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json

_MUTABLE_PATHS=frozenset({'config/user.json'})
_EXECUTABLE_SUFFIXES=frozenset({'.py','.pyw','.bat','.cmd','.ps1','.dll','.pyd','.so'})
_PROTECTED_ROOTS=frozenset({'src','tools','native','assets','provenance','qualification','config','reference'})
_EXCLUDED_PARTS=frozenset({'__pycache__','.pytest_cache','.venv','runtime','.git'})

_RUNTIME_ROOTS=frozenset({'src','tools','native','assets','provenance','qualification'})
_RUNTIME_ROOT_FILES=frozenset({'setup.bat','start.bat','pyproject.toml','requirements-p1.txt',
                               'requirements-windows-capture.txt','PROJECT_INFO.txt'})
_RUNTIME_REFERENCE_PREFIXES=('reference/protocol/','reference/calibration/')
_RUNTIME_CONFIG_PREFIXES=('config/schema/','config/user.example.json')

def _runtime_immutable(rel:str)->bool:
    if rel in _MUTABLE_PATHS:return False
    parts=Path(rel).parts
    if not parts:return False
    if rel in _RUNTIME_ROOT_FILES:return True
    if parts[0] in _RUNTIME_ROOTS:return True
    if rel.startswith(_RUNTIME_REFERENCE_PREFIXES):return True
    if rel.startswith(_RUNTIME_CONFIG_PREFIXES):return True
    return False


def _sha(path:Path)->str:
    h=sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def manifest_sha256(root:Path)->str:
    path=Path(root)/'RELEASE_MANIFEST.json'
    if not path.is_file():raise ValueError('RELEASE_MANIFEST_MISSING')
    return _sha(path)


@dataclass(frozen=True,slots=True)
class ReleaseIntegrity:
    status:str
    release_id:str|None
    manifest_sha256:str|None
    checked_files:int
    missing_files:tuple[str,...]
    mismatched_files:tuple[str,...]
    unexpected_executable_files:tuple[str,...]

    def safe_receipt(self)->dict:
        return {
            'status':self.status,'release_id':self.release_id,
            'manifest_sha256':self.manifest_sha256,
            'checked_files':self.checked_files,
            'missing_count':len(self.missing_files),
            'mismatch_count':len(self.mismatched_files),
            'unexpected_executable_count':len(self.unexpected_executable_files),
            # Paths are intentionally omitted from normal diagnostics. The exact
            # local mismatch remains available to developer verification only.
        }


def verify_release_integrity(root:Path,*,max_manifest_bytes:int=2_000_000,max_files:int=5000)->ReleaseIntegrity:
    root=Path(root)
    manifest_path=root/'RELEASE_MANIFEST.json'
    if not manifest_path.is_file():
        return ReleaseIntegrity('FAIL',None,None,0,('RELEASE_MANIFEST.json',),(),())
    try:
        if manifest_path.stat().st_size>max_manifest_bytes:raise ValueError('RELEASE_MANIFEST_OVERSIZED')
        raw=manifest_path.read_bytes();manifest=json.loads(raw.decode('utf8'))
        if manifest.get('schema_version')!=1 or not isinstance(manifest.get('release_id'),str):
            raise ValueError('RELEASE_MANIFEST_SCHEMA_INVALID')
        entries=manifest.get('files')
        if not isinstance(entries,list) or not 1<=len(entries)<=max_files:
            raise ValueError('RELEASE_MANIFEST_FILE_LIST_INVALID')
        expected={}
        for entry in entries:
            if not isinstance(entry,dict):raise ValueError('RELEASE_MANIFEST_ENTRY_INVALID')
            rel=entry.get('path');digest=entry.get('sha256');size=entry.get('size')
            rel_path=Path(rel) if isinstance(rel,str) else None
            if (not isinstance(rel,str) or not rel or rel_path is None or rel_path.is_absolute() or rel.startswith('/')
                    or '\\' in rel or ':' in rel or '..' in rel_path.parts
                    or not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest)
                    or type(size) is not int or size<0 or rel in expected):
                raise ValueError('RELEASE_MANIFEST_ENTRY_INVALID')
            expected[rel]=(digest,size)
    except (OSError,UnicodeError,json.JSONDecodeError,ValueError):
        return ReleaseIntegrity('FAIL',None,_sha(manifest_path) if manifest_path.is_file() else None,0,(),('MANIFEST_INVALID',),())

    missing=[];mismatch=[];checked=0
    for rel,(digest,size) in expected.items():
        if not _runtime_immutable(rel):continue
        path=root/rel
        if not path.is_file():missing.append(rel);continue
        try:
            if path.stat().st_size!=size or _sha(path)!=digest:mismatch.append(rel)
            checked+=1
        except OSError:mismatch.append(rel)

    # Detect unexpected executable/importable content under protected roots. A
    # benign README or local note is not a runtime-integrity defect.
    unexpected=[]
    for protected in _PROTECTED_ROOTS:
        base=root/protected
        if not base.exists():continue
        for path in base.rglob('*'):
            if not path.is_file() or any(part in _EXCLUDED_PARTS for part in path.parts):continue
            rel=path.relative_to(root).as_posix()
            if not _runtime_immutable(rel):continue
            if rel in expected:continue
            if path.suffix.casefold() in _EXECUTABLE_SUFFIXES:unexpected.append(rel)
    status='PASS' if not missing and not mismatch and not unexpected else 'FAIL'
    return ReleaseIntegrity(status,manifest['release_id'],sha256(raw).hexdigest(),checked,
                            tuple(sorted(missing)[:32]),tuple(sorted(mismatch)[:32]),tuple(sorted(unexpected)[:32]))
