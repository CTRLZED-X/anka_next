"""Internal setup helper for the optional read-only Unity bridge.

This is intentionally not a user-facing launcher. setup.bat invokes it once.
It never downloads BepInEx or game binaries. If a compatible local BepInEx
installation exists, it compiles the bundled source and installs only the ANKA
plugin after byte verification. Missing prerequisites are recorded as PENDING,
not silently ignored.
"""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
import json, os, shutil, subprocess, sys, tempfile, re

ROOT=Path(__file__).resolve().parents[1]
RECORD=ROOT/'runtime'/'bridge_setup.json'
REQUIRED=(
    ('core','BepInEx.Core.dll'),('core','BepInEx.Unity.IL2CPP.dll'),
    ('core','Il2CppInterop.Runtime.dll'),('interop','Il2Cppmscorlib.dll'),
    ('interop','UnityEngine.dll'),('interop','UnityEngine.CoreModule.dll'),
)


def _hash(path:Path)->str:
    return sha256(path.read_bytes()).hexdigest()

def _release_manifest_sha()->str|None:
    path=ROOT/'RELEASE_MANIFEST.json'
    return _hash(path) if path.is_file() else None

def _write(obj:dict)->None:
    RECORD.parent.mkdir(parents=True,exist_ok=True)
    RECORD.write_text(json.dumps(obj,sort_keys=True,indent=2)+'\n',encoding='utf8')
    print('BRIDGE_SETUP='+str(obj.get('status','UNKNOWN')))

def _detect_bepinex(env:dict[str,str]|None=None)->Path|None:
    env=os.environ if env is None else env
    explicit=env.get('BEPINEX_PATH')
    if explicit:
        p=Path(explicit).expanduser()
        return p if p.is_dir() else None
    local=env.get('LOCALAPPDATA')
    if not local:return None
    for rel in (Path('Ankama/Dofus-dofus3/BepInEx'),Path('Ankama/Dofus/BepInEx')):
        p=Path(local)/rel
        if p.is_dir():return p
    return None

def _missing(bep:Path)->list[str]:
    return [parts[-1] for parts in REQUIRED if not bep.joinpath(*parts).is_file()]

def _dofus_process_state()->str:
    """Return RUNNING/NOT_RUNNING/UNKNOWN; UNKNOWN never authorizes replacement."""
    try:
        p=subprocess.run(['tasklist','/FO','CSV','/NH'],capture_output=True,text=True,timeout=8,check=False)
        if p.returncode!=0:return 'UNKNOWN'
        names=p.stdout.casefold()
        return 'RUNNING' if any(name in names for name in ('dofus.exe','dofus-dofus3.exe','dofus unity.exe')) else 'NOT_RUNNING'
    except Exception:
        return 'UNKNOWN'

def _diagnostic_codes(*texts:str)->list[str]:
    """Extract bounded NuGet/MSBuild/compiler codes; never persist raw paths/output."""
    codes=[]
    for text in texts:
        if not isinstance(text,str):continue
        for code in re.findall(r'\b(?:NU|MSB|CS)\d{4,5}\b',text.upper()):
            if code not in codes:codes.append(code)
            if len(codes)>=8:return codes
    return codes

