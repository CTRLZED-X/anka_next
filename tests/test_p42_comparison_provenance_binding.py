"""P42: a comparison from another archive/build must never count as matching research."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from anka_app.cli import ROOT
from anka_app.protocol_evidence_compare import compare_pack
from anka_protocol.capability_matrix import assess_capabilities
from anka_protocol.evidence_intake import inspect_evidence_pack, evidence_binding_id
from tests.test_p29_protocol_evidence_comparison import archive


class P42EvidenceBindingTests(unittest.TestCase):
    def build_pack(self, **kwargs):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name)/'pack.zip'
        path.write_bytes(archive(**kwargs))
        return path

    def test_real_comparison_carries_archive_build_and_adapter_identity(self):
        path = self.build_pack()
        report = inspect_evidence_pack(path)
        comp = compare_pack(path, root=ROOT)
        self.assertEqual(comp['comparison_binding'], evidence_binding_id(
            report.archive_sha256, report.protocol_build, report.adapter_id))
        # Comparison reports stay free of potentially identifying build text.
        self.assertNotIn(report.protocol_build, str(comp))
        self.assertNotIn(report.adapter_id, str(comp))
        cap = next(c for c in assess_capabilities(report,comp)['capabilities'] if c['capability']=='actor_ap')
        self.assertEqual(cap['matched_cases'],1)

    def test_incorrect_source_hash_must_not_count_matched_case(self):
        path = self.build_pack()
        report = inspect_evidence_pack(path)
        comp = compare_pack(path, root=ROOT)
        self.assertGreater(comp['matched_cases'],0)
        different = replace(report,archive_sha256='f'*64)
        result = assess_capabilities(different,comp)
        self.assertEqual(result['status'],'RESEARCH_COMPARISON_BLOCKED')
        self.assertEqual(next(c for c in result['capabilities'] if c['capability']=='actor_ap')['matched_cases'],0)

    def test_same_case_layout_different_archive_must_not_match(self):
        first = self.build_pack()
        second = self.build_pack(expected_ap=11)
        before,after = inspect_evidence_pack(first),inspect_evidence_pack(second)
        self.assertNotEqual(before.archive_sha256,after.archive_sha256)
        comp = compare_pack(first,root=ROOT)
        self.assertEqual(assess_capabilities(after,comp)['status'],'RESEARCH_COMPARISON_BLOCKED')

    def test_other_build_and_adapter_rejected_even_with_same_archive(self):
        path=self.build_pack()
        original=inspect_evidence_pack(path)
        comp=compare_pack(path,root=ROOT)
        for variant in (replace(original,protocol_build='Dofus 9.9.9'),
                        replace(original,adapter_id='unrelated_adapter')):
            with self.subTest(variant=variant.adapter_id):
                out=assess_capabilities(variant,comp)
                self.assertEqual(out['status'],'RESEARCH_COMPARISON_BLOCKED')

    def test_legacy_or_unbound_comparison_must_be_incomplete(self):
        path=self.build_pack()
        report=inspect_evidence_pack(path)
        comp=compare_pack(path,root=ROOT)
        for name in ('comparison_binding',):
            with self.subTest(name=name):
                damaged={k:v for k,v in comp.items() if k!=name}
                out=assess_capabilities(report,damaged)
                self.assertEqual(out['status'],'RESEARCH_COMPARISON_BLOCKED')

    def test_staged_upgrade_review_rejects_mixed_bundle_comparison(self):
        # Exercise the actual setup-time orchestrator, not only its pure matrix.
        from anka_app.protocol_updates import audit_staged_updates
        old=self.build_pack()
        wrong_comparison=compare_pack(old,root=ROOT)
        other=self.build_pack(expected_ap=11)
        with TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'protocol_updates').mkdir()
            (root/'protocol_updates'/'new.zip').write_bytes(other.read_bytes())
            with patch('anka_app.protocol_evidence_compare.compare_pack',
                       return_value=wrong_comparison) as mocked:
                review=audit_staged_updates(root)
            report=review['packs'][0]['capability_assessment']
            self.assertEqual(mocked.call_args.kwargs['expected_archive_sha256'],
                             inspect_evidence_pack(other).archive_sha256)
            self.assertEqual(report['status'],'RESEARCH_COMPARISON_BLOCKED')
            self.assertEqual(next(c for c in report['capabilities'] if c['capability']=='actor_ap')['matched_cases'],0)
            self.assertFalse(review['adapter_activated'])
            self.assertFalse(review['live_semantic_certified'])

    def test_opaque_binding_has_no_raw_build_or_numeric_oracle_values(self):
        path=self.build_pack(expected_ap=11)
        report=inspect_evidence_pack(path)
        comp=compare_pack(path,root=ROOT)
        binding=comp['comparison_binding']
        self.assertRegex(binding,r'^[A-Z2-7]{52}$')
        self.assertNotIn('11',binding)
        self.assertNotIn(report.adapter_id, str(comp))
        self.assertNotIn(report.protocol_build, str(comp))
        self.assertFalse(comp['live_semantic_certified'])

    def test_mutating_success_count_or_case_count_is_rejected(self):
        path=self.build_pack()
        report=inspect_evidence_pack(path)
        comp=compare_pack(path,root=ROOT)
        for damaged in ({**comp, 'matched_cases':True},{**comp,'case_count':comp['case_count']+1}):
            with self.subTest(damaged=damaged['case_count']):
                self.assertEqual(assess_capabilities(report,damaged)['status'],'RESEARCH_COMPARISON_BLOCKED')

if __name__=='__main__':unittest.main()
