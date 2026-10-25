"""Definitive M1 verifier: Q1 architecture + Q2 contracts/lab/bootstrap."""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import argparse, json, sys, time, tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src')); sys.path.insert(0,str(ROOT))

from anka_app.architecture_guard import audit_source_boundaries, AUTHORITY_OWNERS, SYSTEM_IMPORTS
from anka_contracts.verification import VerificationCheck, VerificationCounts, VerificationReceipt
from anka_observability.api import LocalDiagnostics
from anka_observability.bundle import verify_incident
from tests.lab.zero_input_stack import run_zero_input_contract_stack
from tools.verification_common import sha256_file, tree_hash, implementation_source_hash, dependency_manifest_hash, test_fixture_hash, run_unittest_modules, environment_pairs

Q1=ROOT/'verification'/'Q1_architecture_receipt.json'
Q2=ROOT/'verification'/'Q2_contracts_receipt.json'

def _counts(checks):
    return VerificationCounts(
        passed=sum(c.status=='PASS' for c in checks),failed=sum(c.status=='FAIL' for c in checks),
        skipped=sum(c.status=='SKIP' for c in checks),not_run=sum(c.status=='NOT_RUN' for c in checks),
        missing_evidence=sum(c.status=='MISSING_EVIDENCE' for c in checks))

def _common():
    config_schema=ROOT/'config'/'schema'/'user.schema.json'; effective=ROOT/'config'/'user.json'
    calibration=ROOT/'assets'/'reference'/'calibration_1280x649.json'
    if not calibration.exists():
        found=list((ROOT/'assets').rglob('*1280*649*.json')); calibration=found[0] if found else None
    kernel=tree_hash((ROOT/'src'/'anka_game_kernel',))
    data_dir=ROOT/'assets'/'game_data'
    if not data_dir.exists():
        candidates=[p for p in (ROOT/'assets').iterdir() if p.is_dir() and 'data' in p.name.lower()]
        data_dir=candidates[0] if candidates else ROOT/'assets'
    return dict(
        source_tree_sha256=implementation_source_hash(),
        config_schema_sha256=sha256_file(config_schema) if config_schema.exists() else None,
        effective_config_sha256=sha256_file(effective) if effective.exists() else None,
        python_version=sys.version.split()[0],
        dependency_manifest_sha256=dependency_manifest_hash(),
        observed_client_build=None, protocol_adapter_release=None,
        kernel_tree_sha256=kernel,
        game_data_tree_sha256=tree_hash((data_dir,)),
        calibration_sha256=sha256_file(calibration) if calibration and calibration.exists() else None,
        environment=environment_pairs(),
    )

def _receipt(gate,checks,test_counts,duration_ms,physical_state,fixture_hash,limitations,artifacts=()):
    status='PASS' if all(c.status in ('PASS','SKIP') for c in checks) and all(c.status=='PASS' for c in checks if c.status!='SKIP') else 'FAIL'
    # Gate receipts do not hide NOT_RUN/MISSING_EVIDENCE as pass.
    if any(c.status in ('FAIL','NOT_RUN','MISSING_EVIDENCE') for c in checks): status='FAIL'
    return VerificationReceipt(1,gate,'M1',status,datetime.now(timezone.utc).isoformat(),
        **_common(),fixture_manifest_sha256=fixture_hash,check_counts=_counts(checks),test_counts=test_counts,duration_ms=duration_ms,
        physical_input_count=0,physical_input_state=physical_state,checks=tuple(checks),
        known_limitations=tuple(limitations),artifacts=tuple(artifacts))

def verify_q1():
    started=time.monotonic(); audit=audit_source_boundaries(ROOT/'src'); checks=[]
    checks.append(VerificationCheck('Q1_PACKAGE_GRAPH','PASS' if audit.status=='PASS' else 'FAIL',
        f'{audit.packages} reviewed packages, {audit.modules} modules; violations={len(audit.violations)}',tuple(audit.violations[:20])))
    checks.append(VerificationCheck('Q1_NO_DEPENDENCY_CYCLES','PASS' if not audit.strongly_connected_components else 'FAIL',
        f'Strongly connected top-level components={len(audit.strongly_connected_components)}'))
    checks.append(VerificationCheck('Q1_DYNAMIC_IMPORT_BOUNDARY','PASS' if not audit.dynamic_import_sites else 'FAIL',
        f'Unreviewed dynamic import sites={len(audit.dynamic_import_sites)}',audit.dynamic_import_sites[:20]))
    owners_ok=len(AUTHORITY_OWNERS)==len(set(AUTHORITY_OWNERS)) and set(AUTHORITY_OWNERS.values()).issubset(SYSTEM_IMPORTS)
    checks.append(VerificationCheck('Q1_AUTHORITY_OWNERS','PASS' if owners_ok else 'FAIL',
        f'{len(AUTHORITY_OWNERS)} authorities have explicit owners.'))
    tests=run_unittest_modules(('tests.test_m1_architecture_gate','tests.test_p21_architecture_readiness'))
    checks.append(VerificationCheck('Q1_ARCHITECTURE_MUTATION_TESTS','PASS' if tests['failed']==0 else 'FAIL',
        f"tests={tests['tests_run']} pass={tests['passed']} fail={tests['failed']} skip={tests['skipped']}",tuple(tests['failure_details'])))
    fixture=test_fixture_hash(('tests/test_m1_architecture_gate.py','tests/test_p21_architecture_readiness.py','src/anka_app/architecture_guard.py'))
    doc=ROOT/'docs'/'M1_CONTRACTS_ARCHITECTURE_LAB_BOOTSTRAP.md'
    artifacts=((doc.relative_to(ROOT).as_posix(),sha256_file(doc)),) if doc.exists() else ()
    test_counts=VerificationCounts(passed=tests['passed'],failed=tests['failed'],skipped=tests['skipped'])
    return _receipt('Q1',checks,test_counts,int((time.monotonic()-started)*1000),'DISABLED',fixture,
        ('Offline architecture gate; Windows/client behavior is outside Q1.','Decision->Game Kernel concrete imports remain explicitly transitional and are addressed by the KernelQueries port/cutover roadmap.'),artifacts)

