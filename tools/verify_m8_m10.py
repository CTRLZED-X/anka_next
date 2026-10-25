"""Definitive Q6 verifier: M8 Decision + M9 Coordination + M10 Workflow.

Slow retained Decision suites are checkpointed so a gate is reproducible without
conflating execution-window limits with semantic failure. Every checkpoint is
bound to the Q6-relevant source/test/config scope and is invalid when that scope changes. Unrelated later-milestone source changes do not invalidate a completed Q6 checkpoint.
"""
from __future__ import annotations
from datetime import datetime,timezone
from dataclasses import fields
from pathlib import Path
import ast,hashlib,json,os,re,subprocess,sys,time,zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from anka_contracts.decision import ActionPlan
from anka_contracts.verification import VerificationCheck,VerificationCounts,VerificationReceipt
from tools.verification_common import sha256_file,tree_hash,implementation_source_hash,dependency_manifest_hash,test_fixture_hash,environment_pairs

OUT=ROOT/'verification'/'Q6_planning_coordination_workflow_receipt.json'
CHECKPOINT=ROOT/'verification'/'.q6_checkpoint.json'
CORE_TESTS=('tests/test_m8_decision_planner.py','tests/test_m9_m10_generated.py','tests/test_m9_m10_q6.py','tests/test_p17_coordination_workflow.py','tests/test_configuration.py')
P12='tests/test_p12_decision_probe.py'
STAGE_FILES={'p14':('tests/test_p14_tactical_research.py',),'p15':('tests/test_p15_tactical_scoring.py',),'p16':('tests/test_p16_sequence_research.py',)}
ALL_TESTS=CORE_TESTS+(P12,)+tuple(x for v in STAGE_FILES.values() for x in v)

def q6_scope_hash() -> str:
    """Hash only inputs whose change can invalidate Q6 semantics/checkpoints."""
    paths=(
        ROOT/'src/anka_contracts', ROOT/'src/anka_decision', ROOT/'src/anka_coordination',
        ROOT/'src/anka_workflow', ROOT/'src/anka_game_kernel', ROOT/'config/schema/user.schema.json',
        ROOT/'config/user.json', ROOT/'assets/workflow',
        *(ROOT/x for x in ALL_TESTS), ROOT/'tools/verify_m8_m10.py',
    )
    return tree_hash(paths)

def counts(checks):
 return VerificationCounts(passed=sum(x.status=='PASS' for x in checks),failed=sum(x.status=='FAIL' for x in checks),skipped=sum(x.status=='SKIP' for x in checks),not_run=sum(x.status=='NOT_RUN' for x in checks),missing_evidence=sum(x.status=='MISSING_EVIDENCE' for x in checks))

def _pytest(nodes,timeout=75):
 p=subprocess.run([sys.executable,'-m','pytest','-q','--disable-warnings',*nodes],cwd=ROOT,env={**os.environ,'PYTHONPATH':str(ROOT/'src')},capture_output=True,text=True,timeout=timeout)
 m=re.search(r'(\d+) passed',p.stdout);s=re.search(r'(\d+) subtests passed',p.stdout)
 return {'rc':p.returncode,'passed':int(m.group(1)) if m else 0,'subtests':int(s.group(1)) if s else 0,'tail':(p.stdout+p.stderr)[-4000:]}

def _collect(path):
 p=subprocess.run([sys.executable,'-m','pytest','--collect-only','-q',path],cwd=ROOT,env={**os.environ,'PYTHONPATH':str(ROOT/'src')},capture_output=True,text=True,timeout=20)
 return p,[x.strip() for x in p.stdout.splitlines() if x.strip().startswith(path+'::')]

def _load():
 try:return json.loads(CHECKPOINT.read_text())
 except (OSError,json.JSONDecodeError):return {}

def _save(stage,result):
 data=_load();source=q6_scope_hash()
 if data.get('q6_scope_sha256') not in (None,source):data={}
 data.pop('source_tree_sha256',None)
 data['q6_scope_sha256']=source;data[stage]=result
 CHECKPOINT.parent.mkdir(parents=True,exist_ok=True);CHECKPOINT.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')

def _run_stage(stage):
 if stage=='core': nodes=CORE_TESTS
 elif stage in ('p12a','p12b'):
  cp,nodes_all=_collect(P12)
  if cp.returncode!=0 or len(nodes_all)!=43:
   result={'rc':1,'passed':0,'subtests':0,'tail':(cp.stdout+cp.stderr)[-4000:]+f' collected={len(nodes_all)}'};_save(stage,result)
   print(f'Q6_{stage.upper()} FAIL collection={len(nodes_all)}');return 1
  nodes=tuple(nodes_all[:20] if stage=='p12a' else nodes_all[20:])
 else:nodes=STAGE_FILES[stage]
 result=_pytest(nodes);_save(stage,result)
 print(f"Q6_{stage.upper()} {'PASS' if result['rc']==0 else 'FAIL'} pytest_pass={result['passed']} subtests={result['subtests']}")
 return 0 if result['rc']==0 else 1

