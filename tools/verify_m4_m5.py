"""Definitive Q4 verifier: M4 Capture + M5 Protocol."""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
from hashlib import sha256
import ast,json,os,re,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from anka_contracts.verification import VerificationCheck,VerificationCounts,VerificationReceipt
from anka_protocol.adapters.dofus_3_7_10_10.manifest import descriptor,CODE_SHA256,EVIDENCE_MANIFEST_SHA256
from anka_protocol.registry import ProtocolRegistry,ProtocolAdapterNotFound
from anka_protocol.upgrade import CurrentBuildIntake
from tools.verification_common import sha256_file,tree_hash,implementation_source_hash,dependency_manifest_hash,test_fixture_hash,environment_pairs

OUT=ROOT/'verification'/'Q4_capture_protocol_receipt.json'
CAPTURE_TESTS=[
 'tests/test_capture_architecture.py','tests/test_capture_cli.py','tests/test_capture_integration.py','tests/test_capture_live.py',
 'tests/test_capture_parser.py','tests/test_capture_transport.py','tests/test_p60_packet_local_wire_provenance.py',
 'tests/test_p61_ipv6_fragment_evidence_integrity.py','tests/test_p62_capture_loss_metadata.py','tests/test_p63_pcapng_section_integrity.py',
 'tests/test_p64_consented_passive_evidence.py','tests/test_p65_capture_abort_integrity.py','tests/test_p66_post_stop_drain_sealing.py','tests/test_m4_wire_envelopes.py']
PROTOCOL_TESTS=[
 'tests/test_protocol_architecture.py','tests/test_protocol_integration.py','tests/test_protocol_wire.py','tests/test_semantic_p7.py',
 'tests/test_semantic_p7_architecture.py','tests/test_semantic_p7_cli.py','tests/test_p10_protocol_qualification.py','tests/test_p23_semantic_transport_finality.py',
 'tests/test_p28_protocol_evidence_intake.py','tests/test_p29_protocol_evidence_comparison.py','tests/test_p30_declarative_research_adapter.py','tests/test_p31_fight_event_research.py',
 'tests/test_p32_protocol_capability_assessment.py','tests/test_p33_shadow_projection_bridge.py','tests/test_p45_historical_handler_lineage.py','tests/test_p45_historical_lifecycle_research.py',
 'tests/test_p46_combined_lifecycle_combat_research.py','tests/test_p46_historical_combat_effect_research.py','tests/test_p47_historical_stream_replay.py',
 'tests/test_p48_capture_to_historical_research.py','tests/test_p49_pcapng_capture_research.py','tests/test_p50_flow_inventory.py','tests/test_p55_transactional_fixture_journal.py',
 'tests/test_p56_source_bound_batch_receipts.py','tests/test_p58_untrusted_admission_boundary.py','tests/test_p59_capture_bound_admission.py','tests/test_p60_packet_local_wire_provenance.py','tests/test_m5_protocol_sdk.py']

def counts(checks):
 return VerificationCounts(passed=sum(x.status=='PASS' for x in checks),failed=sum(x.status=='FAIL' for x in checks),skipped=sum(x.status=='SKIP' for x in checks),not_run=sum(x.status=='NOT_RUN' for x in checks),missing_evidence=sum(x.status=='MISSING_EVIDENCE' for x in checks))

def pytest(files):
 p=subprocess.run([sys.executable,'-m','pytest','-q','--disable-warnings',*files],cwd=ROOT,env={**os.environ,'PYTHONPATH':str(ROOT/'src')},capture_output=True,text=True,timeout=75)
 m=re.search(r'(\d+) passed',p.stdout);s=re.search(r'(\d+) subtests passed',p.stdout)
 return {'rc':p.returncode,'passed':int(m.group(1)) if m else 0,'subtests':int(s.group(1)) if s else 0,'tail':(p.stdout+p.stderr)[-4000:]}

def recompute_code_hash():
 paths=[ROOT/'src/anka_protocol/adapters/dofus_3_7_10_10/adapter.py',ROOT/'src/anka_protocol/adapters/historical_semantic.py',ROOT/'src/anka_protocol/wire.py']
 h=sha256()
 for p in paths:h.update(p.relative_to(ROOT).as_posix().encode()+b'\0'+p.read_bytes()+b'\0')
 return h.hexdigest()

