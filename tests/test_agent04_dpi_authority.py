"""Chat 04 current-calibration DPI authority regressions."""
from __future__ import annotations

from dataclasses import fields, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from anka_client.calibration import load_calibration_profile
from anka_client.context import build_client_context
from anka_client.discovery import generation_id
from anka_client.projection import project_cell, project_spell
from anka_contracts.bridge import BridgeMapReport, CellProjection
from anka_contracts.client import (
    AccountBinding,
    CalibrationProfileEvidence,
    ClientContextProof,
    ClientGenerationVector,
    LoadoutEvidence,
    WindowObservation,
)


NOW = 91_000_000_000


def window(*, dpi=96) -> WindowObservation:
    return WindowObservation(
        101, 202, 303, 'Dofus.exe', 'Curseni - Dofus',
        1280, 649, dpi, False, True, False, '3.7.10.10'
    )


def binding(w: WindowObservation) -> AccountBinding:
    return AccountBinding(
        'Curseni', 'IDENTITY_MATCHED', 'TEST_EVIDENCE',
        generation_id(w), w.hwnd, w.pid, 'CRA', 'LIVE_PROTOCOL', False,
    )


def calibration(*, dpi=96, generation: int = 11,
                current: bool = True) -> CalibrationProfileEvidence:
    return CalibrationProfileEvidence(
        'cal-dpi-test', 'a' * 64, 'b' * 64, generation,
        1280, 649, dpi,
        ((1, 467, 583),),
        (('PHASE_BUTTON', 893, 606),),
        (('LEFT', 23, 286),),
        'TEST_CURRENT' if current else 'TEST_HISTORICAL',
        current,
    )


def loadout(w: WindowObservation) -> LoadoutEvidence:
    return LoadoutEvidence(
        'TEST_FIXTURE', 'Curseni', 'CRA', generation_id(w),
        17, NOW - 1, ((1, 13058),), 'PROVEN',
    )


def bridge() -> BridgeMapReport:
    return BridgeMapReport(
        'RESEARCH_PROJECTION_ONLY', 'TEST',
        777, 8, 9, (1280, 649),
        (CellProjection(42, 500, 250, True, True, True),),
        True, True, False,
    )


def forge_dataclass(instance, **changes):
    """Simulate a deserializer that bypasses dataclass __post_init__ validation."""
    forged = object.__new__(type(instance))
    for item in fields(instance):
        object.__setattr__(
            forged, item.name,
            changes.get(item.name, getattr(instance, item.name)),
        )
    return forged


def context_for(cal: CalibrationProfileEvidence, *, window_dpi=96) -> ClientContextProof:
    w = window(dpi=window_dpi)
    return build_client_context(
        character_name='Curseni',
        binding=binding(w),
        window=w,
        calibration=cal,
        bridge=bridge(),
        loadout=loadout(w),
        observed_monotonic_ns=NOW,
        expected_map_id=777,
    )


