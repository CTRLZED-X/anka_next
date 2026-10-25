import unittest
from anka_client.geometry import geometry_diagnosis
from anka_contracts.client import WindowObservation

class TestClientGeometry(unittest.TestCase):
    def _window(self,w=1280,h=649,dpi=96,minimized=False):
        return WindowObservation(2,3,44,'Dofus.exe','Dofus - Curseni',w,h,dpi,minimized)
    def test_exact_historical_size_still_not_live_certified(self):
        r=geometry_diagnosis(self._window())
        self.assertTrue(r['observationally_matching_size'])
        self.assertFalse(r['live_calibration_certified'])
        self.assertIn('CLIENT_COORDINATE_SPACE_UNCERTIFIED',r['issues'])
    def test_resized_window_explains_calibration_gap(self):
        r=geometry_diagnosis(self._window(1600,900))
        self.assertIn('WINDOW_SIZE_DIFFERS_FROM_HISTORICAL_CALIBRATION',r['issues'])
    def test_unknown_dpi_not_guessed(self):
        r=geometry_diagnosis(self._window(dpi=None))
        self.assertIn('WINDOW_DPI_UNKNOWN',r['issues'])
    def test_minimized_window_unsafe(self):
        r=geometry_diagnosis(self._window(minimized=True))
        self.assertIn('WINDOW_MINIMIZED',r['issues'])

if __name__=='__main__':unittest.main()
