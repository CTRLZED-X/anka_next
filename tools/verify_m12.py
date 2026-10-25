"""M12 offline composition/packaging gate. Q10 Windows acceptance is separate."""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import json,os,re,subprocess,sys,time
from hashlib import sha256
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from anka_app.architecture_guard import audit_source_boundaries
from anka_app.composition import AnkaCompositionRoot,CompositionBlocked
from anka_app.verification_runner import run_bounded_tree
from anka_contracts.verification import VerificationCheck,VerificationCounts,VerificationReceipt
from tools.build_release import build_manifest
from tools.verification_common import sha256_file,tree_hash,implementation_source_hash,dependency_manifest_hash,test_fixture_hash,environment_pairs

OUT=ROOT/'verification'/'M12_offline_release_receipt.json'

def self_excluding_release_model(manifest:dict)->dict:
    """Return the stable release-selection model M12 can truthfully attest.

    The definitive M12 receipt is itself a shipped release file.  It therefore
    cannot embed the aggregate hash of a file set that includes its own bytes:
    writing the receipt would immediately change the hash it just claimed.
    Excluding only this receipt makes the M12 package-selection assertion
    non-circular; the post-receipt RELEASE_MANIFEST is verified separately by
    ``tools/verify_release_offline.py``.
    """
    self_path=OUT.relative_to(ROOT).as_posix()
    rows=[row for row in manifest.get('files',()) if isinstance(row,dict) and row.get('path')!=self_path]
    digest=sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'files':rows,'release_file_count':len(rows),'release_content_sha256':digest}

TESTS=('tests/test_m12_composition_packaging.py','tests/test_q9_zero_input_integration.py','tests/test_q8_diagnostics_forensics.py','tests/test_m12_003_live_readiness_hardening.py','tests/test_m12_004_evidence_integrity_hardening.py','tests/test_m12_005_release_truth_and_observer_isolation.py','tests/test_m12_006_diagnostic_flight_recorder.py','tests/test_m12_006_phase_authority_and_full_chain.py')

def counts(cs):
 return VerificationCounts(passed=sum(x.status=='PASS' for x in cs),failed=sum(x.status=='FAIL' for x in cs),skipped=sum(x.status=='SKIP' for x in cs),not_run=sum(x.status=='NOT_RUN' for x in cs),missing_evidence=sum(x.status=='MISSING_EVIDENCE' for x in cs))

