"""Definitive M2 Q3 verifier for preserved Kernel + scoped game data."""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
import json, os, subprocess, sys, time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from anka_contracts.verification import VerificationCheck,VerificationCounts,VerificationReceipt
from tools.verification_common import sha256_file,tree_hash,implementation_source_hash,dependency_manifest_hash,test_fixture_hash,run_unittest_modules,environment_pairs

OUT=ROOT/'verification'/'Q3_kernel_data_receipt.json'
SELECTED=json.loads((ROOT/'reference/m2/legacy_kernel_oracle_manifest.json').read_text())['active_q3_subset']

def _counts(checks):
 return VerificationCounts(passed=sum(x.status=='PASS' for x in checks),failed=sum(x.status=='FAIL' for x in checks),skipped=sum(x.status=='SKIP' for x in checks),not_run=sum(x.status=='NOT_RUN' for x in checks),missing_evidence=sum(x.status=='MISSING_EVIDENCE' for x in checks))

def _legacy_subset():
 archive=ROOT/'reference/baselines/archives/R5_198_REFERENCE.zip'
 with TemporaryDirectory() as td:
  base=Path(td); testdir=base/'tests'; testdir.mkdir()
  with ZipFile(archive) as z:
   names=z.namelist(); prefix=names[0].split('/',1)[0]+'/' if names and '/' in names[0] else ''
   for row in SELECTED:
    data=z.read(prefix+row['path']); dest=base/row['path']; dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(data)
  env=os.environ.copy(); env['PYTHONPATH']=str(ROOT/'src')
  files=[str(base/row['path']) for row in SELECTED]
  p=subprocess.run([sys.executable,'-m','pytest','-q','--disable-warnings',*files],cwd=base,env=env,capture_output=True,text=True,timeout=20)
  # Parse pytest's final "N passed" text; selected tests are deterministic and have no skips today.
  import re
  m=re.search(r'(\d+) passed',p.stdout)
  passed=int(m.group(1)) if m else 0
  return {'returncode':p.returncode,'passed':passed,'output':(p.stdout+p.stderr)[-3000:]}

