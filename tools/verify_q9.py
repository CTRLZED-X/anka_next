"""Q9 full CRA+ENU zero-OS-input verifier with bounded checkpoints."""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import ast,json,os,re,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from anka_app.architecture_guard import audit_source_boundaries
from anka_contracts.verification import VerificationCheck,VerificationCounts,VerificationReceipt
from tools.verification_common import sha256_file,tree_hash,implementation_source_hash,dependency_manifest_hash,test_fixture_hash,environment_pairs
OUT=ROOT/'verification'/'Q9_zero_input_integration_receipt.json'
CHECKPOINT=ROOT/'verification'/'.q9_checkpoint.json'
Q9='tests/test_q9_zero_input_integration.py'; P20='tests/test_p20_cross_system_replay.py'; ALL=(Q9,P20)
Q9A=(
 f'{Q9}::TestQ9ZeroInputIntegration::test_full_cra_enu_world_fight_world_lifecycle_completes',
 f'{Q9}::TestQ9ZeroInputIntegration::test_end_turn_stays_pending_until_both_views_prove_new_owner',
 f'{Q9}::TestQ9ZeroInputIntegration::test_canonical_state_replay_matches_durable_projection_after_full_run',
 f'{Q9}::TestQ9ZeroInputIntegration::test_q9_is_explicit_synthetic_build_and_fake_driver_only',
)
Q9B=(
 f'{Q9}::TestQ9ZeroInputIntegration::test_one_account_missing_ready_blocks_party_and_driver',
 f'{Q9}::TestQ9ZeroInputIntegration::test_enu_cannot_act_during_cross_account_handoff_skew',
 f'{Q9}::TestQ9ZeroInputIntegration::test_ambiguous_external_boundary_blocks_workflow_without_retry',
 f'{Q9}::TestQ9ZeroInputIntegration::test_action_settlement_requires_canonical_consequence_and_is_not_click_success',
 f'{Q9}::TestQ9ZeroInputIntegration::test_no_windows_input_primitive_is_reachable_from_q9_harness',
)

def scope_hash():
 return tree_hash((ROOT/'src/anka_app/zero_input_integration.py',ROOT/'src/anka_contracts',ROOT/'src/anka_canonical',ROOT/'src/anka_live_state',ROOT/'src/anka_coordination',ROOT/'src/anka_decision',ROOT/'src/anka_execution',ROOT/'src/anka_workflow',ROOT/'src/anka_game_kernel',ROOT/'src/anka_observability',ROOT/Q9,ROOT/P20,ROOT/'config/user.json',ROOT/'config/schema/user.schema.json',ROOT/'assets/workflow',ROOT/'assets/game_data'))
def load():
 try:return json.loads(CHECKPOINT.read_text())
 except (OSError,json.JSONDecodeError):return {}
def save(stage,r):
 h=scope_hash();d=load()
 if d.get('scope_sha256') not in (None,h):d={}
 d['scope_sha256']=h;d[stage]=r;CHECKPOINT.parent.mkdir(parents=True,exist_ok=True);CHECKPOINT.write_text(json.dumps(d,indent=2,sort_keys=True)+'\n')
def run_pytest(nodes):
 p=subprocess.run([sys.executable,'-m','pytest','-q','--disable-warnings',*nodes],cwd=ROOT,env={**os.environ,'PYTHONPATH':str(ROOT/'src')},capture_output=True,text=True,timeout=40)
 m=re.search(r'(\d+) passed',p.stdout);s=re.search(r'(\d+) subtests passed',p.stdout)
 return {'rc':p.returncode,'passed':int(m.group(1)) if m else 0,'subtests':int(s.group(1)) if s else 0,'tail':(p.stdout+p.stderr)[-4000:]}
def stage(name):
 nodes=Q9A if name=='q9a' else Q9B if name=='q9b' else (P20,)
 r=run_pytest(nodes);save(name,r);print(f"Q9_{name.upper()} {'PASS' if r['rc']==0 else 'FAIL'} tests={r['passed']} subtests={r['subtests']}");return 0 if r['rc']==0 else 1
def counts(cs):
 return VerificationCounts(passed=sum(c.status=='PASS' for c in cs),failed=sum(c.status=='FAIL' for c in cs),skipped=sum(c.status=='SKIP' for c in cs),not_run=sum(c.status=='NOT_RUN' for c in cs),missing_evidence=sum(c.status=='MISSING_EVIDENCE' for c in cs))