def verify_q2():
    started=time.monotonic(); checks=[]
    contract_tests=run_unittest_modules(('tests.test_m1_contracts_lab','tests.test_diagnostics','tests.test_bootstrap'))
    checks.append(VerificationCheck('Q2_CONTRACT_AND_INVALID_CASES','PASS' if contract_tests['failed']==0 else 'FAIL',
        f"tests={contract_tests['tests_run']} pass={contract_tests['passed']} fail={contract_tests['failed']} skip={contract_tests['skipped']}",tuple(contract_tests['failure_details'])))
    result=run_zero_input_contract_stack()
    zero=(result.physical_input_count==0 and result.outcome_status=='REJECTED_NOT_SENT')
    checks.append(VerificationCheck('Q2_FAKE_FULL_STACK_ZERO_INPUT','PASS' if zero else 'FAIL',
        f'state={result.state_reads} kernel={result.kernel_queries} client_identity={result.identity_reads} projection={result.projection_reads} execution={result.execution_submissions} physical_input={result.physical_input_count} outcome={result.outcome_status}'))
    bat=(ROOT/'tools'/'windows'/'_entry.bat').read_text(encoding='utf-8',errors='replace')
    bootstrap_static=all(x in bat for x in ('STAGE=BAT_ENTERED','STAGE=PYTHON_NOT_FOUND','ANKA_BOOTLOG=','DEPENDENCY_INSTALL_FAILED','tools\\bootstrap_failure.py'))
    checks.append(VerificationCheck('Q2_BOOTSTRAP_EVIDENCE_PATH','PASS' if bootstrap_static else 'FAIL',
        'setup/start shared BAT has pre-Python local evidence and dependency-failure incident export paths.'))
    with tempfile.TemporaryDirectory() as td:
        obs=LocalDiagnostics(Path(td),run_id='run-m1-verifier',invocation_id='inv-m1-verifier')
        obs.record('verification.injected_failure',severity='ERROR',owner_system='anka_observability',physical_input_state='NOT_SENT',canonical_cursor=0,boundary='verification.fake',failure_code='FAULT_INJECTION')
        incident=obs.export_incident('FAULT_INJECTION',boundary='verification.fake',detail='M1 structured incident test')
        incident_ok=verify_incident(incident)['status']=='PASS'
    checks.append(VerificationCheck('Q2_STRUCTURED_DIAGNOSTIC_INCIDENT','PASS' if incident_ok else 'FAIL',
        'Injected fake failure emits a bounded sanitized incident bundle whose manifest verifies.'))
    fixture=test_fixture_hash(('tests/test_m1_contracts_lab.py','tests/test_diagnostics.py','tests/test_bootstrap.py','tests/lab','src/anka_contracts'))
    doc=ROOT/'docs'/'M1_CONTRACTS_ARCHITECTURE_LAB_BOOTSTRAP.md'
    artifacts=((doc.relative_to(ROOT).as_posix(),sha256_file(doc)),) if doc.exists() else ()
    test_counts=VerificationCounts(passed=contract_tests['passed'],failed=contract_tests['failed'],skipped=contract_tests['skipped'])
    return _receipt('Q2',checks,test_counts,int((time.monotonic()-started)*1000),'FAKE_ONLY',fixture,
        ('Q2 proves contract semantics and fake/bootstrap evidence offline; it does not certify current Dofus protocol, Windows identity, calibration, or physical input.',
         'Missing-Python branch is statically verified on this non-Windows host; actual cmd.exe execution remains a Q10 Windows acceptance item.'),artifacts)

def write_receipt(path,receipt):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(receipt.to_dict(),indent=2,sort_keys=True)+'\n',encoding='utf-8')

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument('--write-receipts',action='store_true'); args=ap.parse_args(argv)
    q1=verify_q1(); q2=verify_q2()
    if args.write_receipts:
        write_receipt(Q1,q1); write_receipt(Q2,q2)
    for r in (q1,q2):
        print(f'{r.gate_id}_{r.milestone} {r.status} checks={len(r.checks)} physical_input_count={r.physical_input_count}')
        for c in r.checks: print(f'[{c.status}] {c.code}: {c.detail}')
    return 0 if q1.status=='PASS' and q2.status=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