class Agent04DpiAuthorityTests(unittest.TestCase):
    def _profile_files(self, root: Path):
        source = root / 'source.yaml'
        source.write_text('current calibration source', encoding='utf8')
        payload = {
            'schema_version': 1,
            'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'client_size': {'width': 1280, 'height': 649},
            'spell_slots': {'1': {'x': 467, 'y': 583, 'verified': True}},
            'controls': {'PHASE_BUTTON': {'x': 893, 'y': 606, 'verified': True}},
            'directions': {'LEFT': {'x': 23, 'y': 286, 'verified': True}},
            'status': 'CURRENT_CALIBRATION_EVIDENCE',
        }
        profile = root / 'calibration.json'
        profile.write_text(json.dumps(payload), encoding='utf8')
        digest = hashlib.sha256(profile.read_bytes()).hexdigest()
        return source, profile, digest

    def test_current_certified_loader_rejects_missing_or_invalid_dpi(self):
        bad_values = (None, True, 0, -1, 96.0, '96')
        with tempfile.TemporaryDirectory() as directory:
            source, profile, digest = self._profile_files(Path(directory))
            for value in bad_values:
                with self.subTest(expected_dpi=value):
                    with self.assertRaisesRegex(
                            ValueError, 'CURRENT_CALIBRATION_DPI_REQUIRED'):
                        load_calibration_profile(
                            profile,
                            source_path=source,
                            current_client_certified=True,
                            expected_dpi=value,
                            accepted_profile_sha256=digest,
                        )

    def test_matching_positive_dpi_can_prove_context(self):
        ctx = context_for(calibration(dpi=96), window_dpi=96)
        self.assertEqual(ctx.prerequisites_status, 'PROVEN')
        self.assertEqual(ctx.invalidators, ())

    def test_mismatched_positive_dpi_blocks_context(self):
        ctx = context_for(calibration(dpi=120), window_dpi=96)
        self.assertEqual(ctx.prerequisites_status, 'BLOCKED')
        self.assertIn('CALIBRATION_DPI_MISMATCH', ctx.invalidators)

    def test_historical_loader_allows_none_dpi(self):
        with tempfile.TemporaryDirectory() as directory:
            source, profile, _digest = self._profile_files(Path(directory))
            loaded = load_calibration_profile(
                profile,
                source_path=source,
                current_client_certified=False,
                expected_dpi=None,
            )
            self.assertIsNone(loaded.expected_dpi)
            self.assertFalse(loaded.current_client_certified)

    def test_manual_current_certified_dto_missing_dpi_cannot_prove_context(self):
        ctx = context_for(calibration(dpi=None), window_dpi=96)
        self.assertEqual(ctx.prerequisites_status, 'BLOCKED')
        self.assertIn('CALIBRATION_DPI_UNPROVEN', ctx.invalidators)

    def test_forged_current_certified_invalid_dpi_fails_context_and_spell(self):
        good = calibration(dpi=96)
        good_ctx = context_for(good, window_dpi=96)
        self.assertEqual(good_ctx.prerequisites_status, 'PROVEN')

        for bad_dpi in (True, 0, -1, 96.0, '96'):
            with self.subTest(expected_dpi=bad_dpi):
                malformed = forge_dataclass(good, expected_dpi=bad_dpi)
                bad_ctx = context_for(malformed, window_dpi=96)
                self.assertEqual(bad_ctx.prerequisites_status, 'BLOCKED')
                self.assertIn('CALIBRATION_DPI_UNPROVEN', bad_ctx.invalidators)

                result = project_spell(
                    good_ctx, malformed, loadout(window(dpi=96)), 13058, NOW
                )
                self.assertFalse(result.valid)
                self.assertIn('CALIBRATION_DPI_UNPROVEN', result.invalidators)

    def test_manual_current_certified_dto_missing_dpi_fails_spell_final_use(self):
        good = calibration(dpi=96)
        ctx = context_for(good, window_dpi=96)
        self.assertEqual(ctx.prerequisites_status, 'PROVEN')
        malformed = replace(good, expected_dpi=None)
        result = project_spell(
            ctx, malformed, loadout(window(dpi=96)), 13058, NOW
        )
        self.assertFalse(result.valid)
        self.assertIn('CALIBRATION_DPI_UNPROVEN', result.invalidators)

    def test_manual_proven_context_missing_dpi_fails_cell_final_use(self):
        good = context_for(calibration(dpi=96), window_dpi=96)
        forged_vector = replace(good.vector, dpi=None)
        forged = ClientContextProof(
            good.character_name, good.breed, good.class_id,
            forged_vector, 'PROVEN', (), False,
        )
        result = project_cell(forged, bridge(), 42, NOW)
        self.assertFalse(result.valid)
        self.assertIn('CALIBRATION_DPI_UNPROVEN', result.invalidators)

    def test_forged_proven_context_invalid_dpi_fails_cell_final_use(self):
        good = context_for(calibration(dpi=96), window_dpi=96)
        for bad_dpi in (True, 0, -1, 96.0, '96'):
            with self.subTest(vector_dpi=bad_dpi):
                forged_vector = forge_dataclass(good.vector, dpi=bad_dpi)
                forged = ClientContextProof(
                    good.character_name, good.breed, good.class_id,
                    forged_vector, 'PROVEN', (), False,
                )
                result = project_cell(forged, bridge(), 42, NOW)
                self.assertFalse(result.valid)
                self.assertIn('CALIBRATION_DPI_UNPROVEN', result.invalidators)

    def test_dpi_changes_calibration_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            source, profile, digest = self._profile_files(Path(directory))
            dpi96 = load_calibration_profile(
                profile,
                source_path=source,
                current_client_certified=True,
                expected_dpi=96,
                accepted_profile_sha256=digest,
            )
            dpi120 = load_calibration_profile(
                profile,
                source_path=source,
                current_client_certified=True,
                expected_dpi=120,
                accepted_profile_sha256=digest,
            )
            self.assertNotEqual(dpi96.generation, dpi120.generation)

    def test_positive_dpi_preserves_source_and_acceptance_hash_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            source, profile, digest = self._profile_files(Path(directory))
            loaded = load_calibration_profile(
                profile,
                source_path=source,
                current_client_certified=True,
                expected_dpi=96,
                accepted_profile_sha256=digest,
            )
            self.assertEqual(loaded.profile_sha256, digest)

            with self.assertRaisesRegex(
                    ValueError, 'CURRENT_CALIBRATION_ACCEPTANCE_HASH_MISMATCH'):
                load_calibration_profile(
                    profile,
                    source_path=source,
                    current_client_certified=True,
                    expected_dpi=96,
                    accepted_profile_sha256='f' * 64,
                )

            source.write_text('tampered', encoding='utf8')
            with self.assertRaisesRegex(
                    ValueError, 'CALIBRATION_SOURCE_HASH_MISMATCH'):
                load_calibration_profile(
                    profile,
                    source_path=source,
                    current_client_certified=True,
                    expected_dpi=96,
                    accepted_profile_sha256=digest,
                )


if __name__ == '__main__':
    unittest.main()