def recompute_archived_r1_code_hash():
 original=('src/anka_protocol/adapters/dofus_3_7_10_10/adapter.py','src/anka_protocol/adapters/historical_semantic.py','src/anka_protocol/wire.py')
 base=ROOT/'reference/m5/releases/adapter-dofus-3.7.10.10-historical-m5-r1'
 h=sha256()
 for rel in original:h.update(rel.encode()+b'\0'+(base/rel).read_bytes()+b'\0')
 return h.hexdigest()

def import_boundary():
 forbidden=('anka_capture','anka_live_state','anka_execution','anka_decision','anka_coordination','anka_workflow','anka_game_kernel','anka_canonical','anka_app','anka_client')
 bad=[]
 for source in (ROOT/'src/anka_protocol').rglob('*.py'):
  tree=ast.parse(source.read_text())
  for n in ast.walk(tree):
   targets=[]
   if isinstance(n,ast.Import):targets=[x.name for x in n.names]
   elif isinstance(n,ast.ImportFrom):targets=[n.module or '']
   for t in targets:
    if any(t==x or t.startswith(x+'.') for x in forbidden):bad.append(f'{source.relative_to(ROOT)}:{t}')
 return bad

CHECKPOINT=ROOT/'verification'/'.q4_checkpoint.json'

def _load_checkpoint():
    try:return json.loads(CHECKPOINT.read_text())
    except (OSError,json.JSONDecodeError):return {}

def _save_stage(name,result):
    data=_load_checkpoint();data['source_tree_sha256']=implementation_source_hash();data[name]=result
    CHECKPOINT.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')

def _run_stage(name):
    files=CAPTURE_TESTS if name=='capture' else PROTOCOL_TESTS
    result=pytest(files);_save_stage(name,result)
    print(f"Q4_{name.upper()} {'PASS' if result['rc']==0 else 'FAIL'} pytest_pass={result['passed']} subtests={result['subtests']}")
    return 0 if result['rc']==0 else 1

