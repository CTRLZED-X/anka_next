"""P10 qualification must detect broken semantics and must never certify live play."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from hashlib import sha256
import json,unittest,subprocess,sys,ast
from anka_protocol.qualification import (run_suite,load_suite,REQUIRED_SCENARIOS,
    QualificationReport,MAX_CASES,MAX_SUITE_BYTES)
from anka_protocol.adapters.historical_semantic import HistoricalSemanticAdapter,ADAPTER_ID,BUILD
from anka_app.protocol_qualification import qualify_historical
from anka_contracts.semantic import SemanticResult

ROOT=Path(__file__).resolve().parents[1]
SUITE=ROOT/'qualification/historical_3_7_10_10_synthetic.json'

def qualify(suite=SUITE, requested_build=BUILD, decoder=HistoricalSemanticAdapter):
    return run_suite(suite,requested_build=requested_build,
        adapter_factory=decoder,adapter_id=ADAPTER_ID,
        historical_build=BUILD,adapter_sha256='abc123')

class P10Qualification(unittest.TestCase):
    def test_reference_synthetic_suite_passes_but_is_not_live(self):
        r=qualify()
        self.assertEqual(r.status,'SYNTHETIC_CONTRACT_PASS_LIVE_BLOCKED')
        self.assertEqual(len(r.cases),14)
        self.assertTrue(all(c.passed for c in r.cases))
        self.assertFalse(r.live_semantic_certified)
        self.assertEqual(r.canonical_commits,0)
        self.assertFalse(r.physical_input_sent)
        self.assertEqual(r.to_dict()['blocked_gates'][0],'CURRENT_BUILD_RAW_EVIDENCE_ABSENT')
    def test_all_failure_scenarios_present(self):
        _,_,_,cases=load_suite(SUITE)
        self.assertFalse(REQUIRED_SCENARIOS-{c.scenario for c in cases})
        self.assertEqual(len({c.case_id for c in cases}),len(cases))
    def test_external_new_build_cannot_reuse_synthetic_green(self):
        r=qualify(requested_build='Dofus 3.7.11.11')
        self.assertEqual(r.status,'QUALIFICATION_FAILED_LIVE_BLOCKED')
        self.assertEqual(r.to_dict()['passed'],14)
        self.assertFalse(r.live_semantic_certified)
    def test_report_cannot_claim_live_certified(self):
        r=qualify()
        for changed in [dict(live_semantic_certified=True),dict(canonical_commits=1),dict(physical_input_sent=True)]:
            with self.assertRaisesRegex(ValueError,'QUALIFICATION_LIVE_AUTHORITY_FORBIDDEN'):
                replace(r,**changed)
    def test_app_level_wiring_still_never_authorizes(self):
        r=qualify_historical(root=ROOT)
        self.assertFalse(r['live_ready'])
        self.assertFalse(r['gameplay_capabilities_certified'])
        self.assertEqual(r['canonical_commits'],0)
        self.assertEqual(r['passed'],r['total'])
        self.assertEqual(len(r['adapter_sha256']),64)
        self.assertEqual(len(r['fixture_sha256']),64)
    def test_cli_outputs_safe_receipt(self):
        done=subprocess.run([sys.executable,'-m','anka_app.cli','protocol-qualify'],cwd=ROOT,
                 capture_output=True,text=True,timeout=20)
        self.assertEqual(done.returncode,0,done.stderr)
        r=json.loads(next(x.removeprefix('ANKA_RESULT=') for x in done.stdout.splitlines() if x.startswith('ANKA_RESULT=')))
        self.assertEqual(r['status'],'SYNTHETIC_CONTRACT_PASS_LIVE_BLOCKED')
        self.assertNotIn('body_hex',done.stdout)
        self.assertFalse(r['live_ready'])
    def test_cli_reports_new_build_incompatibility(self):
        done=subprocess.run([sys.executable,'-m','anka_app.cli','protocol-qualify','Dofus 3.7.11.11'],cwd=ROOT,
                 capture_output=True,text=True,timeout=20)
        self.assertEqual(done.returncode,0)
        self.assertIn('QUALIFICATION_FAILED_LIVE_BLOCKED',done.stdout)
    def test_cli_wrong_arguments_are_blocked_with_incident(self):
        done=subprocess.run([sys.executable,'-m','anka_app.cli','protocol-qualify','A','B'],cwd=ROOT,
                 capture_output=True,text=True,timeout=20)
        self.assertEqual(done.returncode,40)
        self.assertIn('ANKA_BUNDLE=',done.stdout)
    def test_module_import_boundary(self):
        for path in (ROOT/'src/anka_protocol').rglob('*.py'):
            tree=ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom):
                    self.assertFalse((node.module or '').startswith(('anka_capture','anka_live_state','anka_app','anka_execution')),path)

    def _modified(self,mutate):
        doc=json.loads(SUITE.read_text())
        mutate(doc)
        tmp=TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        file=Path(tmp.name)/'synthetic.json'
        file.write_text(json.dumps(doc))
        return file
    def test_wrong_golden_value_is_caught(self):
        p=self._modified(lambda d:d['cases'][0]['expected_candidates'][0].__setitem__('value',300))
        r=qualify(p)
        self.assertEqual(r.status,'QUALIFICATION_FAILED_LIVE_BLOCKED')
        self.assertIn('CANONICAL_FACT_MISMATCH',r.cases[0].failure_codes)
    def test_wrong_fixture_direction_is_caught(self):
        p=self._modified(lambda d:d['cases'][0].__setitem__('direction','client_to_server'))
        r=qualify(p)
        self.assertIn('STATUS_MISMATCH',r.cases[0].failure_codes)
    def test_changed_fixture_build_rejected(self):
        p=self._modified(lambda d:d.__setitem__('historical_build','Dofus 3.7.11.11'))
        with self.assertRaisesRegex(ValueError,'QUALIFICATION_ADAPTER_OR_BUILD_MISMATCH'):
            qualify(p)
    def test_wrong_adapter_label_rejected(self):
        p=self._modified(lambda d:d.__setitem__('adapter_id','different'))
        with self.assertRaisesRegex(ValueError,'QUALIFICATION_ADAPTER_OR_BUILD_MISMATCH'):
            qualify(p)
    def test_no_reclassifying_synthetic_as_real(self):
        p=self._modified(lambda d:d.__setitem__('evidence_type','CURRENT_CLIENT_CERTIFIED'))
        with self.assertRaisesRegex(ValueError,'QUALIFICATION_FIXTURE_NOT_SYNTHETIC'):
            qualify(p)
    def test_unexpected_privilege_flag_rejected(self):
        p=self._modified(lambda d:d.__setitem__('live_ready',True))
        with self.assertRaisesRegex(ValueError,'QUALIFICATION_FIXTURE_SCHEMA_INVALID'):
            qualify(p)
    def test_case_fake_live_claim_rejected(self):
        p=self._modified(lambda d:d['cases'][0].__setitem__('certified',True))
        with self.assertRaisesRegex(ValueError,'QUALIFICATION_FIXTURE_SCHEMA_INVALID'):
            qualify(p)
    def test_duplicate_case_id_rejected(self):
        p=self._modified(lambda d:d['cases'][1].__setitem__('id',d['cases'][0]['id']))
        with self.assertRaisesRegex(ValueError,'QUALIFICATION_DUPLICATE_CASE_ID'):
            qualify(p)
    def test_missing_mandatory_case_is_not_green(self):
        p=self._modified(lambda d:d.__setitem__('cases',[x for x in d['cases'] if x['scenario']!='malformed_wire']))
        r=qualify(p)
        self.assertEqual(r.status,'QUALIFICATION_FAILED_LIVE_BLOCKED')
        self.assertIn('malformed_wire',r.missing_scenarios)
    def test_empty_cases_rejected(self):
        p=self._modified(lambda d:d.__setitem__('cases',[]))
        with self.assertRaisesRegex(ValueError,'QUALIFICATION_CASE_COUNT_INVALID'):
            qualify(p)
    def test_oversized_case_count_rejected(self):
        def f(d):
            d['cases']=[dict(d['cases'][0],id=f'case-{i}') for i in range(MAX_CASES+1)]
        p=self._modified(f)
        with self.assertRaisesRegex(ValueError,'QUALIFICATION_CASE_COUNT_INVALID'):
            qualify(p)
    def test_invalid_hex_is_rejected(self):
        p=self._modified(lambda d:d['cases'][0].__setitem__('body_hex','zz'))
        with self.assertRaisesRegex(ValueError,'QUALIFICATION_BODY_INVALID'):
            qualify(p)
    def test_illegal_negative_generation_rejected(self):
        p=self._modified(lambda d:d['cases'][0].__setitem__('generation',-1))
        with self.assertRaisesRegex(ValueError,'QUALIFICATION_ORDINAL_INVALID'):
            qualify(p)
    def test_bool_forgery_for_packet_number_rejected(self):
        p=self._modified(lambda d:d['cases'][0].__setitem__('packet_number',True))
        with self.assertRaisesRegex(ValueError,'QUALIFICATION_ORDINAL_INVALID'):
            qualify(p)
    def test_explicit_authority_in_expected_fact_rejected(self):
        p=self._modified(lambda d:d['cases'][0]['expected_candidates'][0].__setitem__('authority','PRODUCTION'))
        with self.assertRaisesRegex(ValueError,'QUALIFICATION_FIXTURE_SCHEMA_INVALID'):
            qualify(p)
    def test_fake_result_that_ignores_wire_is_caught(self):
        class AlwaysSuccess:
            def __init__(self,*,requested_build):self.build=requested_build
            def decode(self,wire,*,context=None):
                return SemanticResult('NO_SEMANTIC_MAPPING',ADAPTER_ID,self.build,wire.name)
        r=qualify(decoder=AlwaysSuccess)
        self.assertEqual(r.status,'QUALIFICATION_FAILED_LIVE_BLOCKED')
        self.assertLess(r.to_dict()['passed'],r.to_dict()['total'])
    def test_adapter_crash_is_caught_as_failure(self):
        class Crashes:
            def __init__(self,*,requested_build):pass
            def decode(self,wire,*,context=None):raise RuntimeError('bad')
        r=qualify(decoder=Crashes)
        self.assertTrue(all('ADAPTER_EXCEPTION' in c.failure_codes for c in r.cases))
        self.assertEqual(r.status,'QUALIFICATION_FAILED_LIVE_BLOCKED')
    def test_fixture_hash_tracks_modifications(self):
        changed=self._modified(lambda d:d['cases'][0].__setitem__('expected_candidates',[dict(d['cases'][0]['expected_candidates'][0],value=8)]+d['cases'][0]['expected_candidates'][1:]))
        self.assertNotEqual(load_suite(changed)[2],load_suite(SUITE)[2])
    def test_contract_expected_failure_mismatch_is_caught(self):
        p=self._modified(lambda d:d['cases'][5].__setitem__('expected_failure','OTHER'))
        self.assertIn('FAILURE_CODE_MISMATCH',qualify(p).cases[5].failure_codes)
    def test_body_bytes_not_exported_in_receipt(self):
        r=qualify_historical(root=ROOT)
        text=json.dumps(r)
        doc=json.loads(SUITE.read_text())
        self.assertNotIn(doc['cases'][0]['body_hex'],text)
        self.assertNotIn('body_hex',text)
    def test_no_historical_to_authoritative_conversion_in_app(self):
        code=(ROOT/'src/anka_app/protocol_qualification.py').read_text()
        self.assertNotIn('append_fixture',code)
        self.assertNotIn('CanonicalDraft(',code)

if __name__=='__main__':unittest.main()

# Additional integration assurances for future adapter replacement:
class P10StagingBoundary(unittest.TestCase):
    def test_historical_fixture_drafts_cannot_commit_despite_positive_context(self):
        from anka_canonical.staging import CanonicalStagingGate
        from anka_contracts.protocol import WireMessage
        from anka_protocol.qualification import load_suite
        _,_,_,cases=load_suite(SUITE)
        gate=CanonicalStagingGate()
        decoder=HistoricalSemanticAdapter(requested_build=BUILD)
        for c in cases:
            if c.case_id not in ('basic_ap_mp','cooldown_positive','hp_verified_context'):
                continue
            wire=WireMessage(c.direction,c.name,c.body,c.packet_number,'synthetic-case',c.generation,c.message_index)
            outcome=gate.inspect(decoder.decode(wire,context=c.context),
                                 transport_complete=True,account_attested=True)
            self.assertEqual(outcome.status,'STAGED_UNCERTIFIED')
            self.assertEqual(outcome.committed_events,0)
            self.assertIsNone(outcome.live_state_revision)
        self.assertEqual(gate.staged_count,4)
    def test_repeated_identical_wire_can_remain_separately_staged(self):
        from anka_canonical.staging import CanonicalStagingGate
        from anka_contracts.protocol import WireMessage
        _,_,_,cases=load_suite(SUITE)
        matches=[c for c in cases if c.scenario=='repeated_occurrence']
        gate=CanonicalStagingGate();decoder=HistoricalSemanticAdapter(requested_build=BUILD)
        for c in matches:
            wire=WireMessage(c.direction,c.name,c.body,c.packet_number,'same-flow',c.generation,c.message_index)
            self.assertEqual(gate.inspect(decoder.decode(wire)).status,'STAGED_UNCERTIFIED')
        self.assertEqual(gate.staged_count,4)
    def test_new_build_output_explicitly_identifies_incompatibility(self):
        r=qualify_historical(root=ROOT,requested_build='Dofus 3.7.11.11')
        self.assertIn('REQUESTED_BUILD_UNSUPPORTED',r['blocked_gates'])
        self.assertFalse(r['live_ready'])
