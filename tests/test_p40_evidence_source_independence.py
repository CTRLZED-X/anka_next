"""P40: role metadata cannot convert one packet into two independent accounts.

Untrusted ZIPs are never executed; evidence intake remains research-only.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from anka_protocol.evidence_intake import inspect_evidence_pack, IntakeRejected
from anka_protocol.capability_matrix import assess_capabilities
from anka_app.protocol_evidence_compare import compare_pack
from anka_app.protocol_updates import audit_staged_updates
from anka_app.cli import ROOT
from tests.test_p29_protocol_evidence_comparison import archive as fixture_archive


def repack(*, second_role='follower', second_selector=None,
           second_oracle_id=None, alias_capture=False, alias_oracle=False):
    with ZipFile(BytesIO(fixture_archive())) as src:
        files={name:src.read(name) for name in src.namelist()}
    manifest=json.loads(files['manifest.json'])
    row=dict(manifest['cases'][0])
    row.update(id='case2', account_role=second_role)
    row['selector']=dict(row['selector'])
    if second_selector is not None:
        row['selector'].update(second_selector)
    if second_oracle_id is not None:
        doc=json.loads(files[row['oracle']])
        observation=dict(doc['observations'][0]);observation['id']=second_oracle_id
        doc['observations'].append(observation)
        files[row['oracle']]=json.dumps(doc).encode()
        # When an existing oracle was amended, re-sign its original manifest
        # source entry; intake should never trust an outdated source digest.
        next(x for x in manifest['sources'] if x['path']==row['oracle'])['sha256']=sha256(files[row['oracle']]).hexdigest()
        row['oracle_id']=second_oracle_id
    if alias_capture:
        original=row['capture'];row['capture']='captures/alias.pcapng'
        files[row['capture']]=files[original]
        manifest['sources'].append({'path':row['capture'],'kind':'pcapng',
                                    'sha256':sha256(files[row['capture']]).hexdigest()})
    if alias_oracle:
        original=row['oracle'];row['oracle']='oracles/alias.json'
        files[row['oracle']]=files[original]
        manifest['sources'].append({'path':row['oracle'],'kind':'oracle',
                                    'sha256':sha256(files[row['oracle']]).hexdigest()})
    manifest['cases'].append(row)
    files['manifest.json']=json.dumps(manifest).encode()
    result=BytesIO()
    with ZipFile(result,'w') as dest:
        for filename,content in files.items():dest.writestr(filename,content)
    return result.getvalue()


class P40SourceIndependenceTests(unittest.TestCase):
    def inspect(self, content):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'pack.zip';path.write_bytes(content)
            return inspect_evidence_pack(path)

    def test_same_oracle_assertion_cannot_be_relabelled_follower(self):
        with self.assertRaisesRegex(IntakeRejected,'P28_ORACLE_OBSERVATION_REUSED'):
            self.inspect(repack())

    def test_duplicate_oracle_rejected_even_for_one_role(self):
        with self.assertRaisesRegex(IntakeRejected,'P28_ORACLE_OBSERVATION_REUSED'):
            self.inspect(repack(second_role='leader'))

    def test_oracle_filename_alias_cannot_bypass_deduplication(self):
        with self.assertRaisesRegex(IntakeRejected,'P28_ORACLE_OBSERVATION_REUSED'):
            self.inspect(repack(alias_oracle=True))

    def test_distinct_oracle_claim_still_cannot_reuse_cross_role_packet(self):
        with self.assertRaisesRegex(IntakeRejected,'P28_CROSS_ROLE_SOURCE_REUSE'):
            self.inspect(repack(second_oracle_id='independent_label'))

    def test_capture_filename_alias_cannot_bypass_source_provenance(self):
        with self.assertRaisesRegex(IntakeRejected,'P28_CROSS_ROLE_SOURCE_REUSE'):
            self.inspect(repack(second_oracle_id='independent_label',alias_capture=True))

    def test_distinct_message_selector_not_falsely_rejected(self):
        report=self.inspect(repack(second_oracle_id='independent_label',
                                   second_selector={'packet_number':3}))
        self.assertEqual(report.case_count,2)
        self.assertEqual(report.cases_with_witness,2)
        self.assertFalse(report.intake_complete)
        self.assertFalse(report.to_dict()['live_semantic_certified'])

    def test_same_message_same_role_different_independent_capabilities_not_rejected(self):
        # One message may legitimately supply more than one field for ONE
        # account; independence is about accounts and oracle assertions.
        with ZipFile(BytesIO(repack(second_role='leader',
                                    second_oracle_id='second_assertion'))) as z:
            files={name:z.read(name) for name in z.namelist()}
        manifest=json.loads(files['manifest.json'])
        manifest['cases'][1]['capability']='actor_mp'
        oracle=json.loads(files['oracles/check.json'])
        oracle['observations'][1]['capability']='actor_mp'
        oracle['observations'][1]['expected']={'actor_id':777,'mp':6}
        files['oracles/check.json']=json.dumps(oracle).encode()
        next(x for x in manifest['sources'] if x['path']=='oracles/check.json')['sha256']=sha256(files['oracles/check.json']).hexdigest()
        files['manifest.json']=json.dumps(manifest).encode()
        output=BytesIO()
        with ZipFile(output,'w') as z:
            for name,data in files.items():z.writestr(name,data)
        report=self.inspect(output.getvalue())
        self.assertEqual(report.case_count,2)
        self.assertEqual(set(report.covered_capabilities),{'actor_ap','actor_mp'})
        self.assertFalse(report.to_dict()['live_semantic_certified'])

    def test_distinct_message_same_role_can_support_different_cases(self):
        report=self.inspect(repack(second_role='leader',second_oracle_id='independent_label',
                                   second_selector={'packet_number':3}))
        self.assertEqual(report.case_count,2)
        self.assertFalse(report.to_dict()['adapter_activated'])

    def test_staged_update_audit_rejects_relabelled_evidence(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);staged=root/'protocol_updates';staged.mkdir()
            (staged/'new_protocol.zip').write_bytes(repack())
            with self.assertRaisesRegex(IntakeRejected,'P28_ORACLE_OBSERVATION_REUSED'):
                audit_staged_updates(root)

    def test_historical_independent_single_case_still_matches_research(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'original.zip';path.write_bytes(fixture_archive())
            intake=inspect_evidence_pack(path)
            comp=compare_pack(path,root=ROOT)
            matrix=assess_capabilities(intake,comp)
            cap=next(x for x in matrix['capabilities'] if x['capability']=='actor_ap')
            self.assertEqual(cap['roles_with_matching_oracles_claimed'],['leader'])
            self.assertEqual(cap['matched_cases'],1)
            self.assertIn('LEADER_FOLLOWER_COVERAGE_INCOMPLETE',cap['blockers'])
            self.assertFalse(matrix['live_semantic_certified'])
            self.assertEqual(matrix['canonical_commits'],0)

    def test_rejected_pack_never_promotes_authority(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'reused.zip';path.write_bytes(repack())
            with self.assertRaises(IntakeRejected):
                inspect_evidence_pack(path)
            # A rejected intake produces no comparable authoritative result.
            self.assertFalse(hasattr(inspect_evidence_pack,'activate_adapter'))

if __name__ == '__main__':
    unittest.main()
