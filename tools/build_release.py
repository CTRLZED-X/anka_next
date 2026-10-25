"""Build a deterministic ANKA_NEXT release manifest and ZIP.

Runtime outputs, local virtual environments and caches are deliberately excluded.
The generated manifest is itself included in the ZIP but is not self-hashed.
"""
from __future__ import annotations
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile,ZipInfo,ZIP_DEFLATED
import argparse,json,sys

ROOT=Path(__file__).resolve().parents[1]
EXCLUDED_TOP={'.git','.venv','.pytest_cache','.mypy_cache','.ruff_cache','.tox','.nox','htmlcov','build','dist','runtime'}
EXCLUDED_ROOT_PREFIXES=('.coverage',)
EXCLUDED_SUFFIX={'.pyc','.pyo'}
RELEASE_ID='ANKA_NEXT_M12_006'
ZIP_ROOT=Path(RELEASE_ID)


def sha(path:Path)->str:
    h=sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def release_files(root:Path):
    for p in sorted(root.rglob('*')):
        if not p.is_file():continue
        rel=p.relative_to(root)
        if rel.parts[0] in EXCLUDED_TOP or '__pycache__' in rel.parts:continue
        if len(rel.parts)==1 and p.name.startswith(EXCLUDED_ROOT_PREFIXES):continue
        if p.is_symlink():
            raise ValueError(f'RELEASE_SYMLINK_UNSUPPORTED:{rel.as_posix()}')
        if p.suffix in EXCLUDED_SUFFIX:continue
        rels=rel.as_posix()
        if rels=='RELEASE_MANIFEST.json':continue
        # Checkpoint files are mutable verifier work state, not release evidence.
        # Shipping them makes an otherwise deterministic release manifest stale as
        # soon as a gate is resumed/replayed. Only sealed receipts belong in ZIPs.
        # Hidden files under verification/ are mutable verifier work-state
        # (checkpoints, temporary progress, local caches), never sealed evidence.
        # Release receipts are ordinary visible JSON files and remain included.
        if rel.parts and rel.parts[0]=='verification' and p.name.startswith('.'):continue
        yield p,rel


def _validate_windows_release_paths(files:list[dict])->None:
    seen={}
    for row in files:
        path=row['path'];key=path.casefold()
        prior=seen.get(key)
        if prior is not None and prior!=path:
            raise ValueError(f'RELEASE_WINDOWS_PATH_COLLISION:{prior}:{path}')
        seen[key]=path

def build_manifest(root:Path=ROOT)->dict:
    files=[{'path':rel.as_posix(),'sha256':sha(p),'size':p.stat().st_size} for p,rel in release_files(root)]
    _validate_windows_release_paths(files)
    receipts={}
    for gate in range(10):
        found=sorted((root/'verification').glob(f'Q{gate}_*receipt.json'))
        if found:
            obj=json.loads(found[-1].read_text())
            receipts[f'Q{gate}']={'status':obj.get('status'),'path':found[-1].relative_to(root).as_posix(),'sha256':sha(found[-1])}
    source_digest=sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {
        'schema_version':1,'release_id':RELEASE_ID,
        'acceptance_tier':'ZERO_INPUT_INTEGRATED',
        'live_action_ready':False,'physical_input_default':'DISABLED',
        'python_requirement':'>=3.13,<3.14',
        'dependency_manifests':{name:sha(root/name) for name in ('pyproject.toml','requirements-p1.txt','requirements-windows-capture.txt')},
        'config_schema_sha256':sha(root/'config/schema/user.schema.json'),
        'operator_config_example_sha256':sha(root/'config/user.example.json'),
        'kernel_tree_reference':'Q3 receipt',
        'protocol_current_build_status':'BLOCKED_MISSING_EVIDENCE',
        'windows_acceptance_status':'BLOCKED_MISSING_EVIDENCE',
        'live_mission_status':'BLOCKED_MISSING_EVIDENCE',
        'quality_gates':receipts,
        'release_file_count':len(files),
        'release_content_sha256':source_digest,
        'files':files,
        'known_limitations':[
            'Q10 Windows clean-host acceptance has not been performed in this environment.',
            'Q11 current-build observe-only evidence is missing.',
            'Q12 physical action scopes and Q13 live mission are not accepted.',
            'Windows Npcap/Scapy backend acceptance requires Q10 evidence on the target host.'
        ],
    }


def write_manifest(root:Path=ROOT)->Path:
    p=root/'RELEASE_MANIFEST.json';p.write_text(json.dumps(build_manifest(root),indent=2,sort_keys=True)+'\n');return p


def build_zip(output:Path,root:Path=ROOT)->Path:
    manifest=write_manifest(root)
    files=list(release_files(root))+[(manifest,Path('RELEASE_MANIFEST.json'))]
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(output,'w',compression=ZIP_DEFLATED,compresslevel=9) as z:
        for p,rel in sorted(files,key=lambda x:x[1].as_posix()):
            archived=(ZIP_ROOT/rel).as_posix()
            info=ZipInfo(archived,date_time=(2026,1,1,0,0,0))
            info.compress_type=ZIP_DEFLATED;info.external_attr=0o644<<16
            z.writestr(info,p.read_bytes())
    return output


def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument('--zip',type=Path);args=ap.parse_args(argv)
    p=write_manifest();print('RELEASE_MANIFEST='+str(p))
    if args.zip:
        z=build_zip(args.zip);print('RELEASE_ZIP='+str(z));print('RELEASE_ZIP_SHA256='+sha(z))
    return 0
if __name__=='__main__':raise SystemExit(main())