def main():
 started=time.monotonic(); checks=[]
 kp=json.loads((ROOT/'reference/m2/kernel_reuse_provenance.json').read_text())
 kernel_ok=kp['file_count']==137 and all(r['byte_identical'] and (ROOT/r['target_path']).is_file() and sha256_file(ROOT/r['target_path'])==r['legacy_sha256'] for r in kp['files'])
 checks.append(VerificationCheck('Q3_KERNEL_BYTE_PARITY','PASS' if kernel_ok else 'FAIL',f"legacy/current Kernel files identical={sum(r['byte_identical'] for r in kp['files'])}/{kp['file_count']}"))
 dp=json.loads((ROOT/'reference/m2/game_data_provenance.json').read_text())
 data_ok=dp['file_count']==27 and all(r['byte_identical'] and (ROOT/r['target_path']).is_file() and sha256_file(ROOT/r['target_path'])==r['legacy_sha256'] for r in dp['files'])
 checks.append(VerificationCheck('Q3_GAME_DATA_BYTE_PARITY','PASS' if data_ok else 'FAIL',f"legacy/current game-data files identical={sum(r['byte_identical'] for r in dp['files'])}/{dp['file_count']}"))
 # Kernel must remain independent from the modular monolith contracts/systems.
 forbidden=[]
 for p in (ROOT/'src/anka_game_kernel').rglob('*.py'):
  text=p.read_text(encoding='utf-8')
  if 'anka_contracts' in text or 'anka_app' in text or 'anka_platform' in text: forbidden.append(p.relative_to(ROOT).as_posix())
 checks.append(VerificationCheck('Q3_KERNEL_INDEPENDENCE','PASS' if not forbidden else 'FAIL',f'forbidden external ANKA imports={len(forbidden)}',tuple(forbidden[:20])))
 scope=json.loads((ROOT/'reference/m2/KERNEL_SCOPE.json').read_text())
 scope_ok=(scope['static_source_game_version']=='3.6.10.10' and scope['verified_spell_mechanics_count']==47 and {x['class_id'] for x in scope['target_classes']}=={3,9} and len(scope['bundled_map_ids'])==4 and bool(scope['not_certified']))
 checks.append(VerificationCheck('Q3_SCOPE_EXPLICIT','PASS' if scope_ok else 'FAIL','Historical source versions, CRA/ENU scope, maps and non-certified boundaries are explicit.'))
 unit=run_unittest_modules(('tests.test_kernel_reuse','tests.test_m2_kernel_adapter'))
 checks.append(VerificationCheck('Q3_CURRENT_KERNEL_ADAPTER_TESTS','PASS' if unit['failed']==0 else 'FAIL',f"tests={unit['tests_run']} pass={unit['passed']} fail={unit['failed']}",tuple(unit['failure_details'])))
 legacy=_legacy_subset()
 checks.append(VerificationCheck('Q3_LEGACY_KERNEL_ORACLE','PASS' if legacy['returncode']==0 and legacy['passed']>=180 else 'FAIL',f"legacy independent mechanics cases passed={legacy['passed']}; selected files={len(SELECTED)}",(legacy['output'],) if legacy['returncode'] else ()))
 all_pass=all(x.status=='PASS' for x in checks)
 test_counts=VerificationCounts(passed=unit['passed']+legacy['passed'],failed=unit['failed']+(0 if legacy['returncode']==0 else 1),skipped=unit['skipped'])
 common=dict(source_tree_sha256=implementation_source_hash(),config_schema_sha256=sha256_file(ROOT/'config/schema/user.schema.json'),effective_config_sha256=sha256_file(ROOT/'config/user.json'),python_version=sys.version.split()[0],dependency_manifest_sha256=dependency_manifest_hash(),observed_client_build=None,protocol_adapter_release=None,kernel_tree_sha256=tree_hash((ROOT/'src/anka_game_kernel',)),game_data_tree_sha256=tree_hash((ROOT/'assets/game_data',)),calibration_sha256=sha256_file(ROOT/'assets/calibration/shared_ui_1280x649.json'),fixture_manifest_sha256=test_fixture_hash(('reference/m2/legacy_kernel_oracle_manifest.json','tests/test_kernel_reuse.py','tests/test_m2_kernel_adapter.py')))
 artifacts=[]
 for rel in ('reference/m2/kernel_reuse_provenance.json','reference/m2/game_data_provenance.json','reference/m2/KERNEL_SCOPE.json','reference/m2/legacy_kernel_oracle_manifest.json','docs/M2_GAME_KERNEL_AND_DATA.md'):
  artifacts.append((rel,sha256_file(ROOT/rel)))
 receipt=VerificationReceipt(1,'Q3','M2','PASS' if all_pass and not test_counts.failed else 'FAIL',datetime.now(timezone.utc).isoformat(),**common,check_counts=_counts(checks),test_counts=test_counts,environment=environment_pairs(),duration_ms=int((time.monotonic()-started)*1000),physical_input_count=0,physical_input_state='DISABLED',checks=tuple(checks),known_limitations=('Game data is historical 3.6.10.10 and does not certify the current client build.','Q3 proves deterministic mechanics/data scope only; live resources, protocol truth, identity, projection and physical input are outside Kernel authority.'),artifacts=tuple(artifacts))
 OUT.write_text(json.dumps(receipt.to_dict(),indent=2,sort_keys=True)+'\n')
 print(f'Q3_M2 {receipt.status} tests_pass={receipt.test_counts.passed} tests_fail={receipt.test_counts.failed} physical_input_count=0')
 for c in checks: print(f'[{c.status}] {c.code}: {c.detail}')
 return 0 if receipt.status=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
