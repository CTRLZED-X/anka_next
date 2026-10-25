"""P52 adversarial anonymous multi-account process/socket research."""
from dataclasses import replace
import json
import unittest
from anka_app.ingress_readiness import stable_multi_account_topology
from anka_capture.windows_flows import TcpEndpoint
from anka_contracts.client import WindowObservation, WindowScan

TIME=10**10
K1=('192.0.2.1', 45670, '198.51.100.7', 40400)
K2=('192.0.2.1', 45671, '198.51.100.7', 40400)
K3=('192.0.2.1', 45672, '198.51.100.7', 40400)

def w(pid, hwnd=None, **kw):
    return replace(WindowObservation(hwnd or pid+1000,pid,pid+9000,'Dofus.exe',
            'Private Character',1280,649,96,False),**kw)

def data(pids=(101,102), keys=(K1,K2), owners=None, **kw):
    wins=tuple(w(p) for p in pids)
    before=WindowScan(TIME,wins)
    after=WindowScan(TIME+1000,wins)
    owner_pids=tuple(owners or pids)
    before_tcp=tuple(TcpEndpoint(*key,pid,5) for key,pid in zip(keys,owner_pids))
    flow_keys={f'flow-{i}':key for i,key in enumerate(keys)}
    return (before,after,before_tcp,before_tcp,flow_keys),kw