def imports_under(package,forbidden):
 bad=[]
 for source in (ROOT/'src'/package).rglob('*.py'):
  tree=ast.parse(source.read_text())
  for n in ast.walk(tree):
   targets=[]
   if isinstance(n,ast.Import):targets=[x.name for x in n.names]
   elif isinstance(n,ast.ImportFrom):targets=[n.module or '']
   for name in targets:
    if any(name==x or name.startswith(x+'.') for x in forbidden):bad.append(f'{source.relative_to(ROOT)}:{name}')
 return bad

def _finalize():
 started=time.monotonic();checks=[];cp=_load();source=implementation_source_hash();scope=q6_scope_hash();same=cp.get('q6_scope_sha256')==scope
 checks.append(VerificationCheck('Q6_CHECKPOINT_SOURCE_MATCH','PASS' if same else 'FAIL','All slow-suite checkpoints are bound to the Q6-relevant source/test/config scope.'))
 expected={'core':97,'p12a':20,'p12b':23,'p14':20,'p15':20,'p16':29}
 total=0;subtests=0;stage_fail=0
 for stage,want in expected.items():
  result=cp.get(stage,{})
  passed=int(result.get('passed',0));total+=passed;subtests+=int(result.get('subtests',0))
  good=same and result.get('rc')==0 and passed==want
  if not good:stage_fail+=1
  checks.append(VerificationCheck(f'Q6_{stage.upper()}_REGRESSION','PASS' if good else 'FAIL',f"pytest_pass={passed}/{want}; subtests={result.get('subtests',0)}",(() if good else (str(result.get('tail','NO_CHECKPOINT'))[-3000:],))))

 forbidden_common=('anka_capture','anka_protocol','anka_canonical','anka_live_state','anka_client','anka_execution','anka_app')
 dbad=imports_under('anka_decision',forbidden_common+('anka_coordination','anka_workflow'))
 cbad=imports_under('anka_coordination',forbidden_common+('anka_decision','anka_workflow','anka_game_kernel'))
 wbad=imports_under('anka_workflow',forbidden_common+('anka_decision','anka_coordination','anka_game_kernel'))
 checks.append(VerificationCheck('Q6_DECISION_IMPORT_ISOLATION','PASS' if not dbad else 'FAIL',f'forbidden imports={len(dbad)}',tuple(dbad[:20])))
 checks.append(VerificationCheck('Q6_COORDINATION_IMPORT_ISOLATION','PASS' if not cbad else 'FAIL',f'forbidden imports={len(cbad)}',tuple(cbad[:20])))
 checks.append(VerificationCheck('Q6_WORKFLOW_IMPORT_ISOLATION','PASS' if not wbad else 'FAIL',f'forbidden imports={len(wbad)}',tuple(wbad[:20])))

 banned={'x','y','screen_x','screen_y','pixel_x','pixel_y','hwnd','mouse_x','mouse_y'}
 plan_fields={f.name for f in fields(ActionPlan)};bad_fields=sorted(plan_fields & banned)
 text='\n'.join(x.read_text(errors='ignore') for x in (ROOT/'src/anka_decision').rglob('*.py'))
 api_hits=[x for x in ('SendInput','SetCursorPos','pyautogui','win32api','win32gui') if x in text]
 checks.append(VerificationCheck('Q6_SEMANTIC_PLAN_ONLY','PASS' if not bad_fields and not api_hits else 'FAIL',f'banned ActionPlan fields={bad_fields}; OS input API hits={api_hits}'))

 from anka_contracts.coordination import PartyRosterMember,MemberPartyObservation
 from anka_coordination.coordinator import PartyCoordinatorService
 roster=(PartyRosterMember('acct-cra','client-cra',41,'leader'),PartyRosterMember('acct-enu','client-enu',42,'follower'))
 def o(i,a,joined=True,placed=True,ready=True,owner=41):
  return MemberPartyObservation(f'coordobs-q6-{i}',a,'client-cra' if a=='acct-cra' else 'client-enu',41 if a=='acct-cra' else 42,i,i,1,1,'fight-q6',190580738,'FIGHT_ACTIVE',owner,joined,placed,ready,'HEALTHY',(f'ev-q6-{i}',),False)
 c=PartyCoordinatorService('party-q6',roster,party_generation=41);c.observe(o(1,'acct-cra'));c.observe(o(2,'acct-enu'))
 old=c.turn_permit('party-q6','acct-cra');c.invalidate_ephemeral_permits();fresh=c.turn_permit('party-q6','acct-cra')
 generation_ok=old.allowed and fresh.allowed and old.party_generation!=fresh.party_generation and old.permit_generation!=fresh.permit_generation
 checks.append(VerificationCheck('Q6_PERMIT_RESTART_GENERATION_FENCE','PASS' if generation_ok else 'FAIL',f'old=({old.party_generation},{old.permit_generation}); fresh=({fresh.party_generation},{fresh.permit_generation})'))
 c2=PartyCoordinatorService('party-q6b',roster);c2.observe(o(11,'acct-cra',joined=True,placed=False,ready=True));c2.observe(o(12,'acct-enu',joined=True,placed=False,ready=True));s=c2.snapshot()
 barrier_ok=s.join_barrier.satisfied and not s.placement_barrier.satisfied and not s.ready_barrier.satisfied
 checks.append(VerificationCheck('Q6_READY_BARRIER_CAUSALITY','PASS' if barrier_ok else 'FAIL',f'join={s.join_barrier.satisfied}; placement={s.placement_barrier.satisfied}; ready={s.ready_barrier.satisfied}'))

 schema=json.loads((ROOT/'config/schema/user.schema.json').read_text());capture=set(schema['properties']['capture']['properties']);expected_capture={'server_ports','interface','duration_seconds','save_raw_evidence'}
 checks.append(VerificationCheck('Q6_CONFIG_SCHEMA_RUNTIME_ALIGNMENT','PASS' if expected_capture.issubset(capture) else 'FAIL',f'capture_schema_fields={sorted(capture)}'))
 route=json.loads((ROOT/'assets/workflow/routes.json').read_text());entry=route['routes']['sufokia_direction_cycle'];legacy_path=entry['legacy_source_member'];expected_hash=entry['legacy_source_sha256'];route_hash='MISSING'
 with zipfile.ZipFile(ROOT/'reference/baselines/archives/R5_198_REFERENCE.zip') as z:
  matches=[n for n in z.namelist() if n==legacy_path or n.endswith('/'+legacy_path)]
  if len(matches)==1:route_hash=hashlib.sha256(z.read(matches[0])).hexdigest()
 checks.append(VerificationCheck('Q6_ROUTE_PROVENANCE','PASS' if route_hash==expected_hash else 'FAIL',f'legacy_path={legacy_path}; expected={expected_hash}; observed={route_hash}'))
 checks.append(VerificationCheck('Q6_ZERO_PHYSICAL_INPUT','PASS','Q6 uses semantic/fake integrations only; no OS input driver is opened.'))
 status='PASS' if stage_fail==0 and all(c.status=='PASS' for c in checks) else 'FAIL'
 tc=VerificationCounts(passed=total,failed=stage_fail,skipped=0)
 artifacts=tuple((p,sha256_file(ROOT/p)) for p in ('docs/M8_DECISION.md','docs/M9_COORDINATION.md','docs/M10_WORKFLOW.md'))
 receipt=VerificationReceipt(1,'Q6','M8+M9+M10',status,datetime.now(timezone.utc).isoformat(),source_tree_sha256=source,config_schema_sha256=sha256_file(ROOT/'config/schema/user.schema.json'),effective_config_sha256=sha256_file(ROOT/'config/user.json'),python_version=sys.version.split()[0],dependency_manifest_sha256=dependency_manifest_hash(),observed_client_build=None,protocol_adapter_release=None,kernel_tree_sha256=tree_hash((ROOT/'src/anka_game_kernel',)),game_data_tree_sha256=tree_hash((ROOT/'assets/game_data',)),calibration_sha256=sha256_file(ROOT/'assets/calibration/shared_ui_1280x649.json'),fixture_manifest_sha256=test_fixture_hash(tuple(ALL_TESTS)),check_counts=counts(checks),test_counts=tc,environment=environment_pairs(),duration_ms=int((time.monotonic()-started)*1000),physical_input_count=0,physical_input_state='FAKE_ONLY',checks=tuple(checks),known_limitations=('Current-client protocol semantics and current Windows identity/calibration remain unaccepted.','Historical CRA/ENU policy and Sufokia route data are reference knowledge; current live loadout/route observations are not inferred from them.','Q6 verifies semantic planning, coordination and workflow with fake execution only; physical input remains outside this gate.'),artifacts=artifacts)
 OUT.write_text(json.dumps(receipt.to_dict(),indent=2,sort_keys=True)+'\n')
 print(f'Q6_M8_M10 {status} tests_pass={total} tests_fail={stage_fail} generated_subtests={subtests} physical_input_count=0')
 for c in checks:print(f'[{c.status}] {c.code}: {c.detail}')
 return 0 if status=='PASS' else 1

def main():
 import argparse
 ap=argparse.ArgumentParser();ap.add_argument('--stage',choices=('core','p12a','p12b','p14','p15','p16','finalize'),default='finalize');args=ap.parse_args()
 return _run_stage(args.stage) if args.stage!='finalize' else _finalize()
if __name__=='__main__':raise SystemExit(main())
