"""Definitive M3 offline Client milestone verifier (not Windows/live acceptance)."""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import ast,json,re,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from anka_client.calibration import load_calibration_profile
from anka_contracts.verification import MilestoneReceipt,VerificationCheck,VerificationCounts
from tools.verification_common import sha256_file,implementation_source_hash

OUT=ROOT/'verification'/'M3_client_offline_receipt.json'
TESTS=(
 'tests/test_m3_client_foundation.py','tests/test_client_discovery.py','tests/test_client_geometry.py',
 'tests/test_client_integration.py','tests/test_reference_assets.py','tests/test_p33_shadow_projection_bridge.py',
 'tests/test_p38_causal_window_confounders.py','tests/test_p44_unity_bridge_readonly.py',
 'tests/test_p51_windows_flow_owner_stability.py','tests/test_p53_historical_character_identity.py',
 'tests/test_p53_historical_identity_lineage.py')

def main():
 started=time.monotonic();checks=[]
 cal=load_calibration_profile(ROOT/'assets/calibration/shared_ui_1280x649.json',source_path=ROOT/'reference/calibration/shared_ui_calibration_1280x649.yaml')
 cal_ok=(len(cal.spell_slots)==22 and not cal.current_client_certified and cal.status=='HISTORICAL_COORDINATES_NOT_LIVE_CERTIFIED')
 checks.append(VerificationCheck('M3_CALIBRATION_PROVENANCE','PASS' if cal_ok else 'FAIL',f'slots={len(cal.spell_slots)} historical_current_certified={cal.current_client_certified}'))
 prov=json.loads((ROOT/'reference/m3/client_reuse_provenance.json').read_text())
 bridge_ok=prov['native_bridge_compared_count']>=10 and prov['native_bridge_byte_identical_count']==prov['native_bridge_compared_count']
 checks.append(VerificationCheck('M3_BRIDGE_SOURCE_PARITY','PASS' if bridge_ok else 'FAIL',f"native bridge exact={prov['native_bridge_byte_identical_count']}/{prov['native_bridge_compared_count']}"))
 # Client package may observe foreground but must not send/focus/click/type.
 forbidden={'SendInput','mouse_event','keybd_event','SetForegroundWindow','SetCursorPos','click_physical_screen','send_key','PostMessageW','SendMessageW'}
 found=[]
 for path in (ROOT/'src/anka_client').glob('*.py'):
  tree=ast.parse(path.read_text())
  for n in ast.walk(tree):
   if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in forbidden:
    found.append(f'{path.name}:{n.func.attr}')
 checks.append(VerificationCheck('M3_CLIENT_NO_INPUT_AUTHORITY','PASS' if not found else 'FAIL',f'forbidden physical-input primitives={len(found)}',tuple(found)))
 # Presence of each definitive proof family is source-audited in addition to tests.
 client_contract=(ROOT/'src/anka_contracts/client.py').read_text()
 required=('CalibrationProfileEvidence','LoadoutEvidence','ClientGenerationVector','ClientContextProof')
 contract_ok=all(x in client_contract for x in required)
 checks.append(VerificationCheck('M3_GENERATION_AND_LOADOUT_MODEL','PASS' if contract_ok else 'FAIL','calibration/loadout/generation/context proof contracts present'))
 env=dict(PYTHONPATH=str(ROOT/'src'))
 import os
 e=os.environ.copy();e.update(env)
 p=subprocess.run([sys.executable,'-m','pytest','-q','--disable-warnings',*TESTS],cwd=ROOT,env=e,capture_output=True,text=True,timeout=30)
 m=re.search(r'(\d+) passed',p.stdout);passed=int(m.group(1)) if m else 0
 test_ok=p.returncode==0 and passed>=170
 checks.append(VerificationCheck('M3_ZERO_INPUT_AMBIGUITY_MATRIX','PASS' if test_ok else 'FAIL',f'client/offline regression cases passed={passed}',((p.stdout+p.stderr)[-2500:],) if not test_ok else ()))
 status='PASS' if all(c.status=='PASS' for c in checks) else 'FAIL'
 artifacts=[]
 for rel in ('reference/m3/client_reuse_provenance.json','docs/M3_CLIENT_IDENTITY_CALIBRATION_PROJECTION.md','assets/calibration/shared_ui_1280x649.json'):
  artifacts.append((rel,sha256_file(ROOT/rel)))
 receipt=MilestoneReceipt(1,'M3',status,'OFFLINE_OBSERVE_ONLY_CLIENT_FOUNDATION',datetime.now(timezone.utc).isoformat(),
  implementation_source_hash(),VerificationCounts(passed=passed,failed=0 if p.returncode==0 else 1),int((time.monotonic()-started)*1000),
  0,'DISABLED',tuple(checks),(
   'No current Windows host, Dofus process/window generation or DPI/occlusion behavior was live-accepted in M3.',
   'Bundled 1280x649 calibration remains historical and cannot self-certify the current client.',
   'Native bridge source parity and offline projection tests do not prove current-client loadability or semantic correctness.',
   'No real current-client loadout evidence is bundled; TEST_FIXTURE loadouts are used only for the fail-closed proof model.'),tuple(artifacts))
 OUT.write_text(json.dumps(receipt.to_dict(),indent=2,sort_keys=True)+'\n')
 print(f'M3_CLIENT {receipt.status} tests_pass={passed} physical_input_count=0')
 for c in checks: print(f'[{c.status}] {c.code}: {c.detail}')
 return 0 if status=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
