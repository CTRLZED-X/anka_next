"""M0: immutable reference/evidence baseline and provenance guard tests."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("anka_verify_m0", ROOT / "tools" / "verify_m0.py")
assert SPEC and SPEC.loader
verify_m0 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_m0)


class M0BaselineTests(unittest.TestCase):
    def test_q0_gate_passes_on_exact_tree(self):
        result = verify_m0.verify(type("Args", (), {})())
        self.assertEqual(result["status"], "PASS", result["checks"])
        self.assertEqual(result["summary"]["fail"], 0)
        self.assertEqual(result["summary"]["physical_input_count"], 0)
        self.assertFalse(result["summary"]["live_client_contact"])

    def test_exact_reference_archive_hashes_are_frozen(self):
        baseline = json.loads((ROOT / "reference" / "m0" / "baseline_sources.json").read_text())
        self.assertEqual(
            baseline["reference_archives"]["legacy_r5_198"]["sha256"],
            "f1a50a3555cbe89f27d58ef8411cfcb002ec3cd1cd5aefe4546b4285f47f62d6",
        )
        self.assertEqual(
            baseline["reference_archives"]["starting_anka_next_p66"]["sha256"],
            "9c0edf863de39be9479bbd25e39c22d089af088268f9cf0afcc87e37f7765297",
        )

    def test_manifest_comparison_detects_one_byte_fixture_change(self):
        manifest = json.loads((ROOT / "reference" / "m0" / "master_specification_file_manifest.json").read_text())
        expected = {r["path"]: (r["sha256"], r["bytes"]) for r in manifest["files"]}
        source = ROOT / "reference" / "baselines" / "archives" / "ANKA_NEXT_DEFINITIVE_MASTER_SPECIFICATION.zip"
        actual = verify_m0.zip_file_map(source)
        self.assertEqual(actual, expected)
        # An independent synthetic mutation must no longer equal the frozen oracle.
        with tempfile.TemporaryDirectory() as td:
            mutated = Path(td) / "mutated.zip"
            with zipfile.ZipFile(source) as zin, zipfile.ZipFile(mutated, "w") as zout:
                changed = False
                for info in zin.infolist():
                    data = zin.read(info.filename)
                    if not info.is_dir() and info.filename.endswith("README.md") and not changed:
                        data += b"\nMUTATION"
                        changed = True
                    zout.writestr(info, data)
            self.assertTrue(changed)
            self.assertNotEqual(verify_m0.zip_file_map(mutated), expected)

    def test_missing_evidence_is_not_silently_promoted(self):
        catalog = json.loads((ROOT / "reference" / "m0" / "evidence_catalog.json").read_text())
        missing = [x for x in catalog["evidence"] if x["classification"] == "MISSING"]
        self.assertGreaterEqual(len(missing), 5)
        for row in missing:
            self.assertNotIn("path", row)
            self.assertTrue(row["limitation"])

    def test_reuse_manifest_preserves_exact_kernel_and_data_bytes(self):
        manifest = json.loads((ROOT / "provenance" / "REUSE_MANIFEST.json").read_text())
        unchanged = [r for r in manifest["rows"] if r["reuse_mode"] == "UNCHANGED_REUSE"]
        self.assertGreaterEqual(len(unchanged), 160)
        for row in unchanged:
            self.assertEqual(row["legacy_file_sha256"], row["target_sha256"])
            self.assertFalse(row["semantic_change"])

    def test_historical_symptoms_do_not_claim_one_root_cause(self):
        catalog = json.loads((ROOT / "reference" / "m0" / "regression_catalog.json").read_text())
        symptoms = [r for r in catalog["regressions"] if r["regression_id"].startswith("SYM-")]
        self.assertGreaterEqual(len(symptoms), 8)
        for row in symptoms:
            self.assertEqual(row["legacy_test_paths"], [])
            self.assertIn("first divergent boundary", row["permanent_invariant"])

    def test_live_pending_boundaries_are_all_fail_closed(self):
        ledger = json.loads((ROOT / "reference" / "m0" / "live_pending_boundaries.json").read_text())
        self.assertGreaterEqual(len(ledger["items"]), 9)
        self.assertTrue(all(x["status"] == "BLOCKED_MISSING_EVIDENCE" for x in ledger["items"]))
        self.assertTrue(all(x["required_evidence"] for x in ledger["items"]))

    def test_no_legacy_runtime_package_was_reintroduced(self):
        self.assertFalse((ROOT / "src" / "anka_platform").exists())
        root_bats = sorted(p.name for p in ROOT.glob("*.bat"))
        self.assertEqual(root_bats, ["setup.bat", "start.bat"])


if __name__ == "__main__":
    unittest.main()
