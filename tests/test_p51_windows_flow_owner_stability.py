"""P51 deterministic Windows host/flow forgery tests without Windows access."""
from dataclasses import replace
import json
import unittest
from anka_app.ingress_readiness import stable_flow_hints, _safe_attribution
from anka_contracts.client import WindowScan, WindowObservation
from anka_capture.windows_flows import TcpEndpoint

TIME = 15_000_000_000
FLOW_A = ('127.0.0.1', 45000, '198.51.100.7', 40400)
FLOW_B = ('127.0.0.1', 45001, '198.51.100.7', 40400)

def window(pid=101, hwnd=501, created=1000, **kw):
    base = WindowObservation(hwnd, pid, created, 'Dofus.exe', 'CRA - Dofus', 1280, 649, 96, False)
    return replace(base, **kw)

def scan(*wins, at=TIME, errors=()):
    return WindowScan(at, tuple(wins), errors)

def tcp(flow=FLOW_A, pid=101, state=5):
    return TcpEndpoint(*flow, pid, state)

def probe(bw=None, aw=None, bt=None, at=None, keys=None):
    return stable_flow_hints(bw if bw is not None else scan(window()),
                             aw if aw is not None else scan(window(), at=TIME+1_000_000_000),
                             bt if bt is not None else (tcp(),),
                             at if at is not None else (tcp(),),
                             keys if keys is not None else {'opaque': FLOW_A})

