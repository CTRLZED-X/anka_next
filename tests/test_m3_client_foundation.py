from __future__ import annotations
import ast
from dataclasses import replace
from pathlib import Path
import unittest

from anka_client.calibration import load_calibration_profile
from anka_client.context import build_client_context, generation_invalidators, identity_from_binding
from anka_client.discovery import generation_id
from anka_client.projection import project_cell, project_spell
from anka_contracts.bridge import BridgeMapReport, CellProjection
from anka_contracts.client import (AccountBinding, CalibrationProfileEvidence, LoadoutEvidence,
                                   WindowObservation)

ROOT=Path(__file__).resolve().parents[1]
NOW=90_000_000_000


def window(*,hwnd=101,pid=202,created=303,width=1280,height=649,dpi=96,
           minimized=False,foreground=True,occluded=False):
    return WindowObservation(hwnd,pid,created,'Dofus.exe','Curseni - Dofus',width,height,dpi,minimized,foreground,occluded)


def binding(w=None,*,breed='CRA',state='IDENTITY_MATCHED'):
    w=w or window()
    return AccountBinding('Curseni',state,'TEST_EVIDENCE',generation_id(w),w.hwnd,w.pid,breed,'LIVE_PROTOCOL',False)


def calibration(*,width=1280,height=649,dpi=96,current=True,generation=11):
    return CalibrationProfileEvidence('cal-test','a'*64,'b'*64,generation,width,height,dpi,
        ((1,467,583),(2,494,584)),(('PHASE_BUTTON',893,606),),(('LEFT',23,286),),
        'TEST_CURRENT' if current else 'HISTORICAL_COORDINATES_NOT_LIVE_CERTIFIED',current)


def loadout(w=None,*,breed='CRA',generation=17,status='PROVEN',slots=((1,13058),(2,13059)),at=NOW-1):
    w=w or window()
    return LoadoutEvidence('TEST_FIXTURE','Curseni',breed,generation_id(w),generation,at,slots,status)


def bridge(*,map_id=777,map_gen=8,coord_gen=9,size=(1280,649),live=True,cells=None):
    if cells is None: cells=(CellProjection(42,500,250,True,True,True),)
    return BridgeMapReport('RESEARCH_PROJECTION_ONLY','TEST',map_id,map_gen,coord_gen,size,cells,True,live,False)


def proof(**changes):
    w=changes.pop('window',window())
    return build_client_context(character_name='Curseni', binding=changes.pop('binding',binding(w)), window=w,
        calibration=changes.pop('calibration',calibration()), bridge=changes.pop('bridge',bridge()),
        loadout=changes.pop('loadout',loadout(w)), observed_monotonic_ns=changes.pop('now',NOW),
        expected_map_id=changes.pop('expected_map_id',777), **changes)


class TestM3Calibration(unittest.TestCase):
    def test_historical_reference_is_hash_bound_and_not_current(self):
        p=load_calibration_profile(ROOT/'assets/calibration/shared_ui_1280x649.json',
            source_path=ROOT/'reference/calibration/shared_ui_calibration_1280x649.yaml')
        self.assertEqual((p.width,p.height,len(p.spell_slots)),(1280,649,22))
        self.assertFalse(p.current_client_certified)
        self.assertEqual(p.status,'HISTORICAL_COORDINATES_NOT_LIVE_CERTIFIED')

    def test_historical_profile_cannot_self_promote_to_current(self):
        with self.assertRaisesRegex(ValueError,'HISTORICAL_CALIBRATION_CANNOT_SELF_CERTIFY_CURRENT_CLIENT'):
            load_calibration_profile(ROOT/'assets/calibration/shared_ui_1280x649.json',current_client_certified=True)


