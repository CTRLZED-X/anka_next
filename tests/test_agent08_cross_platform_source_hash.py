"""Independent Chat 08 regression for cross-platform source identity.

The release/source fingerprint must not depend on whether the verifier runs on
POSIX or Windows.  pathlib path ordering is flavor-dependent, so sorting Path
objects before hashing can change row order even when file bytes are identical.
"""
from __future__ import annotations

from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory
import unittest

from tools.verification_common import canonical_hash, sha256_file, tree_hash


class TestAgent08CrossPlatformSourceHash(unittest.TestCase):
    def test_tree_hash_is_independent_of_windows_vs_posix_path_ordering(self):
        with TemporaryDirectory() as td:
            base = Path(td) / "Static"
            base.mkdir()

            # These names have different ordering under POSIX case-sensitive
            # path comparison and Windows path-flavor comparison.
            first = base / "Companions.json"
            second = base / "CompanionSpells.json"
            first.write_text("companions\n", encoding="utf8")
            second.write_text("spells\n", encoding="utf8")

            observed_posix = tree_hash((base,))

            candidates = [first, second]
            windows_order = sorted(
                candidates,
                key=lambda path: PureWindowsPath(
                    path.relative_to(base).as_posix()
                ),
            )
            windows_rows = [
                (path.as_posix(), sha256_file(path), path.stat().st_size)
                for path in windows_order
            ]
            simulated_windows = canonical_hash(windows_rows)

            self.assertEqual(
                observed_posix,
                simulated_windows,
                "Source identity changes only because Path sorting uses the host "
                "path flavor. Sort canonical POSIX relative path strings instead.",
            )


if __name__ == "__main__":
    unittest.main()
