"""P32 adversarial role/capability qualification matrix, no live authority."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anka_protocol.evidence_intake import IntakeReport, REQUIRED_CAPABILITIES, evidence_case_binding
from anka_protocol.capability_matrix import assess_capabilities
from anka_app.protocol_updates import audit_staged_updates
from tests.test_p29_protocol_evidence_comparison import archive as historical_archive
from tests.test_p28_protocol_evidence_intake import packed as intake_archive


def intake(cases):
    caps = {x[0] for x in cases}
    return IntakeReport('Dofus 3.7.10.10','historical_research','a'*64,3,len(cases),
                        tuple(sorted(caps)),tuple(sorted(REQUIRED_CAPABILITIES-caps)),
                        sum(x[2] for x in cases),False,tuple(cases))


def comparison(cases, statuses=None, *, status=None):
    statuses = list(statuses or ['MATCHED_RESEARCH_ONLY']*len(cases))
    rows = [{'case_index':idx,'capability':cap,'status':statuses[idx],
             'mismatch_fields':['value'] if statuses[idx]=='FIELD_MISMATCH' else [],
             'case_binding':evidence_case_binding('a'*64,'Dofus 3.7.10.10','historical_research',idx,cases[idx])}
            for idx,(cap,_,_,_) in enumerate(cases)]
    success = all(s == 'MATCHED_RESEARCH_ONLY' for s in statuses)
    # Deliberately bind synthetic matrix fixtures to the synthetic intake
    # report so consumer-contract tests cannot pass with unbound comparisons.
    from anka_protocol.evidence_intake import evidence_binding_id
    return {'status':status or ('RESEARCH_COMPARISON_MATCHED_NOT_CERTIFIED' if success else 'RESEARCH_COMPARISON_BLOCKED'),
            'comparison_binding': evidence_binding_id('a'*64, 'Dofus 3.7.10.10', 'historical_research'),
            'case_results':rows,'case_count':len(rows),
            'matched_cases':sum(s=='MATCHED_RESEARCH_ONLY' for s in statuses),
            'mismatched_cases':sum(s=='FIELD_MISMATCH' for s in statuses),
            'finding_counts':{key:statuses.count(key) for key in set(statuses)}}


class CapabilityMatrixTests(unittest.TestCase):
    def one(self, cap='actor_ap', role='leader', witnessed=True, selector=True, status='MATCHED_RESEARCH_ONLY'):
        cases=[(cap,role,witnessed,selector)]
        return assess_capabilities(intake(cases), comparison(cases,[status]))

    def get(self, report, cap='actor_ap'):
        return next(x for x in report['capabilities'] if x['capability']==cap)

    def test_missing_required_capability_not_filled_in(self):
        r=self.one()
        self.assertIn('fight_start',r['required_blocked_capabilities'])
        self.assertEqual(self.get(r,'fight_start')['status'],'NOT_OBSERVED')

    def test_single_account_never_satisfies_both_roles(self):
        r=self.one()
        self.assertIn('LEADER_FOLLOWER_COVERAGE_INCOMPLETE',self.get(r)['blockers'])
        self.assertEqual(self.get(r)['roles_with_matching_oracles_claimed'],['leader'])

    def test_two_account_matched_capability_is_still_research(self):
        cases=[('actor_ap','leader',True,True),('actor_ap','follower',True,True)]
        r=assess_capabilities(intake(cases),comparison(cases))
        self.assertEqual(self.get(r)['status'],'RESEARCH_MATCHED_NOT_CERTIFIED')
        self.assertFalse(r['live_semantic_certified'])
        self.assertFalse(r['adapter_activated'])
        self.assertEqual(r['canonical_commits'],0)
        self.assertFalse(r['physical_input_sent'])
        self.assertEqual(r['status'],'RESEARCH_COVERAGE_INCOMPLETE')

    def test_all_required_both_roles_does_not_certify_live(self):
        cases=[(cap,role,True,True) for cap in sorted(REQUIRED_CAPABILITIES)
                                     for role in ('leader','follower')]
        r=assess_capabilities(intake(cases),comparison(cases))
        self.assertEqual(r['status'],'RESEARCH_COVERAGE_MATCHED_NOT_CERTIFIED')
        self.assertEqual(r['required_blocked_capabilities'],[])
        self.assertFalse(r['current_build_certified'])
        self.assertTrue(r['remaining_live_gates'])
        self.assertTrue(all(self.get(r,cap)['status']=='RESEARCH_MATCHED_NOT_CERTIFIED'
                            for cap in REQUIRED_CAPABILITIES))

    def test_witness_file_missing_even_when_matching(self):
        r=self.one(witnessed=False)
        self.assertIn('WITNESS_FILE_MISSING',self.get(r)['blockers'])

    def test_selector_missing_even_when_comparator_says_match(self):
        r=self.one(selector=False)
        self.assertIn('EXACT_SOURCE_SELECTOR_MISSING',self.get(r)['blockers'])

    def test_mismatch_blocks_capability_and_global_status(self):
        r=self.one(status='FIELD_MISMATCH')
        self.assertEqual(self.get(r)['status'],'FIELD_MISMATCH')
        self.assertEqual(r['status'],'RESEARCH_COMPARISON_BLOCKED')

    def test_unresolved_case_is_not_counted_matched(self):
        r=self.one(status='SOURCE_MESSAGE_NOT_FOUND')
        self.assertEqual(self.get(r)['unresolved_cases'],1)
        self.assertIn('CASE_COMPARISON_UNRESOLVED',self.get(r)['blockers'])

    def test_absent_comparison_never_claims_success(self):
        r=assess_capabilities(intake([('actor_ap','leader',True,True)]),
             {'status':'ADAPTER_UNAVAILABLE_FOR_EXACT_BUILD','case_results':[], 'matched_cases':0,'mismatched_cases':0})
        self.assertEqual(r['status'],'RESEARCH_COMPARISON_BLOCKED')
        self.assertIn('COMPARISON_NOT_COMPLETE_OR_INCONSISTENT',self.get(r)['blockers'])
        self.assertEqual(r['comparison_status'],'ADAPTER_UNAVAILABLE_FOR_EXACT_BUILD')

    def test_forged_case_status_with_missing_record_rejected(self):
        cases=[('actor_ap','leader',True,True),('actor_ap','follower',True,True)]
        bad=comparison(cases)
        bad['case_results'].pop()
        r=assess_capabilities(intake(cases),bad)
        self.assertEqual(r['status'],'RESEARCH_COMPARISON_BLOCKED')
        self.assertEqual(self.get(r)['matched_cases'],0)

    def test_forged_success_count_rejected(self):
        cases=[('actor_ap','leader',True,True)]
        bad=comparison(cases);bad['matched_cases']=2
        self.assertEqual(assess_capabilities(intake(cases),bad)['status'],'RESEARCH_COMPARISON_BLOCKED')

    def test_forged_mismatch_count_rejected(self):
        cases=[('actor_ap','leader',True,True)]
        bad=comparison(cases);bad['mismatched_cases']=1
        self.assertEqual(assess_capabilities(intake(cases),bad)['status'],'RESEARCH_COMPARISON_BLOCKED')

    def test_forged_wrong_capability_rejected(self):
        cases=[('actor_ap','leader',True,True)]
        bad=comparison(cases);bad['case_results'][0]['capability']='actor_hp'
        self.assertEqual(assess_capabilities(intake(cases),bad)['status'],'RESEARCH_COMPARISON_BLOCKED')

    def test_forged_wrong_index_rejected(self):
        cases=[('actor_ap','leader',True,True)]
        bad=comparison(cases);bad['case_results'][0]['case_index']=99
        self.assertEqual(assess_capabilities(intake(cases),bad)['status'],'RESEARCH_COMPARISON_BLOCKED')

    def test_forged_bool_index_rejected(self):
        cases=[('actor_ap','leader',True,True)]
        bad=comparison(cases);bad['case_results'][0]['case_index']=True
        self.assertEqual(assess_capabilities(intake(cases),bad)['status'],'RESEARCH_COMPARISON_BLOCKED')

    def test_forged_duplicate_index_rejected(self):
        cases=[('actor_ap','leader',True,True),('actor_ap','follower',True,True)]
        bad=comparison(cases);bad['case_results'][1]['case_index']=0
        self.assertEqual(assess_capabilities(intake(cases),bad)['status'],'RESEARCH_COMPARISON_BLOCKED')

    def test_forged_fully_matched_global_on_mismatch_rejected(self):
        cases=[('actor_ap','leader',True,True)]
        bad=comparison(cases,['FIELD_MISMATCH'],status='RESEARCH_COMPARISON_MATCHED_NOT_CERTIFIED')
        self.assertEqual(assess_capabilities(intake(cases),bad)['status'],'RESEARCH_COMPARISON_BLOCKED')

    def test_invalid_intake_case_metadata_fails_closed(self):
        src=intake([('actor_ap','leader',True,True)])
        from dataclasses import replace
        bad=replace(src,case_evidence=(('actor_ap','leader',1,True),))
        self.assertEqual(assess_capabilities(bad,comparison(src.case_evidence))['status'],'RESEARCH_COMPARISON_BLOCKED')

    def test_no_value_name_or_packet_content_in_report(self):
        r=self.one()
        s=str(r)
        for secret in ('captures/','oracle_id','actor_id','player_name','flow_digest','target_cell'):
            self.assertNotIn(secret,s)

    def test_optional_capability_single_role_can_be_matched(self):
        r=self.one(cap='ready')
        self.assertEqual(self.get(r,'ready')['status'],'RESEARCH_MATCHED_NOT_CERTIFIED')
        self.assertFalse(self.get(r,'ready')['required'])

    def test_real_historical_pack_matrix_does_not_certify(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'sample.zip';path.write_bytes(historical_archive())
            from anka_protocol.evidence_intake import inspect_evidence_pack
            from anka_app.protocol_evidence_compare import compare_pack
            from anka_app.cli import ROOT
            r=assess_capabilities(inspect_evidence_pack(path),compare_pack(path,root=ROOT))
            self.assertEqual(self.get(r)['matched_cases'],1)
            self.assertEqual(self.get(r)['status'],'INCOMPLETE_RESEARCH_EVIDENCE')
            self.assertFalse(r['live_semantic_certified'])

    def test_real_mismatched_pack_reports_field_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'sample.zip';path.write_bytes(historical_archive(expected_ap=11))
            from anka_protocol.evidence_intake import inspect_evidence_pack
            from anka_app.protocol_evidence_compare import compare_pack
            from anka_app.cli import ROOT
            r=assess_capabilities(inspect_evidence_pack(path),compare_pack(path,root=ROOT))
            self.assertEqual(self.get(r)['status'],'FIELD_MISMATCH')

    def test_setup_report_includes_research_matrix(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'protocol_updates').mkdir()
            (root/'protocol_updates'/'evidence.zip').write_bytes(historical_archive())
            from anka_app.cli import ROOT
            # Real comparison needs historical reference assets in the project.
            with patch('anka_app.protocol_evidence_compare.compare_pack',return_value={
                'status':'ADAPTER_UNAVAILABLE_FOR_EXACT_BUILD','case_results':[],
                'matched_cases':0,'mismatched_cases':0}):
                result=audit_staged_updates(root)
            report=result['packs'][0]['capability_assessment']
            self.assertEqual(report['status'],'RESEARCH_COMPARISON_BLOCKED')
            self.assertFalse(report['adapter_activated'])
            self.assertEqual(report['required_blocked_capabilities'],sorted(REQUIRED_CAPABILITIES))

    def test_pack_hash_cannot_change_between_intake_and_comparison(self):
        from anka_app.protocol_evidence_compare import compare_pack
        from anka_app.cli import ROOT
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'sample.zip';path.write_bytes(historical_archive())
            result=compare_pack(path,root=ROOT,expected_archive_sha256='f'*64)
            self.assertEqual(result['status'],'PACK_CHANGED_SINCE_INTAKE')
            self.assertEqual(result['case_count'],0)
            self.assertFalse(result['live_semantic_certified'])

    def test_setup_links_intake_and_comparator_using_exact_archive_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'protocol_updates').mkdir()
            (root/'protocol_updates'/'sample.zip').write_bytes(historical_archive())
            from anka_protocol.evidence_intake import inspect_evidence_pack
            digest=inspect_evidence_pack(root/'protocol_updates'/'sample.zip').archive_sha256
            with patch('anka_app.protocol_evidence_compare.compare_pack',return_value={
                'status':'ADAPTER_UNAVAILABLE_FOR_EXACT_BUILD','case_results':[],
                'matched_cases':0,'mismatched_cases':0}) as mock:
                audit_staged_updates(root)
            self.assertEqual(mock.call_args.kwargs['expected_archive_sha256'],digest)

    def test_intake_does_not_expose_case_identifiers(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'e.zip';path.write_bytes(intake_archive())
            from anka_protocol.evidence_intake import inspect_evidence_pack
            report=inspect_evidence_pack(path)
            self.assertEqual(report.case_evidence,(('actor_hp','leader',True,False),))
            self.assertNotIn('case0',str(report.to_dict()))
            self.assertNotIn('captures/',str(report.to_dict()))

if __name__=='__main__':unittest.main()
