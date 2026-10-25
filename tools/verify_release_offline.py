"""Offline M12 release/package verifier. Never invokes physical input."""
from __future__ import annotations
from pathlib import Path, PurePosixPath
from hashlib import sha256
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from anka_app.architecture_guard import audit_source_boundaries
from anka_app.configuration import load_user_config
from tools.verification_common import implementation_source_hash
from tools.build_release import release_files


def sha(path):
 h=sha256()
 with Path(path).open('rb') as f:
  for c in iter(lambda:f.read(1024*1024),b''):h.update(c)
 return h.hexdigest()

def _valid_sha256(value:object)->bool:
 return isinstance(value,str) and len(value)==64 and all(ch in '0123456789abcdef' for ch in value)

def _safe_relative_path(value:object)->bool:
 if not isinstance(value,str) or not value or '\\' in value:
  return False
 path=PurePosixPath(value)
 return not path.is_absolute() and '..' not in path.parts and '.' not in path.parts

def undeclared_release_files(root:Path, manifest:dict)->tuple[str,...]:
    """Return package files that exist now but are absent from the sealed manifest."""
    if not isinstance(manifest,dict):
        return ()
    rows=manifest.get('files',())
    if not isinstance(rows,list):
        rows=()
    declared={row.get('path') for row in rows if isinstance(row,dict) and isinstance(row.get('path'),str)}
    current={rel.as_posix() for _path,rel in release_files(Path(root))}
    return tuple(sorted(current-declared))

def release_manifest_integrity_failures(root:Path, manifest:object)->tuple[str,...]:
    """Validate manifest structure plus the sealed package file set without crashing."""
    if not isinstance(manifest,dict):
        return ('manifest_shape',)
    failures=[]
    rows=manifest.get('files')
    if not isinstance(rows,list):
        return ('files_shape',)
    expected_count=manifest.get('release_file_count')
    if not isinstance(expected_count,int) or isinstance(expected_count,bool) or expected_count!=len(rows):
        failures.append('file_count')
    seen=set();normalized=[]
    for index,row in enumerate(rows):
        if not isinstance(row,dict):
            failures.append(f'file_row_shape:{index}');continue
        rel=row.get('path');size=row.get('size');digest=row.get('sha256')
        if not _safe_relative_path(rel):
            failures.append(f'file_path_invalid:{index}');continue
        if rel in seen:
            failures.append('duplicate_file:'+rel);continue
        seen.add(rel)
        if not isinstance(size,int) or isinstance(size,bool) or size<0:
            failures.append('file_size_invalid:'+rel);continue
        if not _valid_sha256(digest):
            failures.append('file_hash_invalid:'+rel);continue
        normalized.append(row)
        f=Path(root)/rel
        if not f.is_file() or f.stat().st_size!=size or sha(f)!=digest:
            failures.append('file:'+rel)
    if len(normalized)==len(rows):
        aggregate=sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if manifest.get('release_content_sha256')!=aggregate:
            failures.append('release_content_hash')
    extra=undeclared_release_files(Path(root),manifest)
    failures.extend('undeclared:'+name for name in extra[:10])
    return tuple(failures)

def _load_json_object(path:Path):
    try:
        value=json.loads(path.read_text(encoding='utf8'))
    except (OSError,UnicodeError,json.JSONDecodeError):
        return None
    return value if isinstance(value,dict) else None

def main():
 p=ROOT/'RELEASE_MANIFEST.json'
 if not p.is_file():print('M12_RELEASE FAIL missing manifest');return 1
 m=_load_json_object(p)
 if m is None:
  print('M12_RELEASE FAIL files=0 gates=10 architecture_violations=UNKNOWN physical_input_count=0')
  print('FAILURES='+json.dumps(['manifest_invalid']))
  return 1
 fail=list(release_manifest_integrity_failures(ROOT,m))
 if m.get('acceptance_tier')!='ZERO_INPUT_INTEGRATED' or m.get('live_action_ready') is not False:fail.append('acceptance_tier')
 gates=m.get('quality_gates')
 if not isinstance(gates,dict):
  fail.append('quality_gates_shape');gates={}
 source_hash=None
 for gate in range(10):
  q=gates.get(f'Q{gate}')
  if not isinstance(q,dict) or q.get('status')!='PASS':
   fail.append('gate:'+str(gate));continue
  qpath=q.get('path');qdigest=q.get('sha256')
  if not _safe_relative_path(qpath) or not _valid_sha256(qdigest):
   fail.append('gate_receipt_invalid:'+str(gate));continue
  receipt_path=ROOT/qpath
  if not receipt_path.is_file() or sha(receipt_path)!=qdigest:
   fail.append('gate_hash:'+str(gate));continue
  if gate>=1:
   receipt=_load_json_object(receipt_path)
   if receipt is None:
    fail.append('gate_receipt_json:'+str(gate));continue
   if source_hash is None:source_hash=implementation_source_hash()
   if receipt.get('source_tree_sha256')!=source_hash:fail.append('gate_stale:'+str(gate))
 arch=audit_source_boundaries(ROOT/'src')
 if arch.violations:fail.append('architecture')
 try:
  cfg=load_user_config(ROOT/'config/user.json')
 except Exception:
  fail.append('operator_config_invalid');cfg=None
 if cfg is not None and cfg.capture.server_ports:fail.append('operator_capture_override')
 if sorted(x.name for x in ROOT.glob('*.bat'))!=['setup.bat','start.bat']:fail.append('operator_bats')
 forbidden=('flask','fastapi','django','streamlit','gradio','dash')
 try:deps=(ROOT/'pyproject.toml').read_text(encoding='utf8').lower()
 except (OSError,UnicodeError):deps='';fail.append('pyproject_unreadable')
 if any(x in deps for x in forbidden):fail.append('ui_dependency')
 rows=m.get('files') if isinstance(m.get('files'),list) else []
 print('M12_RELEASE '+('PASS' if not fail else 'FAIL')+f' files={len(rows)} gates=10 architecture_violations={len(arch.violations)} physical_input_count=0')
 if fail:print('FAILURES='+json.dumps(fail[:20]));return 1
 return 0
if __name__=='__main__':raise SystemExit(main())