class TestM3Context(unittest.TestCase):
    def test_coherent_synthetic_context_can_prove_prerequisites_but_never_input(self):
        p=proof()
        self.assertEqual((p.prerequisites_status,p.class_id),('PROVEN',9))
        self.assertEqual(p.invalidators,())
        self.assertFalse(p.physical_input_permitted)

    def test_archived_calibration_and_bridge_never_claim_current_context(self):
        p=proof(calibration=calibration(current=False),bridge=bridge(live=False))
        self.assertEqual(p.prerequisites_status,'INCOMPLETE')
        self.assertIn('CALIBRATION_NOT_CURRENT_CERTIFIED',p.invalidators)
        self.assertIn('BRIDGE_NOT_CURRENT_CERTIFIED',p.invalidators)

    def test_wrong_pid_hwnd_generation_blocks(self):
        old=window(); current=window(pid=999,created=999)
        p=proof(window=current,binding=binding(old),loadout=loadout(current))
        self.assertEqual(p.prerequisites_status,'BLOCKED')
        self.assertIn('WINDOW_GENERATION_MISMATCH',p.invalidators)

    def test_wrong_class_blocks(self):
        p=proof(binding=binding(breed='FECA'),loadout=loadout(breed='CRA'))
        self.assertEqual(p.prerequisites_status,'BLOCKED')
        self.assertIn('CLASS_NOT_PROVEN',p.invalidators)

    def test_size_dpi_map_each_fail_closed(self):
        cases=(
            (dict(window=window(width=1200),loadout=loadout(window(width=1200))),'CALIBRATION_WINDOW_SIZE_MISMATCH'),
            (dict(window=window(dpi=120),loadout=loadout(window(dpi=120))),'CALIBRATION_DPI_MISMATCH'),
            (dict(bridge=bridge(map_id=778)),'BRIDGE_MAP_MISMATCH'),
        )
        for kwargs,reason in cases:
            with self.subTest(reason=reason):
                p=proof(**kwargs)
                self.assertNotEqual(p.prerequisites_status,'PROVEN')
                self.assertIn(reason,p.invalidators)
                self.assertFalse(p.physical_input_permitted)

    def test_focus_occlusion_and_minimize_fail_closed(self):
        for w,reason in ((window(foreground=False),'WINDOW_NOT_FOREGROUND'),
                         (window(occluded=True),'WINDOW_OCCLUDED'),
                         (window(minimized=True),'WINDOW_MINIMIZED')):
            with self.subTest(reason=reason):
                p=proof(window=w,loadout=loadout(w))
                self.assertIn(reason,p.invalidators)
                self.assertFalse(p.physical_input_permitted)

    def test_loadout_mismatch_stale_and_conflict_fail_closed(self):
        for lo,reason in ((loadout(breed='ENUTROF'),'LOADOUT_CLASS_MISMATCH'),
                          (loadout(at=NOW-4_000_000_000),'LOADOUT_STALE_OR_FUTURE'),
                          (loadout(status='CONFLICTING'),'LOADOUT_NOT_PROVEN')):
            with self.subTest(reason=reason):
                p=proof(loadout=lo)
                self.assertIn(reason,p.invalidators)
                self.assertFalse(p.physical_input_permitted)

    def test_generation_vector_detects_every_relevant_drift(self):
        base=proof().vector
        variants=(
            (replace(base,window_generation_id='win-'+'1'*32),'WINDOW_GENERATION_CHANGED'),
            (replace(base,width=1279),'WINDOW_SIZE_CHANGED'),
            (replace(base,dpi=120),'WINDOW_DPI_CHANGED'),
            (replace(base,bridge_map_id=778),'BRIDGE_MAP_CHANGED'),
            (replace(base,bridge_map_generation=99),'BRIDGE_MAP_GENERATION_CHANGED'),
            (replace(base,bridge_coordinate_generation=99),'BRIDGE_COORDINATE_GENERATION_CHANGED'),
            (replace(base,calibration_generation=99),'CALIBRATION_GENERATION_CHANGED'),
            (replace(base,loadout_generation=99),'LOADOUT_GENERATION_CHANGED'),
            (replace(base,foreground=False),'FOCUS_NOT_PROVEN'),
            (replace(base,occluded=None),'VISIBILITY_NOT_PROVEN'),
        )
        for changed,reason in variants:
            with self.subTest(reason=reason): self.assertIn(reason,generation_invalidators(base,changed))

    def test_identity_conversion_maps_cra_class_without_title_authority(self):
        w=window(); ident=identity_from_binding(account_id='cra',binding=binding(w),window=w,bridge_generation=9)
        self.assertEqual((ident.class_id,ident.character_match_status,ident.class_proof_status),(9,'PROVEN','PROVEN'))


class TestM3Projection(unittest.TestCase):
    def test_spell_projection_requires_loadout_slot_proof(self):
        ctx=proof(); lo=loadout(); cal=calibration()
        ok=project_spell(ctx,cal,lo,13058,NOW)
        self.assertTrue(ok.valid); self.assertEqual((ok.pixel_x,ok.pixel_y),(467,583)); self.assertFalse(ok.input_certified)
        missing=project_spell(ctx,cal,lo,99999,NOW)
        self.assertFalse(missing.valid); self.assertIn('SPELL_SLOT_MISSING_OR_AMBIGUOUS',missing.invalidators)

    def test_duplicate_spell_assignment_is_ambiguous_even_when_slots_valid(self):
        lo=loadout(slots=((1,13058),(2,13058)))
        ctx=proof(loadout=lo)
        result=project_spell(ctx,calibration(),lo,13058,NOW)
        self.assertFalse(result.valid); self.assertIn('SPELL_SLOT_MISSING_OR_AMBIGUOUS',result.invalidators)

    def test_cell_projection_is_generation_scoped(self):
        b=bridge(); ctx=proof(bridge=b)
        ok=project_cell(ctx,b,42,NOW); self.assertTrue(ok.valid); self.assertFalse(ok.input_certified)
        drift=replace(b,coordinate_generation=10)
        blocked=project_cell(ctx,drift,42,NOW)
        self.assertFalse(blocked.valid); self.assertIn('BRIDGE_GENERATION_CHANGED',blocked.invalidators)

    def test_unprojectable_or_unknown_cell_blocks(self):
        b=bridge(cells=(CellProjection(42,-1,-1,False,True,False),));ctx=proof(bridge=b)
        r=project_cell(ctx,b,42,NOW)
        self.assertFalse(r.valid);self.assertIn('CELL_NOT_PROJECTABLE',r.invalidators)


class TestM3AuthorityBoundary(unittest.TestCase):
    def test_client_source_contains_no_physical_input_primitive(self):
        forbidden={'SendInput','mouse_event','keybd_event','SetForegroundWindow','SetCursorPos','click_physical_screen','send_key'}
        for path in (ROOT/'src/anka_client').glob('*.py'):
            tree=ast.parse(path.read_text())
            calls={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
            self.assertFalse(calls & forbidden,(path,calls & forbidden))

    def test_native_inventory_observes_foreground_but_not_occlusion_claim(self):
        text=(ROOT/'src/anka_client/win32_inventory.py').read_text()
        self.assertIn('GetForegroundWindow',text)
        self.assertNotIn('SetForegroundWindow',text)

if __name__=='__main__': unittest.main()
