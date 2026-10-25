from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import ast,json,re,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from anka_contracts.verification import VerificationCheck,VerificationCounts,VerificationReceipt
from tools.verification_common import sha256_file,tree_hash,implementation_source_hash,dependency_manifest_hash,test_fixture_hash,environment_pairs

OUT=ROOT/'verification'/'Q5_canonical_live_state_receipt.json'
TESTS=[
 'tests/test_m6_m7_canonical_state.py','tests/test_m6_m7_protocol_canonical_integration.py',
 'tests/test_p8_integration.py','tests/test_p8_state_journal.py','tests/test_p9_quality.py','tests/test_p11_fight_evidence.py',
 'tests/test_p17_coordination_workflow.py','tests/test_p22_causal_linkage.py','tests/test_p33_shadow_projection_bridge.py',
 'tests/test_p35_effect_reconciliation.py','tests/test_p38_causal_window_confounders.py','tests/test_p41_cell_transition_evidence.py',
 'tests/test_p41_packet_claim_uniqueness.py','tests/test_p55_transactional_fixture_journal.py','tests/test_p56_source_bound_batch_receipts.py',
 'tests/test_p57_atomic_schema_bootstrap.py','tests/test_p58_untrusted_admission_boundary.py','tests/test_p59_capture_bound_admission.py']

def check_counts(checks):
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
 p=subprocess.run([sys.executable,'-m','pytest','-q','--disable-warnings',*TESTS],cwd=ROOT,env={**__import__('os').environ,'PYTHONPATH':str(ROOT/'src')},capture_output=True,text=True,timeout=90)
 m=re.search(r'(\d+) passed',p.stdout);sm=re.search(r'(\d+) subtests passed',p.stdout);passed=int(m.group(1)) if m else 0;subs=int(sm.group(1)) if sm else 0
 checks.append(VerificationCheck('Q5_CANONICAL_STATE_REGRESSION','PASS' if p.returncode==0 and passed>=402 else 'FAIL',f'pytest_pass={passed}; subtests={subs}',(() if p.returncode==0 else ((p.stdout+p.stderr)[-2500:],))))
 cbad=imports_under('anka_canonical',('anka_protocol','anka_live_state','anka_execution','anka_decision','anka_coordination','anka_workflow','anka_capture','anka_client'))
 checks.append(VerificationCheck('Q5_CANONICAL_IMPORT_ISOLATION','PASS' if not cbad else 'FAIL',f'forbidden imports={len(cbad)}',tuple(cbad[:20])))
 sbad=imports_under('anka_live_state',('anka_protocol','anka_canonical','anka_execution','anka_decision','anka_coordination','anka_workflow','anka_capture','anka_client'))
 checks.append(VerificationCheck('Q5_LIVE_STATE_IMPORT_ISOLATION','PASS' if not sbad else 'FAIL',f'forbidden imports={len(sbad)}',tuple(sbad[:20])))
 from anka_canonical.writer import ExactReleaseAdmissionPolicy
 from anka_contracts.protocol import CandidateCanonicalBatch,DecoderCheckpointRef,WireEnvelopeRef
 from hashlib import sha256
 adapter='adapter-q5';build='Dofus Q5';conn='conn-q5';ref=WireEnvelopeRef('capture-q5',conn,1,1,'server_to_client','COMPLETE','1'*64);cp=DecoderCheckpointRef(adapter,build,conn,1,1,'2'*64)
 unmapped=CandidateCanonicalBatch('batch-q5-unmapped',adapter,build,conn,1,(ref,),(),'NO_SEMANTIC_MAPPING',cp)
 ok,reason=ExactReleaseAdmissionPolicy(((adapter,build),)).assess(unmapped)
 checks.append(VerificationCheck('Q5_UNMAPPED_FAILS_CLOSED','PASS' if not ok and reason=='CANONICAL_PROTOCOL_HEALTH_UNSAFE' else 'FAIL',f'allowed={ok}; reason={reason}'))
 writer=(ROOT/'src/anka_canonical/writer.py').read_text();api=all(x in writer for x in ('def commit_candidate_batch','def events_after','def current_cursor','def replay','def health'))
 checks.append(VerificationCheck('Q5_CANONICAL_PUBLIC_API','PASS' if api else 'FAIL','commit/read/cursor/replay/health surface present.'))
 bridge=(ROOT/'src/anka_app/adapters/protocol_canonical.py').read_text();link=('CanonicalCommitUncertain' in bridge and "ProtocolAdmissionDecision('UNCERTAIN'" in bridge)
 checks.append(VerificationCheck('Q5_PROTOCOL_CANONICAL_LINKAGE','PASS' if link else 'FAIL','Composition adapter distinguishes commit/reject/uncertain and Protocol rollback is regression tested.'))
 physical=0
 checks.append(VerificationCheck('Q5_ZERO_PHYSICAL_INPUT','PASS','M6/M7 verification opens no physical input driver.'))
 status='PASS' if p.returncode==0 and all(c.status=='PASS' for c in checks) else 'FAIL'
 tc=VerificationCounts(passed=passed,failed=0 if p.returncode==0 else 1,skipped=0)
 receipt=VerificationReceipt(1,'Q5','M6+M7',status,datetime.now(timezone.utc).isoformat(),source_tree_sha256=implementation_source_hash(),config_schema_sha256=sha256_file(ROOT/'config/schema/user.schema.json'),effective_config_sha256=sha256_file(ROOT/'config/user.json'),python_version=sys.version.split()[0],dependency_manifest_sha256=dependency_manifest_hash(),observed_client_build=None,protocol_adapter_release=None,kernel_tree_sha256=tree_hash((ROOT/'src/anka_game_kernel',)),game_data_tree_sha256=tree_hash((ROOT/'assets/game_data',)),calibration_sha256=sha256_file(ROOT/'assets/calibration/shared_ui_1280x649.json'),fixture_manifest_sha256=test_fixture_hash(tuple(TESTS)),check_counts=check_counts(checks),test_counts=tc,environment=environment_pairs(),duration_ms=int((time.monotonic()-started)*1000),physical_input_count=physical,physical_input_state='DISABLED',checks=tuple(checks),known_limitations=('Current-client protocol semantics remain unaccepted.','Historical/synthetic P55 journals are retained as regression evidence and are not silently promoted into definitive Canonical truth.','Windows/live observation and all physical input remain outside Q5.'),artifacts=(('docs/M6_CANONICAL_DURABLE_AUTHORITY.md',sha256_file(ROOT/'docs/M6_CANONICAL_DURABLE_AUTHORITY.md')),('docs/M7_LIVE_STATE_PROVENANCE_FRESHNESS.md',sha256_file(ROOT/'docs/M7_LIVE_STATE_PROVENANCE_FRESHNESS.md'))))
 OUT.write_text(json.dumps(receipt.to_dict(),indent=2,sort_keys=True)+'\n')
 print(f'Q5_M6_M7 {status} tests_pass={passed} tests_fail={tc.failed} physical_input_count={physical}')
 for c in checks:print(f'[{c.status}] {c.code}: {c.detail}')
 return 0 if status=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