def _finalize():
 started=time.monotonic();checks=[];cp=_load_checkpoint();source=implementation_source_hash()
 same=cp.get('source_tree_sha256')==source
 cap=cp.get('capture',{});pro=cp.get('protocol',{})
 checks.append(VerificationCheck('Q4_CHECKPOINT_SOURCE_MATCH','PASS' if same else 'FAIL','Capture/Protocol test checkpoints are bound to the current implementation source hash.'))
 checks.append(VerificationCheck('Q4_CAPTURE_REGRESSION','PASS' if same and cap.get('rc')==0 and cap.get('passed',0)>=161 else 'FAIL',f"pytest_pass={cap.get('passed',0)} subtests={cap.get('subtests',0)}"))
 checks.append(VerificationCheck('Q4_PROTOCOL_REGRESSION','PASS' if same and pro.get('rc')==0 and pro.get('passed',0)>=550 else 'FAIL',f"pytest_pass={pro.get('passed',0)} subtests={pro.get('subtests',0)}"))
 bad=import_boundary();checks.append(VerificationCheck('Q4_PROTOCOL_IMPORT_ISOLATION','PASS' if not bad else 'FAIL',f'forbidden protocol imports={len(bad)}',tuple(bad[:20])))
 d=descriptor();hash_ok=recompute_code_hash()==CODE_SHA256 and sha256_file(ROOT/'reference/protocol/manifest.json')==EVIDENCE_MANIFEST_SHA256
 checks.append(VerificationCheck('Q4_HISTORICAL_RELEASE_HASH_BOUND','PASS' if hash_ok else 'FAIL',f'current corrective release={d.adapter_release_id}; code/evidence hashes exact={hash_ok}'))
 try:r1=json.loads((ROOT/'reference/m5/historical_3_7_10_10_release.json').read_text())
 except Exception:r1={}
 r1_archive_ok=(r1.get('adapter_release_id')=='adapter-dofus-3.7.10.10-historical-m5-r1' and
                recompute_archived_r1_code_hash()==r1.get('code_sha256'))
 checks.append(VerificationCheck('Q4_HISTORICAL_R1_ARCHIVE_IMMUTABLE','PASS' if r1_archive_ok else 'FAIL',f'archived r1 source reconstructs original hash={r1_archive_ok}'))
 lifecycle_ok=d.lifecycle=='REPLAY_CERTIFIED' and not d.action_scopes
 checks.append(VerificationCheck('Q4_HISTORICAL_RELEASE_NOT_LIVE','PASS' if lifecycle_ok else 'FAIL',f'lifecycle={d.lifecycle}; action_scopes={len(d.action_scopes)}'))
 reg=ProtocolRegistry();reg.register(d,lambda **kw:None)
 try:reg.select_active_exact(d.observed_client_build);auto=False
 except ProtocolAdapterNotFound:auto=True
 checks.append(VerificationCheck('Q4_NO_AUTO_ACTIVATION','PASS' if auto else 'FAIL','Registered replay adapter cannot become active by presence/registration.'))
 intake=CurrentBuildIntake().assess(None,())
 checks.append(VerificationCheck('Q4_CURRENT_BUILD_BLOCKED','PASS' if intake.status=='BLOCKED_MISSING_BUILD' and not intake.may_activate else 'FAIL',f'status={intake.status}; may_activate={intake.may_activate}'))
 capture_no_protocol=all('anka_protocol' not in p.read_text() for p in (ROOT/'src/anka_capture').rglob('*.py'))
 checks.append(VerificationCheck('Q4_CAPTURE_PROTOCOL_DECOUPLED','PASS' if capture_no_protocol else 'FAIL','Capture owns WireEnvelope transport boundary and imports no Protocol implementation.'))
 all_pass=all(x.status=='PASS' for x in checks)
 test_counts=VerificationCounts(passed=int(cap.get('passed',0))+int(pro.get('passed',0)),failed=(0 if cap.get('rc')==0 else 1)+(0 if pro.get('rc')==0 else 1),skipped=0)
 common=dict(source_tree_sha256=source,config_schema_sha256=sha256_file(ROOT/'config/schema/user.schema.json'),effective_config_sha256=sha256_file(ROOT/'config/user.json'),python_version=sys.version.split()[0],dependency_manifest_sha256=dependency_manifest_hash(),observed_client_build=None,protocol_adapter_release=d.adapter_release_id,kernel_tree_sha256=tree_hash((ROOT/'src/anka_game_kernel',)),game_data_tree_sha256=tree_hash((ROOT/'assets/game_data',)),calibration_sha256=sha256_file(ROOT/'assets/calibration/shared_ui_1280x649.json'),fixture_manifest_sha256=test_fixture_hash(('qualification/historical_3_7_10_10_synthetic.json','reference/protocol/manifest.json','reference/protocol/dofus_3_7_10_10_scenarios.json','tests/test_m4_wire_envelopes.py','tests/test_m5_protocol_sdk.py')))
 artifacts=[]
 for rel in ('docs/M4_CAPTURE.md','docs/M5_PROTOCOL_SDK_AND_QUALIFICATION.md','reference/m5/historical_3_7_10_10_release.json','reference/m5/historical_3_7_10_10_release_r2.json'):
  artifacts.append((rel,sha256_file(ROOT/rel)))
 receipt=VerificationReceipt(1,'Q4','M4+M5','PASS' if all_pass and not test_counts.failed else 'FAIL',datetime.now(timezone.utc).isoformat(),**common,check_counts=counts(checks),test_counts=test_counts,environment=environment_pairs(),duration_ms=int((time.monotonic()-started)*1000),physical_input_count=0,physical_input_state='DISABLED',checks=tuple(checks),known_limitations=('Historical 3.7.10.10 replay evidence does not certify the current client build.','No protocol adapter is ACTIVE and no physical action scope is authorized.','Current Windows capture and observe-only current-build acceptance remain Q10/Q11 evidence work.'),artifacts=tuple(artifacts))
 OUT.write_text(json.dumps(receipt.to_dict(),indent=2,sort_keys=True)+'\n')
 print(f'Q4_M4_M5 {receipt.status} tests_pass={receipt.test_counts.passed} tests_fail={receipt.test_counts.failed} physical_input_count=0')
 for c in checks:print(f'[{c.status}] {c.code}: {c.detail}')
 return 0 if receipt.status=='PASS' else 1

def main():
 import argparse
 ap=argparse.ArgumentParser();ap.add_argument('--stage',choices=('capture','protocol','finalize'),default='finalize');args=ap.parse_args()
 return _run_stage(args.stage) if args.stage in ('capture','protocol') else _finalize()
if __name__=='__main__':raise SystemExit(main())
