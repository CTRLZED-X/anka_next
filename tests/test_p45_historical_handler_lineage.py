"""Reference materials stay inert; exact old source hash and immutable inventory."""
from pathlib import Path
import shutil
import tempfile
import unittest
from anka_protocol.historical_lineage import audit_historical_lineage, HistoricalLineageRejected

ROOT=Path(__file__).resolve().parents[1]

class HistoricalLineageTests(unittest.TestCase):
    def test_reference_source_is_pinned_and_research_only(self):
        report=audit_historical_lineage(ROOT)
        self.assertEqual(report['source_files'],7)
        self.assertEqual(report['registered_handler_names'],39)
        self.assertEqual(report['handler_groups'],5)
        self.assertFalse(report['current_client_certified'])
        self.assertFalse(report['physical_input_permitted'])

    def _copy(self):
        temp=tempfile.TemporaryDirectory()
        target=Path(temp.name)/'reference/protocol/historical_3_7_10_10'
        target.parent.mkdir(parents=True)
        shutil.copytree(ROOT/'reference/protocol/historical_3_7_10_10',target)
        return temp,Path(temp.name),target

    def test_tampered_source_file_fails(self):
        ctx,root,target=self._copy()
        with ctx:
            p=target/'archived_source/fight.source.txt';p.write_bytes(p.read_bytes()+b'altered')
            with self.assertRaisesRegex(HistoricalLineageRejected,'P45_SOURCE_HASH_MISMATCH'):
                audit_historical_lineage(root)

    def test_tampered_manifest_fails(self):
        ctx,root,target=self._copy()
        with ctx:
            p=target/'handler_inventory.json';p.write_bytes(p.read_bytes()+b'\n')
            with self.assertRaisesRegex(HistoricalLineageRejected,'P45_INVENTORY_HASH_MISMATCH'):
                audit_historical_lineage(root)

    def test_missing_source_file_fails(self):
        ctx,root,target=self._copy()
        with ctx:
            (target/'archived_source/registry.source.txt').unlink()
            with self.assertRaisesRegex(HistoricalLineageRejected,'P45_SOURCE_UNAVAILABLE'):
                audit_historical_lineage(root)

    def test_symlink_source_directory_fails(self):
        ctx,root,target=self._copy()
        with ctx:
            base=target/'archived_source'
            moved=target/'outside'
            base.rename(moved)
            base.symlink_to(moved, target_is_directory=True)
            with self.assertRaisesRegex(HistoricalLineageRejected,'P45_SOURCE_PATH_UNSAFE'):
                audit_historical_lineage(root)

    def test_symlink_source_file_fails(self):
        ctx,root,target=self._copy()
        with ctx:
            p=target/'archived_source/fight.source.txt';p.unlink();p.symlink_to(target/'archived_source/actions.source.txt')
            with self.assertRaisesRegex(HistoricalLineageRejected,'P45_SOURCE_PATH_UNSAFE'):
                audit_historical_lineage(root)

if __name__=='__main__': unittest.main()
