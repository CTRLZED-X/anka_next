"""P41: one selected wire message is one independent case per capability.

Distinct independent annotations can corroborate one source; they cannot
turn that single source into multiple packet samples or inflated coverage.
"""
from __future__ import annotations
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from anka_protocol.evidence_intake import IntakeRejected, inspect_evidence_pack
from anka_app.protocol_evidence_compare import compare_pack
from anka_app.cli import ROOT
from tests.test_p40_evidence_source_independence import repack


class PacketClaimUniquenessTests(unittest.TestCase):
    def intake(self, content):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'new.zip'
            path.write_bytes(content)
            return inspect_evidence_pack(path)

    def test_same_role_same_message_same_capability_different_oracle_is_rejected(self):
        with self.assertRaisesRegex(IntakeRejected, 'P28_DUPLICATE_SOURCE_CAPABILITY_CLAIM'):
            self.intake(repack(second_role='leader', second_oracle_id='second_oracle'))

    def test_renamed_capture_does_not_duplicate_packet_claim(self):
        with self.assertRaisesRegex(IntakeRejected, 'P28_DUPLICATE_SOURCE_CAPABILITY_CLAIM'):
            self.intake(repack(second_role='leader', second_oracle_id='second_oracle', alias_capture=True))

    def test_second_message_same_capability_is_valid_distinct_sample(self):
        report = self.intake(repack(second_role='leader', second_oracle_id='second_oracle',
                                    second_selector={'packet_number': 3}))
        self.assertEqual(report.case_count, 2)
        self.assertEqual(report.covered_capabilities, ('actor_ap',))
        self.assertFalse(report.to_dict()['live_semantic_certified'])

    def test_same_message_two_distinct_capabilities_remains_permitted(self):
        # Counterexample required to avoid accidentally rejecting a protobuf
        # frame containing both actor AP and MP updates.
        blob = repack(second_role='leader', second_oracle_id='second_oracle')
        with ZipFile(BytesIO(blob)) as inp:
            members = {x: inp.read(x) for x in inp.namelist()}
        manifest = json.loads(members['manifest.json'])
        oracle_name = manifest['cases'][1]['oracle']
        doc = json.loads(members[oracle_name]);doc['observations'][1]['capability'] = 'actor_mp'
        doc['observations'][1]['expected'] = {'actor_id': 777, 'mp': 6}
        members[oracle_name] = json.dumps(doc).encode()
        manifest['cases'][1]['capability'] = 'actor_mp'
        next(x for x in manifest['sources'] if x['path']==oracle_name)['sha256']=sha256(members[oracle_name]).hexdigest()
        members['manifest.json'] = json.dumps(manifest).encode()
        buff=BytesIO()
        with ZipFile(buff, 'w') as output:
            for name, value in members.items(): output.writestr(name,value)
        report=self.intake(buff.getvalue())
        self.assertEqual(report.case_count, 2)
        self.assertEqual(set(report.covered_capabilities), {'actor_ap','actor_mp'})

    def test_p40_cross_role_same_packet_is_still_rejected_at_stronger_boundary(self):
        with self.assertRaisesRegex(IntakeRejected,'P28_CROSS_ROLE_SOURCE_REUSE'):
            self.intake(repack(second_role='follower',second_oracle_id='second_oracle'))

    def test_research_comparator_cannot_count_invalid_pack_twice(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'reused.zip'
            path.write_bytes(repack(second_role='leader',second_oracle_id='second_oracle'))
            with self.assertRaisesRegex(IntakeRejected,'P28_DUPLICATE_SOURCE_CAPABILITY_CLAIM'):
                compare_pack(path,root=ROOT)

if __name__=='__main__':unittest.main()