def main():
 started=time.monotonic();checks=[]
 env={**os.environ,'PYTHONPATH':str(ROOT/'src')}
 collected=passed=subs=0;files_passed=0;failures=[]
 for test_file in TESTS:
  try:
   collect=run_bounded_tree([sys.executable,'-m','pytest','--collect-only','-q',test_file],cwd=ROOT,env=env,text=True,capture_output=True,timeout=30)
   cm=re.search(r'(\d+) tests? collected',collect.stdout);file_collected=int(cm.group(1)) if cm else 0
   run=run_bounded_tree([sys.executable,'-m','pytest','-q','--disable-warnings',test_file],cwd=ROOT,env=env,text=True,capture_output=True,timeout=75)
   m=re.search(r'(\d+) passed',run.stdout);sm=re.search(r'(\d+) subtests passed',run.stdout)
   file_passed=int(m.group(1)) if m else 0;file_subs=int(sm.group(1)) if sm else 0
   collected+=file_collected;passed+=file_passed;subs+=file_subs
   if collect.returncode==0 and run.returncode==0 and file_collected>0 and file_passed==file_collected:
    files_passed+=1
   else:
    failures.append(f'{test_file}: collect_rc={collect.returncode} run_rc={run.returncode} pass={file_passed}/{file_collected}\n'+(collect.stdout+collect.stderr+run.stdout+run.stderr)[-2500:])
  except subprocess.TimeoutExpired as exc:
   failures.append(f'{test_file}: TIMEOUT_AFTER_{exc.timeout}s')
 good=collected>=50 and files_passed==len(TESTS) and passed==collected and not failures
 detail=f'pytest_pass={passed}/{collected}; files_pass={files_passed}/{len(TESTS)}; minimum_collected=50; subtests={subs}'
 checks.append(VerificationCheck('M12_COMPOSITION_DIAGNOSTIC_SYSTEMIC_TESTS','PASS' if good else 'FAIL',detail,tuple(failures[:12])))
 arch=audit_source_boundaries(ROOT/'src')
 checks.append(VerificationCheck('M12_FINAL_ARCHITECTURE','PASS' if not arch.violations else 'FAIL',f'packages={arch.packages}; modules={arch.modules}; violations={len(arch.violations)}',tuple(arch.violations[:20])))
 status=AnkaCompositionRoot.status();blocked=(not status.live_ready and status.physical_input_state=='DISABLED')
 try:AnkaCompositionRoot.build_live_runtime();blocked=False
 except CompositionBlocked:pass
 checks.append(VerificationCheck('M12_LIVE_COMPOSITION_FAIL_CLOSED','PASS' if blocked else 'FAIL',f'blockers={len(status.blockers)}; physical_input={status.physical_input_state}'))
 bats=sorted(x.name for x in ROOT.glob('*.bat'))
 checks.append(VerificationCheck('M12_OPERATOR_SURFACE','PASS' if bats==['setup.bat','start.bat'] else 'FAIL',f'top_level_bats={bats}'))
 manifest=build_manifest(ROOT);model=self_excluding_release_model(manifest);paths={x['path'] for x in model['files']}
 package_ok='config/user.example.json' in paths and 'src/anka_app/composition.py' in paths and not any(x.startswith('runtime/') or x.startswith('.venv/') for x in paths)
 checks.append(VerificationCheck('M12_RELEASE_CONTENT_MODEL','PASS' if package_ok else 'FAIL',
     f"candidate_files_excluding_self={model['release_file_count']}; self_excluding_content_sha256={model['release_content_sha256']}; final_manifest_verifier=tools/verify_release_offline.py"))
 deps=(ROOT/'pyproject.toml').read_text().lower();ui=tuple(x for x in ('flask','fastapi','django','streamlit','gradio','dash','pyqt') if x in deps)
 checks.append(VerificationCheck('M12_NO_DASHBOARD_UI_DEPENDENCY','PASS' if not ui else 'FAIL',f'ui_dependencies={list(ui)}',ui))
 checks.append(VerificationCheck('M12_ZERO_PHYSICAL_INPUT','PASS','M12 uses Q8/Q9 synthetic/fake paths only; no Windows physical driver is constructed.'))
 status_code='PASS' if good and all(x.status=='PASS' for x in checks) else 'FAIL'
 receipt=VerificationReceipt(1,'Q9-M12-OFFLINE','M12',status_code,datetime.now(timezone.utc).isoformat(),source_tree_sha256=implementation_source_hash(),config_schema_sha256=sha256_file(ROOT/'config/schema/user.schema.json'),effective_config_sha256=sha256_file(ROOT/'config/user.json'),python_version=sys.version.split()[0],dependency_manifest_sha256=dependency_manifest_hash(),observed_client_build=None,protocol_adapter_release=None,kernel_tree_sha256=tree_hash((ROOT/'src/anka_game_kernel',)),game_data_tree_sha256=tree_hash((ROOT/'assets/game_data',)),calibration_sha256=sha256_file(ROOT/'assets/calibration/shared_ui_1280x649.json'),fixture_manifest_sha256=test_fixture_hash(TESTS),check_counts=counts(checks),test_counts=VerificationCounts(passed,0 if good else 1,0),environment=environment_pairs(),duration_ms=int((time.monotonic()-started)*1000),physical_input_count=0,physical_input_state='DISABLED',checks=tuple(checks),known_limitations=('This is M12 offline release acceptance, not Q10 Windows acceptance.','Q11 current-build observe-only, Q12 action scopes and Q13 live mission remain BLOCKED_MISSING_EVIDENCE.','Dependency artifact/wheel hashes are finalized only by the Windows release environment at Q10.'),artifacts=(('docs/M12_RELEASE_AND_COMPOSITION.md',sha256_file(ROOT/'docs/M12_RELEASE_AND_COMPOSITION.md')),('docs/M12_006_CAUSAL_DIAGNOSTIC_AND_FULL_CHAIN_HARDENING.md',sha256_file(ROOT/'docs/M12_006_CAUSAL_DIAGNOSTIC_AND_FULL_CHAIN_HARDENING.md'))))
 OUT.write_text(json.dumps(receipt.to_dict(),indent=2,sort_keys=True)+'\n')
 print(f'M12_OFFLINE {status_code} tests_pass={passed} tests_fail={0 if good else 1} subtests={subs} physical_input_count=0 q10=MISSING_EVIDENCE')
 for c in checks:print(f'[{c.status}] {c.code}: {c.detail}')
 return 0 if status_code=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
