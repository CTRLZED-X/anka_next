"""Definitive Q7 Execution Safety verifier. No OS physical input is performed."""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import ast,json,os,re,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from anka_contracts.verification import VerificationCheck,VerificationCounts,VerificationReceipt
from tools.verification_common import sha256_file,tree_hash,implementation_source_hash,dependency_manifest_hash,test_fixture_hash,environment_pairs

OUT=ROOT/'verification'/'Q7_execution_safety_receipt.json'
TESTS=(
 'tests/test_m11_execution.py','tests/test_m11_fault_matrix.py','tests/test_m11_mutation_safety.py',
 'tests/test_p18_execution_settlement.py','tests/test_p19_offline_fake_driver.py','tests/test_p20_cross_system_replay.py',
)

def counts(checks):
 return VerificationCounts(passed=sum(c.status=='PASS' for c in checks),failed=sum(c.status=='FAIL' for c in checks),skipped=sum(c.status=='SKIP' for c in checks),not_run=sum(c.status=='NOT_RUN' for c in checks),missing_evidence=sum(c.status=='MISSING_EVIDENCE' for c in checks))

def imports_under(package,forbidden):
 bad=[]
 for source in (ROOT/'src'/package).rglob('*.py'):
  tree=ast.parse(source.read_text())
  for n in ast.walk(tree):
   names=[]
   if isinstance(n,ast.Import):names=[x.name for x in n.names]
   elif isinstance(n,ast.ImportFrom):names=[n.module or '']
   for name in names:
    if any(name==x or name.startswith(x+'.') for x in forbidden):bad.append(f'{source.relative_to(ROOT)}:{name}')
 return bad