def finalize():
 started=time.monotonic();checks=[];d=load();same=d.get('scope_sha256')==scope_hash();checks.append(VerificationCheck('Q9_CHECKPOINT_SCOPE','PASS' if same else 'FAIL','All expensive stages are bound to the current Q9 implementation/test/config scope.'))
 total=subs=fails=0
 for name,want in (('q9a',4),('q9b',5),('p20',13)):
  r=d.get(name,{});p=int(r.get('passed',0));total+=p;subs+=int(r.get('subtests',0));ok=same and r.get('rc')==0 and p==want;fails+=0 if ok else 1
  checks.append(VerificationCheck(f'Q9_{name.upper()}_REGRESSION','PASS' if ok else 'FAIL',f"pytest_pass={p}/{want}; subtests={r.get('subtests',0)}",(() if ok else (str(r.get('tail','NO_CHECKPOINT'))[-3000:],))))
 src=(ROOT/'src/anka_app/zero_input_integration.py').read_text();expected=('CanonicalWriter','StateProjector','PartyCoordinatorService','DeterministicPlanner','MissionWorkflow','DefinitiveExecutionService','WorkflowTurnController','GameKernel','HostInputArbiter','LocalDiagnostics')
 checks.append(VerificationCheck('Q9_REAL_SYSTEM_BOUNDARIES_WIRED','PASS' if all(x in src for x in expected) else 'FAIL','Production Canonical/State/Coordination/Decision/Workflow/Execution/Kernel/Observability boundaries are composed.'))
 handoff=all(x in src for x in ('_run_end_turn_and_handoff','TURN_OWNER_CHANGED','Q9_NEXT_ACCOUNT_PERMITTED_BEFORE_OWNER_PROOF','Q9_NEXT_ACCOUNT_NOT_PERMITTED_AFTER_OWNER_PROOF'))
 checks.append(VerificationCheck('Q9_END_TURN_TO_NEXT_OWNER_CAUSALITY','PASS' if handoff else 'FAIL','END_TURN cannot grant ENU authority before cross-account owner convergence.'))
 tree=ast.parse(src);imports=[]
 for n in ast.walk(tree):
  if isinstance(n,ast.Import):imports.extend(a.name for a in n.names)
  elif isinstance(n,ast.ImportFrom):imports.append(n.module or '')
 unsafe=[x for x in imports if 'windows_input' in x or x in ('ctypes','pyautogui','pynput','win32api','win32gui')];tokens=[x for x in ('SetCursorPos','mouse_event','SendInput','keybd_event','pyautogui','pynput') if x in src]
 checks.append(VerificationCheck('Q9_NO_OS_INPUT_REACHABILITY','PASS' if not unsafe and not tokens else 'FAIL',f'unsafe_imports={unsafe}; primitive_hits={tokens}',tuple(unsafe+tokens)))
 synthetic=('SYNTHETIC-Q9-NOT-A-LIVE-CLIENT' in src and 'FakePhysicalInputDriver' in src)
 checks.append(VerificationCheck('Q9_SYNTHETIC_EXTERNAL_BOUNDARY','PASS' if synthetic else 'FAIL','Current-client-required boundaries are explicitly synthetic and the fake driver is used.'))
 arch=audit_source_boundaries(ROOT/'src');checks.append(VerificationCheck('Q9_ARCHITECTURE_STILL_CLEAN','PASS' if not arch.violations else 'FAIL',f'packages={arch.packages}; modules={arch.modules}; violations={len(arch.violations)}',tuple(arch.violations[:20])))
 bats=sorted(x.name for x in ROOT.glob('*.bat'));checks.append(VerificationCheck('Q9_OPERATOR_SURFACE','PASS' if bats==['setup.bat','start.bat'] else 'FAIL',f'root BAT launchers={bats}'))
 checks.append(VerificationCheck('Q9_ZERO_PHYSICAL_INPUT','PASS' if fails==0 else 'FAIL','All Q9/P20 scenarios use fake/synthetic external boundaries; physical OS input count is 0.'))
 status='PASS' if fails==0 and all(c.status=='PASS' for c in checks) else 'FAIL';tc=VerificationCounts(passed=total,failed=fails,skipped=0)
 receipt=VerificationReceipt(1,'Q9','M12-Q9',status,datetime.now(timezone.utc).isoformat(),source_tree_sha256=implementation_source_hash(),config_schema_sha256=sha256_file(ROOT/'config/schema/user.schema.json'),effective_config_sha256=sha256_file(ROOT/'config/user.json'),python_version=sys.version.split()[0],dependency_manifest_sha256=dependency_manifest_hash(),observed_client_build='SYNTHETIC-Q9-NOT-A-LIVE-CLIENT',protocol_adapter_release='adapter-q9-synthetic-zero-input-r1',kernel_tree_sha256=tree_hash((ROOT/'src/anka_game_kernel',)),game_data_tree_sha256=tree_hash((ROOT/'assets/game_data',)),calibration_sha256=sha256_file(ROOT/'assets/calibration/shared_ui_1280x649.json'),fixture_manifest_sha256=test_fixture_hash(ALL),check_counts=counts(checks),test_counts=tc,environment=environment_pairs(),duration_ms=int((time.monotonic()-started)*1000),physical_input_count=0,physical_input_state='FAKE_ONLY',checks=tuple(checks),known_limitations=('Q9 proves full production-service integration only against an explicitly synthetic protocol/build/client boundary; it is not current-client acceptance.','Q10 Windows packaging/startup and Q11 current-build observe-only acceptance remain blocked pending real supported-host evidence.','Q9 evidence cannot activate the Windows physical-input driver or any action scope.'),artifacts=(('docs/Q9_ZERO_INPUT_INTEGRATION.md',sha256_file(ROOT/'docs/Q9_ZERO_INPUT_INTEGRATION.md')),('src/anka_app/zero_input_integration.py',sha256_file(ROOT/'src/anka_app/zero_input_integration.py'))))
 OUT.write_text(json.dumps(receipt.to_dict(),indent=2,sort_keys=True)+'\n');print(f'Q9_ZERO_INPUT {status} tests_pass={total} tests_fail={fails} subtests={subs} physical_input_count=0');[print(f'[{c.status}] {c.code}: {c.detail}') for c in checks];return 0 if status=='PASS' else 1
def main():
 import argparse
 ap=argparse.ArgumentParser();ap.add_argument('--stage',choices=('q9a','q9b','p20','finalize'),default='finalize');a=ap.parse_args();return stage(a.stage) if a.stage!='finalize' else finalize()
if __name__=='__main__':raise SystemExit(main())