class WindowsFlowOwnerStability(unittest.TestCase):
    def test_stable_window_and_tcp_are_only_provisional(self):
        self.assertEqual(probe(), {'status': 'NOT_ATTESTED', 'counts':
                                  {'PROVISIONAL': 1, 'AMBIGUOUS': 0, 'UNMATCHED': 0}})
    def test_duplicate_owner_present_only_before_must_not_disappear(self):
        r = probe(bt=(tcp(), tcp(pid=111)))
        self.assertEqual(r['counts']['AMBIGUOUS'], 1)
    def test_duplicate_owner_present_only_after_must_not_disappear(self):
        r = probe(at=(tcp(), tcp(pid=111)))
        self.assertEqual(r['counts']['AMBIGUOUS'], 1)
    def test_duplicate_exact_os_row_remains_ambiguous(self):
        self.assertEqual(probe(bt=(tcp(), tcp()))['counts']['AMBIGUOUS'], 1)
    def test_pid_changes_between_tables(self):
        self.assertEqual(probe(at=(tcp(pid=102),))['counts']['AMBIGUOUS'], 1)
    def test_tcp_state_transition_disallows_stable_hint(self):
        self.assertEqual(probe(at=(tcp(state=8),))['counts']['UNMATCHED'], 1)
    def test_tcp_connection_closes_between_snapshots(self):
        self.assertEqual(probe(at=())['counts']['UNMATCHED'], 1)
    def test_unknown_tcp_endpoint(self):
        self.assertEqual(probe(keys={'t': FLOW_B})['counts']['UNMATCHED'], 1)
    def test_process_creation_changed(self):
        self.assertEqual(probe(aw=scan(window(created=1001), at=TIME+1))['counts']['UNMATCHED'], 1)
    def test_hwnd_changed(self):
        self.assertEqual(probe(aw=scan(window(hwnd=502), at=TIME+1))['counts']['UNMATCHED'], 1)
    def test_executable_changes_not_trusted(self):
        self.assertEqual(probe(aw=scan(window(executable_name='notepad.exe'), at=TIME+1))['counts']['UNMATCHED'], 1)
    def test_untrusted_image_both_boundaries(self):
        s1=scan(window(executable_name='notepad.exe'))
        self.assertEqual(probe(bw=s1,aw=scan(window(executable_name='notepad.exe'),at=TIME+1))['counts']['UNMATCHED'],1)
    def test_window_resize_mid_capture(self):
        self.assertEqual(probe(aw=scan(window(client_width=1200), at=TIME+1))['counts']['UNMATCHED'],1)
    def test_dpi_changed_mid_capture(self):
        self.assertEqual(probe(aw=scan(window(dpi=144), at=TIME+1))['counts']['UNMATCHED'],1)
    def test_minimized_client_mid_capture(self):
        self.assertEqual(probe(aw=scan(window(minimized=True), at=TIME+1))['counts']['UNMATCHED'],1)
    def test_zero_geometry_both_snapshots(self):
        w=window(client_width=0)
        self.assertEqual(probe(bw=scan(w),aw=scan(w,at=TIME+1))['counts']['UNMATCHED'],1)
    def test_duplicate_hwnd_in_inventory_unavailable(self):
        self.assertEqual(probe(bw=scan(window(),window(pid=102)))['status'],'UNAVAILABLE')
    def test_shared_pid_windows_are_unmatched(self):
        bw=scan(window(),window(hwnd=700))
        aw=scan(window(),window(hwnd=700), at=TIME+1)
        self.assertEqual(probe(bw=bw,aw=aw)['counts']['UNMATCHED'],1)
    def test_incomplete_inventory_unavailable(self):
        self.assertEqual(probe(aw=scan(window(),errors=('INSPECT_FAILED',)))['status'],'UNAVAILABLE')
    def test_reversed_monotonic_time_unavailable(self):
        self.assertEqual(probe(aw=scan(window(),at=TIME-1))['status'],'UNAVAILABLE')
    def test_overlong_snapshot_interval_unavailable(self):
        self.assertEqual(probe(aw=scan(window(),at=TIME+31_000_000_000))['status'],'UNAVAILABLE')
    def test_invalid_time_unavailable(self):
        self.assertEqual(probe(bw=scan(window(),at=0))['status'],'UNAVAILABLE')
    def test_invalid_flow_key_blocked(self):
        for val in (('127.0.0.1',True,'198.51.100.7',40400),('x',-1,'y',40400),('x',5,'y'),[],'evil'):
            with self.subTest(value=val):
                self.assertEqual(probe(keys={'t':val})['status'],'UNAVAILABLE')
    def test_all_account_data_and_ips_stay_private(self):
        result=probe()
        safe = _safe_attribution(result)
        serialized=json.dumps(safe)
        for secret in ('198.51.100.7','CRA','Dofus','45000','101','501','opaque'):
            self.assertNotIn(secret,serialized)
        self.assertNotIn('account_binding_verified',result)
    def test_two_distinct_flows_have_independent_hints(self):
        w1, w2=window(), window(pid=102,hwnd=502,created=1001)
        b=scan(w1,w2)
        a=scan(w1,w2,at=TIME+1)
        result=probe(bw=b,aw=a,bt=(tcp(),tcp(FLOW_B,102)),
                     at=(tcp(),tcp(FLOW_B,102)), keys={'a':FLOW_A,'b':FLOW_B})
        self.assertEqual(result['counts'], {'PROVISIONAL':2,'AMBIGUOUS':0,'UNMATCHED':0})
        self.assertEqual(result['status'],'NOT_ATTESTED')
    def test_one_flow_disputed_other_remains_observation(self):
        w1, w2=window(),window(pid=102,hwnd=502,created=1001)
        s1=scan(w1,w2)
        result=probe(bw=s1,aw=scan(w1,w2,at=TIME+1),
                     bt=(tcp(),tcp(FLOW_B,102),tcp(FLOW_B,103)),
                     at=(tcp(),tcp(FLOW_B,102)), keys={'a':FLOW_A,'b':FLOW_B})
        self.assertEqual(result['counts'], {'PROVISIONAL':1,'AMBIGUOUS':1,'UNMATCHED':0})
    def test_malformed_os_snapshot_unavailable(self):
        self.assertEqual(probe(bt=(object(),))['status'],'UNAVAILABLE')
    def test_empty_capture_is_still_uncertified(self):
        self.assertEqual(probe(keys={}), {'status':'NOT_ATTESTED','counts':
                                         {'PROVISIONAL':0,'AMBIGUOUS':0,'UNMATCHED':0}})

if __name__=='__main__':
    unittest.main()