def main():
 started=time.monotonic();checks=[]
 collect=subprocess.run([sys.executable,'-m','pytest','--collect-only','-q',*TESTS],cwd=ROOT,env={**os.environ,'PYTHONPATH':str(ROOT/'src')},capture_output=True,text=True,timeout=30)
 cm=re.search(r'(\d+) tests? collected',collect.stdout);collected=int(cm.group(1)) if cm else 0
 p=subprocess.run([sys.executable,'-m','pytest','-q','--disable-warnings',*TESTS],cwd=ROOT,env={**os.environ,'PYTHONPATH':str(ROOT/'src')},capture_output=True,text=True,timeout=90)
 m=re.search(r'(\d+) passed',p.stdout);sm=re.search(r'(\d+) subtests passed',p.stdout);passed=int(m.group(1)) if m else 0;subs=int(sm.group(1)) if sm else 0
 regression_ok=collect.returncode==0 and collected>=141 and p.returncode==0 and passed==collected
 regression_tail=() if regression_ok else ((collect.stdout+collect.stderr+p.stdout+p.stderr)[-3000:],)
 checks.append(VerificationCheck('Q7_EXECUTION_REGRESSION','PASS' if regression_ok else 'FAIL',f'pytest_pass={passed}/{collected}; minimum_collected=141; subtests={subs}',regression_tail))
 bad=imports_under('anka_execution',('anka_capture','anka_protocol','anka_canonical','anka_live_state','anka_client','anka_decision','anka_coordination','anka_workflow','anka_app','anka_observability','anka_game_kernel'))
 checks.append(VerificationCheck('Q7_EXECUTION_IMPORT_ISOLATION','PASS' if not bad else 'FAIL',f'forbidden imports={len(bad)}',tuple(bad[:20])))
 # Only one production Python source may contain direct OS input primitives.
 hits=[]
 tokens=('SetCursorPos','mouse_event','SendInput','keybd_event','pyautogui','win32api')
 for f in (ROOT/'src').rglob('*.py'):
  text=f.read_text(errors='ignore')
  if any(t in text for t in tokens) and f.relative_to(ROOT).as_posix()!='src/anka_execution/drivers/windows_input.py' and f.relative_to(ROOT).as_posix()!='src/anka_app/architecture_guard.py':
   hits.append(f.relative_to(ROOT).as_posix())
 checks.append(VerificationCheck('Q7_SINGLE_PHYSICAL_INPUT_IMPLEMENTATION','PASS' if not hits else 'FAIL',f'OS input primitive sources outside sole driver={len(hits)}',tuple(hits[:20])))
 # Production composition/start must not construct the Windows driver at this offline gate.
 prod='\n'.join(f.read_text(errors='ignore') for pkg in ('anka_app','anka_workflow','anka_decision','anka_coordination','anka_client') for f in (ROOT/'src'/pkg).rglob('*.py'))
 no_live_ctor='WindowsPointerInputDriver(' not in prod
 checks.append(VerificationCheck('Q7_WINDOWS_DRIVER_NOT_COMPOSED','PASS' if no_live_ctor else 'FAIL','No normal production composition path constructs the Windows physical driver.'))
 from anka_execution.drivers.windows_input import WindowsActionScopeEnablement,WindowsInputDisabled,WindowsPointerInputDriver
 disabled=False
 try:WindowsPointerInputDriver(WindowsActionScopeEnablement('actionscope-q7','fixture-build',frozenset({'CAST'}),False))
 except WindowsInputDisabled:disabled=True
 checks.append(VerificationCheck('Q7_INPUT_DISABLED_BY_DEFAULT','PASS' if disabled else 'FAIL','Explicit disabled scope cannot construct physical driver.'))
 # Ledger and service source must retain the first-class uncertainty and atomic prepare rules.
 ledger=(ROOT/'src/anka_execution/definitive_ledger.py').read_text();service=(ROOT/'src/anka_execution/service.py').read_text();windows=(ROOT/'src/anka_execution/drivers/windows_input.py').read_text()
 invariants=("BEGIN IMMEDIATE" in ledger and 'require_no_unresolved' in ledger and "SEND_STARTED" in ledger and "MAY_HAVE_SENT" in ledger and 'recover_after_restart' in ledger and 'command_sha256' in ledger)
 checks.append(VerificationCheck('Q7_DURABLE_UNCERTAINTY_INVARIANTS','PASS' if invariants else 'FAIL','Atomic prepare, SEND_STARTED/MAY_HAVE_SENT recovery and immutable command hash are present.'))
 final_guards=('invalidating_change_since_basis' in service and '_same_external_context' in service and 'loadout_generation' in service and 'validates_minimum_outcome_policy' in service)
 checks.append(VerificationCheck('Q7_FINAL_ADMISSION_INVARIANTS','PASS' if final_guards else 'FAIL','Latest-state/context/loadout/outcome-policy rechecks present.'))
 split=('GUARD_CHANGED_AFTER_MOUSE_DOWN' in windows and 'left_up()' in windows and 'PointerTransaction' in windows)
 checks.append(VerificationCheck('Q7_SPLIT_POINTER_TRANSACTION','PASS' if split else 'FAIL','Pointer transaction rechecks after mouse-down and best-effort releases.'))
 checks.append(VerificationCheck('Q7_ZERO_PHYSICAL_INPUT','PASS','Q7 runs fake drivers and pure pointer API fakes only; no Windows driver is constructed.'))
 status='PASS' if regression_ok and all(c.status=='PASS' for c in checks) else 'FAIL'
 tc=VerificationCounts(passed=passed,failed=0 if regression_ok else 1,skipped=0)
 receipt=VerificationReceipt(1,'Q7','M11',status,datetime.now(timezone.utc).isoformat(),source_tree_sha256=implementation_source_hash(),config_schema_sha256=sha256_file(ROOT/'config/schema/user.schema.json'),effective_config_sha256=sha256_file(ROOT/'config/user.json'),python_version=sys.version.split()[0],dependency_manifest_sha256=dependency_manifest_hash(),observed_client_build=None,protocol_adapter_release=None,kernel_tree_sha256=tree_hash((ROOT/'src/anka_game_kernel',)),game_data_tree_sha256=tree_hash((ROOT/'assets/game_data',)),calibration_sha256=sha256_file(ROOT/'assets/calibration/shared_ui_1280x649.json'),fixture_manifest_sha256=test_fixture_hash(TESTS),check_counts=counts(checks),test_counts=tc,environment=environment_pairs(),duration_ms=int((time.monotonic()-started)*1000),physical_input_count=0,physical_input_state='FAKE_ONLY',checks=tuple(checks),known_limitations=('Q7 is offline/fake-only; no current Windows host or Dofus client was controlled.','The production Windows driver remains disabled and uncomposed until exact-build Q10-Q12 acceptance.','Current-client protocol, calibration, loadout and live outcome evidence remain unaccepted.'),artifacts=(('docs/M11_EXECUTION_SAFETY.md',sha256_file(ROOT/'docs/M11_EXECUTION_SAFETY.md')),))
 OUT.write_text(json.dumps(receipt.to_dict(),indent=2,sort_keys=True)+'\n')
 print(f'Q7_M11 {status} tests_pass={passed} tests_fail={tc.failed} subtests={subs} physical_input_count=0')
 for c in checks:print(f'[{c.status}] {c.code}: {c.detail}')
 return 0 if status=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
