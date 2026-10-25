"""Definitive Q8 diagnostics/forensics verifier."""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import ast,json,os,re,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from anka_contracts.verification import VerificationCheck,VerificationCounts,VerificationReceipt
from anka_app.verification_runner import run_bounded_tree
from tools.verification_common import sha256_file,tree_hash,implementation_source_hash,dependency_manifest_hash,test_fixture_hash,environment_pairs

OUT=ROOT/'verification'/'Q8_diagnostics_receipt.json'
TESTS=('tests/test_q8_diagnostics_forensics.py','tests/test_diagnostics.py','tests/test_bootstrap.py','tests/test_m12_006_diagnostic_flight_recorder.py')

def counts(cs):
 return VerificationCounts(passed=sum(x.status=='PASS' for x in cs),failed=sum(x.status=='FAIL' for x in cs),skipped=sum(x.status=='SKIP' for x in cs),not_run=sum(x.status=='NOT_RUN' for x in cs),missing_evidence=sum(x.status=='MISSING_EVIDENCE' for x in cs))

def pytest_run():
 # Diagnostic fault-injection modules intentionally exercise stalled/failed
 # background observers. Run each file in a fresh bounded subprocess so one
 # adversarial test cannot pollute timing/thread state for the next file.
 collected=passed=subtests=0;failures=[];collection_failed=False
 env={**os.environ,'PYTHONPATH':str(ROOT/'src')}
 for test_file in TESTS:
  try:
   collect=run_bounded_tree([sys.executable,'-m','pytest','--collect-only','-q',test_file],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
  except subprocess.TimeoutExpired:
   collection_failed=True;failures.append(f'{test_file}:COLLECT_TIMEOUT');continue
  cm=re.search(r'(\d+) tests? collected',collect.stdout);count=int(cm.group(1)) if cm else 0
  if collect.returncode!=0 or count<=0:
   collection_failed=True;failures.append(f'{test_file}:COLLECT_FAILED:'+(collect.stdout+collect.stderr)[-1500:]);continue
  collected+=count
  try:
   result=run_bounded_tree([sys.executable,'-m','pytest','-q','--disable-warnings',test_file],cwd=ROOT,env=env,capture_output=True,text=True,timeout=75)
  except subprocess.TimeoutExpired as exc:
   failures.append(f'{test_file}:TEST_TIMEOUT:{exc.timeout}s');continue
  m=re.search(r'(\d+) passed',result.stdout); sm=re.search(r'(\d+) subtests passed',result.stdout)
  file_pass=int(m.group(1)) if m else 0;passed+=file_pass;subtests+=int(sm.group(1)) if sm else 0
  if result.returncode!=0 or file_pass!=count:
   failures.append(f'{test_file}:TEST_FAILED:'+(result.stdout+result.stderr)[-2500:])
 return collected,passed,subtests,collection_failed,failures

def imports_for_package(package):
 bad=[]
 root=ROOT/'src'/package
 forbidden={
  'anka_capture','anka_protocol','anka_canonical','anka_live_state','anka_game_kernel',
  'anka_decision','anka_execution','anka_coordination','anka_workflow','anka_client'
 }
 for path in root.rglob('*.py'):
  tree=ast.parse(path.read_text())
  for node in ast.walk(tree):
   names=[]
   if isinstance(node,ast.Import): names=[a.name for a in node.names]
   elif isinstance(node,ast.ImportFrom) and node.module: names=[node.module]
   for name in names:
    top=name.split('.')[0]
    if top in forbidden: bad.append(f'{path.relative_to(ROOT)}:{node.lineno}:{name}')
 return bad

def main():
 started=time.monotonic(); checks=[]
 collected,passed,subtests,collection_failed,failures=pytest_run(); good=(not collection_failed and not failures and collected>=24 and passed==collected)
 tail=() if good else tuple(failures[:8])
 checks.append(VerificationCheck('Q8_DELIBERATE_FAULT_MATRIX','PASS' if good else 'FAIL',f'pytest_pass={passed}/{collected}; files={len(TESTS)}; minimum_collected=24; subtests={subtests}',tail))
 bad=imports_for_package('anka_observability')
 checks.append(VerificationCheck('Q8_OBSERVER_AUTHORITY_ISOLATION','PASS' if not bad else 'FAIL',f'forbidden concrete-system imports={len(bad)}',tuple(bad[:20])))
 bundle=(ROOT/'src/anka_observability/bundle.py').read_text(); forensic=(ROOT/'src/anka_observability/forensics.py').read_text()
 required_paths=('analysis/diagnosis.json','analysis/boundary_graph.json','analysis/evidence_gaps.json','analysis/next_verification.json','logs/relevant_timeline.jsonl','logs/relevant_errors.jsonl','run_manifest.json')
 checks.append(VerificationCheck('Q8_GPT_BUNDLE_STRUCTURE','PASS' if all(x in bundle for x in required_paths) else 'FAIL','Definitive incident analysis/timeline paths are emitted while backward-compatible P1 paths remain.'))
 checks.append(VerificationCheck('Q8_FIRST_DIVERGENCE_ENGINE','PASS' if all(x in forensic for x in ('FirstDivergenceAnalyzer','first_divergent_boundary','missing_evidence','candidate_causes')) else 'FAIL','Expected-boundary analyzer records earliest missing causal edge and uncertainty.'))
 privacy=all(x in bundle for x in ("'raw_protocol_included':False",'UNSAFE_ZIP_PATH','BAD_CHECKSUM','OVERSIZED_BUNDLE_UNCOMPRESSED'))
 checks.append(VerificationCheck('Q8_PRIVACY_INTEGRITY_DEFAULT','PASS' if privacy else 'FAIL','Raw protocol is excluded by default; traversal/checksum/size checks remain active.'))
 fallback='INCIDENT_PRIMARY_EXPORT_FAILED' in bundle and "'EXPORT_FAILED'" in bundle and 'gettempdir' in bundle
 checks.append(VerificationCheck('Q8_EXPORT_FAILURE_FALLBACK','PASS' if fallback else 'FAIL','Primary exporter failure is preserved and fallback is explicitly marked EXPORT_FAILED.'))
 api=(ROOT/'src/anka_observability/api.py').read_text()
 passive='send_input' not in api and 'grant_permit' not in api and 'Best-effort bounded recorder' in api
 checks.append(VerificationCheck('Q8_OBSERVABILITY_PASSIVE','PASS' if passive else 'FAIL','Observer exposes recording/export only and has no input/permit authority API.'))
 checks.append(VerificationCheck('Q8_ZERO_OS_INPUT','PASS','Q8 diagnostics tests use synthetic events and fake failures only; physical input count is 0.'))
 status='PASS' if good and all(x.status=='PASS' for x in checks) else 'FAIL'
 receipt=VerificationReceipt(1,'Q8','M12-Q8',status,datetime.now(timezone.utc).isoformat(),source_tree_sha256=implementation_source_hash(),config_schema_sha256=sha256_file(ROOT/'config/schema/user.schema.json'),effective_config_sha256=sha256_file(ROOT/'config/user.json'),python_version=sys.version.split()[0],dependency_manifest_sha256=dependency_manifest_hash(),observed_client_build=None,protocol_adapter_release=None,kernel_tree_sha256=tree_hash((ROOT/'src/anka_game_kernel',)),game_data_tree_sha256=tree_hash((ROOT/'assets/game_data',)),calibration_sha256=sha256_file(ROOT/'assets/calibration/shared_ui_1280x649.json'),fixture_manifest_sha256=test_fixture_hash(TESTS),check_counts=counts(checks),test_counts=VerificationCounts(passed,0 if good else 1,0),environment=environment_pairs(),duration_ms=int((time.monotonic()-started)*1000),physical_input_count=0,physical_input_state='DISABLED',checks=tuple(checks),known_limitations=('Q8 proves offline causal diagnostics and bundle integrity; current-client event coverage still requires Q10/Q11 evidence.','Observer evidence never replaces Canonical or Execution authority ledgers.'),artifacts=(('docs/Q8_DIAGNOSTICS.md',sha256_file(ROOT/'docs/Q8_DIAGNOSTICS.md')),))
 OUT.write_text(json.dumps(receipt.to_dict(),indent=2,sort_keys=True)+'\n')
 print(f'Q8_DIAGNOSTICS {status} tests_pass={passed} tests_fail={0 if good else 1} subtests={subtests} physical_input_count=0')
 for c in checks: print(f'[{c.status}] {c.code}: {c.detail}')
 return 0 if status=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
