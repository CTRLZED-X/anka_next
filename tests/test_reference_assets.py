import json
import tempfile
import unittest
from pathlib import Path
from anka_client.reference_assets import audit_calibration
from anka_app.cli import ROOT

class TestReferenceAssets(unittest.TestCase):
    def setUp(self):
        self.profile=ROOT/'assets/calibration/shared_ui_1280x649.json'
        self.source=ROOT/'reference/calibration/shared_ui_calibration_1280x649.yaml'
    def test_coordinates_reused_without_claim_of_live_certification(self):
        summary=audit_calibration(self.profile,self.source)
        self.assertEqual(summary['spell_slots'],22)
        self.assertEqual(summary['controls'],['JOIN_FIGHT','PHASE_BUTTON'])
        self.assertFalse(summary['live_certified'])
    def test_wrong_calibration_size_fails(self):
        data=json.loads(self.profile.read_text())
        data['spell_slots']['22']['x']=9999
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'bad.json';p.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'POINT_OUT_OF_BOUNDS'):audit_calibration(p,self.source)
    def test_missing_phase_control_fails(self):
        data=json.loads(self.profile.read_text())
        data['controls'].pop('PHASE_BUTTON')
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'bad.json';p.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'MISSING_PHASE_OR_JOIN_BUTTON'):audit_calibration(p,self.source)
    def test_legacy_source_tampered_detected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'tampered.yaml';p.write_text(self.source.read_text()+'\n# changed\n')
            with self.assertRaisesRegex(ValueError,'SOURCE_CALIBRATION_HASH_MISMATCH'):audit_calibration(self.profile,p)
