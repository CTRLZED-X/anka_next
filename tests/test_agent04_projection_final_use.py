"""Chat 04 final-use projection evidence regressions."""
from __future__ import annotations

from dataclasses import replace
import unittest

from anka_client.context import build_client_context
from anka_client.discovery import generation_id
from anka_client.projection import project_cell, project_spell
from anka_contracts.bridge import BridgeMapReport, CellProjection
from anka_contracts.client import (
    AccountBinding, CalibrationProfileEvidence, LoadoutEvidence, WindowObservation
)


NOW = 90_000_000_000


def window() -> WindowObservation:
    return WindowObservation(
        101, 202, 303, 'Dofus.exe', 'Curseni - Dofus',
        1280, 649, 96, False, True, False, '3.7.10.10'
    )


def binding(w: WindowObservation) -> AccountBinding:
    return AccountBinding(
        'Curseni', 'IDENTITY_MATCHED', 'TEST_EVIDENCE',
        generation_id(w), w.hwnd, w.pid, 'CRA', 'LIVE_PROTOCOL', False
    )


def calibration(*, generation: int = 11, current: bool = True, dpi: int = 96) -> CalibrationProfileEvidence:
    return CalibrationProfileEvidence(
        'cal-test', 'a' * 64, 'b' * 64, generation, 1280, 649, dpi,
        ((1, 467, 583), (2, 494, 584)),
        (('PHASE_BUTTON', 893, 606),), (('LEFT', 23, 286),),
        'TEST_CURRENT' if current else 'TEST_REVOKED', current,
    )


def loadout(w: WindowObservation, *, generation: int = 17, status: str = 'PROVEN',
            at: int = NOW - 1, name: str = 'Curseni', breed: str = 'CRA') -> LoadoutEvidence:
    return LoadoutEvidence(
        'TEST_FIXTURE', name, breed, generation_id(w), generation, at,
        ((1, 13058), (2, 13059)), status,
    )


def bridge(*, generation: int = 9, live: bool = True,
           cells: tuple[CellProjection, ...] | None = None) -> BridgeMapReport:
    if cells is None:
        cells = (CellProjection(42, 500, 250, True, True, True),)
    return BridgeMapReport(
        'RESEARCH_PROJECTION_ONLY', 'TEST', 777, 8, generation,
        (1280, 649), cells, True, live, False,
    )


def proven_context():
    w = window()
    cal = calibration()
    lo = loadout(w)
    br = bridge()
    ctx = build_client_context(
        character_name='Curseni', binding=binding(w), window=w,
        calibration=cal, bridge=br, loadout=lo,
        observed_monotonic_ns=NOW, expected_map_id=777,
    )
    assert ctx.prerequisites_status == 'PROVEN'
    return w, cal, lo, br, ctx


class Agent04ProjectionFinalUseTests(unittest.TestCase):
    def test_spell_rejects_calibration_generation_swap_after_context_proof(self):
        _w, _cal, lo, _br, ctx = proven_context()
        result = project_spell(ctx, calibration(generation=12), lo, 13058, NOW)
        self.assertFalse(result.valid)
        self.assertIn('CALIBRATION_GENERATION_CHANGED', result.invalidators)

    def test_spell_rejects_revoked_calibration_even_with_same_generation(self):
        _w, _cal, lo, _br, ctx = proven_context()
        result = project_spell(ctx, calibration(current=False), lo, 13058, NOW)
        self.assertFalse(result.valid)
        self.assertIn('CALIBRATION_GENERATION_CHANGED', result.invalidators)

    def test_spell_rejects_conflicting_loadout_even_with_same_generation(self):
        w, cal, _lo, _br, ctx = proven_context()
        result = project_spell(ctx, cal, loadout(w, status='CONFLICTING'), 13058, NOW)
        self.assertFalse(result.valid)
        self.assertIn('LOADOUT_NOT_PROVEN', result.invalidators)

    def test_spell_rechecks_loadout_freshness_at_projection_time(self):
        _w, cal, lo, _br, ctx = proven_context()
        result = project_spell(ctx, cal, lo, 13058, NOW + 3_000_000_001)
        self.assertFalse(result.valid)
        self.assertIn('LOADOUT_STALE_OR_FUTURE', result.invalidators)

    def test_spell_rejects_identity_swap_with_reused_loadout_generation(self):
        w, cal, _lo, _br, ctx = proven_context()
        result = project_spell(ctx, cal, loadout(w, name='Other'), 13058, NOW)
        self.assertFalse(result.valid)
        self.assertIn('LOADOUT_CHARACTER_CHANGED', result.invalidators)

    def test_spell_rejects_bool_id(self):
        _w, cal, lo, _br, ctx = proven_context()
        result = project_spell(ctx, cal, lo, True, NOW)
        self.assertFalse(result.valid)
        self.assertIn('INVALID_SPELL_ID', result.invalidators)

    def test_cell_rejects_revoked_bridge_certification_with_same_generation(self):
        _w, _cal, _lo, br, ctx = proven_context()
        result = project_cell(ctx, replace(br, live_certified=False), 42, NOW)
        self.assertFalse(result.valid)
        self.assertIn('BRIDGE_PROJECTION_UNPROVEN', result.invalidators)

    def test_cell_rejects_out_of_bounds_projection_even_if_marked_verified(self):
        _w, _cal, _lo, br, ctx = proven_context()
        bad = replace(br, cells=(CellProjection(42, 1280, 250, True, True, True),))
        result = project_cell(ctx, bad, 42, NOW)
        self.assertFalse(result.valid)
        self.assertIn('CELL_COORDINATES_OUT_OF_BOUNDS', result.invalidators)

    def test_cell_rejects_bool_id(self):
        _w, _cal, _lo, br, ctx = proven_context()
        result = project_cell(ctx, br, True, NOW)
        self.assertFalse(result.valid)
        self.assertIn('INVALID_CELL_ID', result.invalidators)


if __name__ == '__main__':
    unittest.main()