def prepare()->dict:
    base={'schema_version':2,'source':'ANKA_NEXT_SETUP','bridge_contract_version':4,
          'physical_input_enabled':False,'external_download_performed':False,
          'release_manifest_sha256':_release_manifest_sha()}
    if os.name!='nt': return {**base,'status':'NOT_WINDOWS'}
    bep=_detect_bepinex()
    if bep is None:return {**base,'status':'PENDING_BEPINEX_NOT_FOUND'}
    missing=_missing(bep)
    if missing:return {**base,'status':'PENDING_BEPINEX_INTEROP_INCOMPLETE','missing_files':missing}
    dotnet=shutil.which('dotnet')
    if not dotnet:return {**base,'status':'PENDING_DOTNET_SDK_NOT_FOUND'}
    try:
        sdks=subprocess.run([dotnet,'--list-sdks'],capture_output=True,text=True,timeout=15,check=False)
        if sdks.returncode or not sdks.stdout.strip():return {**base,'status':'PENDING_DOTNET_SDK_NOT_FOUND'}
    except Exception:return {**base,'status':'PENDING_DOTNET_SDK_NOT_FOUND'}
    process_state=_dofus_process_state()
    if process_state=='RUNNING':return {**base,'status':'DEFERRED_DOFUS_RUNNING','process_state':'RUNNING'}
    if process_state!='NOT_RUNNING':return {**base,'status':'PENDING_DOFUS_PROCESS_STATE_UNKNOWN','process_state':'UNKNOWN'}

    src=ROOT/'native'/'unity_bridge';proj=src/'DofusCoordinateBridge.csproj'
    if not proj.is_file():return {**base,'status':'FAILED_SOURCE_MISSING'}
    env=os.environ.copy();env['BEPINEX_PATH']=str(bep)
    try:
        restore=subprocess.run([dotnet,'restore',str(proj),'--nologo'],cwd=src,env=env,
                               capture_output=True,text=True,timeout=120,check=False)
        if restore.returncode:return {**base,'status':'PENDING_BRIDGE_RESTORE_FAILED','exit_code':restore.returncode,
                                      'diagnostic_codes':_diagnostic_codes(restore.stdout,restore.stderr)}
        build=subprocess.run([dotnet,'build',str(proj),'--configuration','Release','--framework','net6.0',
                              '--no-restore','--nologo'],cwd=src,env=env,capture_output=True,text=True,timeout=180,check=False)
        if build.returncode:return {**base,'status':'PENDING_BRIDGE_BUILD_FAILED','exit_code':build.returncode,
                                    'diagnostic_codes':_diagnostic_codes(build.stdout,build.stderr)}
    except subprocess.TimeoutExpired:return {**base,'status':'PENDING_BRIDGE_BUILD_TIMEOUT'}
    except Exception:return {**base,'status':'PENDING_BRIDGE_BUILD_ERROR'}
    built=src/'bin'/'Release'/'net6.0'/'DofusCoordinateBridge.dll'
    if not built.is_file():return {**base,'status':'FAILED_BUILD_OUTPUT_MISSING'}
    built_hash=_hash(built)
    target_dir=bep/'plugins'/'DofusCoordinateBridge';target=target_dir/'DofusCoordinateBridge.dll'
    try:
        target_dir.mkdir(parents=True,exist_ok=True)
        if target.is_file() and _hash(target)==built_hash:
            return {**base,'status':'CURRENT_BYTE_IDENTICAL','installed_sha256':built_hash}
        backup=target.with_suffix('.dll.previous')
        if target.is_file(): shutil.copy2(target,backup)
        tmp=target.with_suffix('.dll.new')
        shutil.copy2(built,tmp)
        if _hash(tmp)!=built_hash:raise OSError('COPY_HASH_MISMATCH')
        os.replace(tmp,target)
        if _hash(target)!=built_hash:raise OSError('INSTALL_HASH_MISMATCH')
        backup.unlink(missing_ok=True)
        return {**base,'status':'INSTALLED_BYTE_VERIFIED','installed_sha256':built_hash}
    except Exception:
        try:
            backup=target.with_suffix('.dll.previous')
            if backup.is_file():os.replace(backup,target)
        except Exception:pass
        return {**base,'status':'FAILED_INSTALL_OR_VERIFY','built_sha256':built_hash}

def main()->int:
    try:result=prepare()
    except Exception as exc:
        result={'schema_version':1,'status':'FAILED_INTERNAL_'+type(exc).__name__.upper(),
                'physical_input_enabled':False,'external_download_performed':False}
    try:_write(result)
    except Exception:
        print('BRIDGE_SETUP=RECORD_WRITE_FAILED')
    # Bridge availability is a later live-readiness gate; Python/offline setup
    # remains successful while the exact pending reason is preserved.
    return 0

if __name__=='__main__':raise SystemExit(main())