class P52MultiAccountTopology(unittest.TestCase):
    def invoke(self, *args, expected_clients=2, **kw):
        if not args:
            args,_=data(**kw)
        return stable_multi_account_topology(*args,expected_clients=expected_clients)

    def test_independent_two_processes_is_still_not_account_identity(self):
        out=self.invoke()
        self.assertEqual(out['status'],'CANDIDATES_ONLY')
        self.assertEqual(out['reason'],'P52_PROCESS_TOPOLOGY_ONLY')
        self.assertEqual((out['provisional_flows'],out['distinct_candidate_processes']),(2,2))
        self.assertFalse(out['account_binding_verified'])
        self.assertFalse(out['current_build_certified'])
        self.assertFalse(out['actionable'])
        self.assertEqual(out['canonical_commits'],0)

    def test_duplicate_same_flow_key_never_counts_two_independent_sockets(self):
        args,_=data(keys=(K1,K1),pids=(101,))
        r=self.invoke(*args)
        self.assertEqual(r['status'],'BLOCKED_AMBIGUOUS')
        self.assertEqual(r['reason'],'P52_DUPLICATE_SOCKET_SELECTORS')
        self.assertEqual(r['duplicate_socket_selectors'],1)

    def test_duplicate_same_flow_under_independent_tokens_still_blocks(self):
        args,_=data()
        r=self.invoke(*args[:4],{'Flow-A':K1,'Flow-B':K1})
        self.assertEqual(r['reason'],'P52_DUPLICATE_SOCKET_SELECTORS')

    def test_owner_conflict_visible_before_snapshots_intersect(self):
        args,_=data()
        b,a,bt,at,keys=args
        before=bt+(TcpEndpoint(*K1,999,5),)
        r=self.invoke(b,a,before,at,keys)
        self.assertEqual(r['ambiguous_flows'],1)
        self.assertEqual(r['distinct_candidate_processes'],1)
        self.assertEqual(r['reason'],'P52_FLOW_OWNERSHIP_AMBIGUOUS')

    def test_two_independent_connections_same_process_not_two_clients(self):
        args,_=data(pids=(101,),owners=(101,101))
        r=self.invoke(*args)
        self.assertEqual(r['distinct_candidate_processes'],1)
        self.assertEqual(r['multi_socket_candidate_processes'],1)
        self.assertEqual(r['reason'],'P52_INCOMPLETE_PROCESS_CANDIDATES')

    def test_extra_third_process_remains_anonymous(self):
        args,_=data(pids=(101,102,103),keys=(K1,K2,K3))
        r=self.invoke(*args)
        self.assertEqual(r['distinct_candidate_processes'],3)
        self.assertEqual(r['reason'],'P52_EXTRA_PROCESS_CANDIDATES')

    def test_one_missing_process_stays_partial(self):
        args,_=data()
        b,a,bt,at,keys=args
        r=self.invoke(b,a,bt,at[:1],keys)
        self.assertEqual(r['unmatched_flows'],1)
        self.assertEqual(r['reason'],'P52_INCOMPLETE_PROCESS_CANDIDATES')

    def test_pid_reuse_is_unmatched(self):
        args,_=data()
        b,a,bt,at,keys=args
        changed=replace(a,windows=(replace(a.windows[0],process_created_100ns=99),a.windows[1]))
        r=self.invoke(b,changed,bt,at,keys)
        self.assertEqual(r['unmatched_flows'],1)

    def test_geometry_change_is_unmatched(self):
        args,_=data()
        b,a,bt,at,keys=args
        changed=replace(a,windows=(replace(a.windows[0],client_width=200),a.windows[1]))
        r=self.invoke(b,changed,bt,at,keys)
        self.assertEqual(r['provisional_flows'],1)

    def test_duplicate_window_pid_is_not_unique(self):
        args,_=data()
        b,a,bt,at,keys=args
        second=replace(b, windows=b.windows+(w(101,hwnd=5000),))
        r=self.invoke(second,a,bt,at,keys)
        self.assertEqual(r['unmatched_flows'],1)

    def test_incomplete_windows_returns_unavailable(self):
        args,_=data()
        b,a,bt,at,keys=args
        r=self.invoke(replace(b,errors=('FAILED',)),a,bt,at,keys)
        self.assertEqual(r['status'],'UNAVAILABLE')

    def test_reversed_observation_clock_returns_unavailable(self):
        args,_=data()
        b,a,bt,at,keys=args
        r=self.invoke(b,replace(a,observed_monotonic_ns=1),bt,at,keys)
        self.assertEqual(r['status'],'UNAVAILABLE')

    def test_invalid_client_count_and_boolean_fails_closed(self):
        args,_=data()
        for n in (0,9,-1,True,'2',None):
            with self.subTest(n=n):
                self.assertEqual(self.invoke(*args,expected_clients=n)['status'],'UNAVAILABLE')

    def test_invalid_flow_tokens_fail_closed(self):
        args,_=data()
        for keys in ({1:K1}, {'':K1}, {'a'*129:K1}):
            with self.subTest(keys=keys):
                self.assertEqual(self.invoke(*args[:4],keys)['status'],'UNAVAILABLE')

    def test_private_data_never_exposed_even_on_success(self):
        args,_=data()
        r=self.invoke(*args)
        serialized=json.dumps(r)
        for secret in ('192.0.2.1','198.51.100.7','45670','Private Character',
                       'Dofus.exe','flow-0','101','102','win-'):
            with self.subTest(secret=secret):
                self.assertNotIn(secret,serialized)

    def test_untrusted_executable_not_accepted(self):
        args,_=data()
        b,a,bt,at,keys=args
        alien=replace(b.windows[0],executable_name='notepad.exe')
        r=self.invoke(replace(b,windows=(alien,b.windows[1])),a,bt,at,keys)
        self.assertEqual(r['provisional_flows'],1)

    def test_no_flow_claims_stay_candidate_only(self):
        args,_=data()
        r=self.invoke(*args[:4],{})
        self.assertEqual(r['candidate_flows'],0)
        self.assertEqual(r['distinct_candidate_processes'],0)
        self.assertFalse(r['account_binding_verified'])

    def test_more_than_4096_flow_tokens_is_unavailable(self):
        args,_=data()
        keys={str(i):('192.0.2.1',i,'198.51.100.7',40400) for i in range(4097)}
        self.assertEqual(self.invoke(*args[:4],keys)['status'],'UNAVAILABLE')

    def test_non_hashable_selector_fails_closed(self):
        args,_=data()
        keys={'a':['192.0.2.1',45670,'198.51.100.7',40400]}
        self.assertEqual(self.invoke(*args[:4],keys)['status'],'UNAVAILABLE')

    def test_positive_process_hint_without_character_witness_never_certified(self):
        args,_=data()
        r=self.invoke(*args)
        self.assertEqual(r['independent_character_witnesses'],0)
        self.assertFalse(r['physical_input_sent'])

if __name__=='__main__': unittest.main()
