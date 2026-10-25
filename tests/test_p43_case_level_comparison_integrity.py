"""P43: a matched research result belongs to one precise source case, not just a ZIP."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from anka_app.cli import ROOT
from anka_app.protocol_evidence_compare import compare_pack
from anka_protocol.capability_matrix import assess_capabilities
from anka_protocol.evidence_intake import inspect_evidence_pack
from tests.test_p29_protocol_evidence_comparison import archive
from tests.test_p32_protocol_capability_assessment import intake, comparison


class P43CaseLevelComparisonTests(unittest.TestCase):
    def real_result(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'evidence.zip'
        path.write_bytes(archive())
        return inspect_evidence_pack(path), compare_pack(path, root=ROOT)

    def self_assert_blocked(self, intake_report, comparison_result):
        report = assess_capabilities(intake_report, comparison_result)
        self.assertEqual(report['status'], 'RESEARCH_COMPARISON_BLOCKED')
        self.assertEqual(next(c for c in report['capabilities'] if c['capability']=='actor_ap')['matched_cases'], 0)
        self.assertFalse(report['live_semantic_certified'])
        self.assertFalse(report['adapter_activated'])

    def test_real_evidence_rows_carry_private_case_binding(self):
        src, result = self.real_result()
        row = result['case_results'][0]
        self.assertRegex(row['case_binding'], r'^[A-Z2-7]{52}$')
        self.assertNotIn(src.protocol_build, str(result))
        self.assertNotIn(src.adapter_id, str(result))
        self.assertEqual(next(c for c in assess_capabilities(src,result)['capabilities']
                              if c['capability']=='actor_ap')['matched_cases'], 1)

    def test_missing_case_binding_must_not_count_a_matching_packet(self):
        src, result = self.real_result()
        damaged = deepcopy(result)
        damaged['case_results'][0].pop('case_binding',None)
        self.self_assert_blocked(src, damaged)

    def test_different_case_binding_must_not_count(self):
        src, result = self.real_result()
        damaged = deepcopy(result)
        damaged['case_results'][0]['case_binding'] = 'A'*52
        self.self_assert_blocked(src,damaged)

    def test_same_capability_different_role_result_swap_is_rejected(self):
        cases = [('actor_ap','leader',True,True),('actor_ap','follower',True,True)]
        src = intake(cases)
        result = comparison(cases,['FIELD_MISMATCH','MATCHED_RESEARCH_ONLY'])
        # Both rows have the same capability. Old P42 validated only the index/capability,
        # so moving a matched row to the leader's index was accepted as different proof.
        rows = result['case_results']
        rows[0]['case_binding'],rows[1]['case_binding'] = rows[1]['case_binding'],rows[0]['case_binding']
        self.self_assert_blocked(src,result)

    def test_true_same_capability_multi_role_evidence_stays_valid(self):
        cases = [('actor_ap','leader',True,True),('actor_ap','follower',True,True)]
        src = intake(cases)
        r = assess_capabilities(src,comparison(cases))
        cap = next(c for c in r['capabilities'] if c['capability']=='actor_ap')
        self.assertEqual(cap['matched_cases'],2)
        self.assertEqual(cap['status'],'RESEARCH_MATCHED_NOT_CERTIFIED')
        self.assertFalse(r['current_build_certified'])

    def test_field_mismatch_without_field_explanation_fails_consistency(self):
        cases=[('actor_ap','leader',True,True)]
        src=intake(cases)
        forged=comparison(cases,['FIELD_MISMATCH'])
        forged['case_results'][0]['mismatch_fields']=[]
        self.self_assert_blocked(src,forged)

    def test_matched_case_with_reported_mismatch_field_fails(self):
        src,result=self.real_result()
        damaged=deepcopy(result)
        damaged['case_results'][0]['mismatch_fields']=['ap']
        self.self_assert_blocked(src,damaged)

    def test_unknown_status_cannot_be_counted_as_complete_comparison(self):
        src,result=self.real_result()
        damaged=deepcopy(result)
        damaged['case_results'][0]['status']='SOME_UNRECOGNIZED_REASON'
        damaged['matched_cases']=0
        damaged['status']='RESEARCH_COMPARISON_BLOCKED'
        self.self_assert_blocked(src,damaged)

    def test_finding_counts_must_match_case_rows(self):
        src,result=self.real_result()
        damaged=deepcopy(result)
        damaged['finding_counts']={'MATCHED_RESEARCH_ONLY':999}
        self.self_assert_blocked(src,damaged)


if __name__=='__main__':unittest.main()
