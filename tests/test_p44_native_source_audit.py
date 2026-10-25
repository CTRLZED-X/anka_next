"""P44 source migration tamper checks; changes never install native binaries."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from anka_client.api import audit_reference_bridge_source
from anka_app.cli import ROOT


class NativeSourceAuditTests(unittest.TestCase):
    def test_unmodified_source_matches_historical_release(self):
        r = audit_reference_bridge_source(ROOT)
        self.assertEqual(r['status'],'HISTORICAL_SOURCE_INTEGRITY_PASS')
        self.assertEqual(r['file_count'],14)
        self.assertFalse(r['compiled'] or r['installed'] or r['input_certified'])

    def _copy(self, directory):
        root=Path(directory)
        shutil.copytree(ROOT/'native/unity_bridge',root/'native/unity_bridge')
        (root/'provenance').mkdir()
        shutil.copy2(ROOT/'provenance/P44_native_bridge_source.json',root/'provenance/P44_native_bridge_source.json')
        return root

    def test_mutated_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=self._copy(folder)
            with (root/'native/unity_bridge/Plugin.cs').open('ab') as f:f.write(b'//modified')
            with self.assertRaisesRegex(ValueError,'BRIDGE_SOURCE_HASH_MISMATCH'):
                audit_reference_bridge_source(root)

    def test_manifest_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=self._copy(folder); p=root/'provenance/P44_native_bridge_source.json'
            data=json.loads(p.read_text());data['files'][0]['path']='native/unity_bridge/../../secrets.txt'
            p.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'MISSING_OR_OUTSIDE_BRIDGE_SOURCE'):
                audit_reference_bridge_source(root)

    def test_legacy_provenance_false_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=self._copy(folder);p=root/'provenance/P44_native_bridge_source.json'
            data=json.loads(p.read_text());data['files'][0]['legacy_provenance_matches']=False
            p.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'LEGACY_BRIDGE_SOURCE_DRIFT'):
                audit_reference_bridge_source(root)

    def test_missing_native_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=self._copy(folder)
            (root/'native/unity_bridge/Plugin.cs').unlink()
            with self.assertRaisesRegex(ValueError,'MISSING_OR_OUTSIDE_BRIDGE_SOURCE'):
                audit_reference_bridge_source(root)

if __name__=='__main__':unittest.main()
