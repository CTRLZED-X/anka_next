from __future__ import annotations
import json
import shutil
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from anka_protocol.historical_identity_lineage import audit_historical_identity_lineage, HistoricalIdentityLineageRejected

ROOT=Path(__file__).resolve().parents[1]

class P53IdentityLineageTests(unittest.TestCase):
    def test_project_reference_passes_and_preserves_registry_discrepancy(self):
        r=audit_historical_identity_lineage(ROOT)
        self.assertEqual(r['status'],'HISTORICAL_IDENTITY_SOURCE_VERIFIED_RESEARCH_ONLY')
        self.assertEqual((r['accepted_identity_wire'],r['reference_only_wire']),('jnj','jns'))
        self.assertTrue(r['registry_discrepancy_preserved'])
        self.assertFalse(r['current_client_certified'])
        self.assertEqual(r['canonical_commits'],0)
        self.assertFalse(r['physical_input_permitted'])

    def copy(self):
        t=TemporaryDirectory();dst=Path(t.name)
        src=ROOT/'reference/protocol/historical_3_7_10_10'
        target=dst/'reference/protocol/historical_3_7_10_10'
        target.parent.mkdir(parents=True);shutil.copytree(src,target)
        return t,dst,target

    def test_modified_source_fails_closed(self):
        t,root,d=self.copy();self.addCleanup(t.cleanup)
        p=d/'archived_source/world_identity.source.txt';p.write_text(p.read_text()+'\n# drift')
        with self.assertRaises(HistoricalIdentityLineageRejected):audit_historical_identity_lineage(root)

    def test_modified_manifest_fails_before_trusting_content(self):
        t,root,d=self.copy();self.addCleanup(t.cleanup)
        p=d/'identity_recovery_manifest.json';doc=json.loads(p.read_text());doc['accepted_identity_wire']='jns';p.write_text(json.dumps(doc))
        with self.assertRaises(HistoricalIdentityLineageRejected):audit_historical_identity_lineage(root)

    def test_symlink_source_is_rejected(self):
        t,root,d=self.copy();self.addCleanup(t.cleanup)
        p=d/'archived_source/world_identity.source.txt';target=d/'copy.txt';target.write_bytes(p.read_bytes());p.unlink()
        try:p.symlink_to(target)
        except OSError:self.skipTest('symlink unavailable')
        with self.assertRaises(HistoricalIdentityLineageRejected):audit_historical_identity_lineage(root)

if __name__=='__main__':unittest.main()
