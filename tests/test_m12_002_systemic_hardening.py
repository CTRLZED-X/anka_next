from __future__ import annotations
import json, tempfile, unittest
from pathlib import Path
from zipfile import ZipFile
from unittest.mock import patch

from anka_app.cli import ROOT
from anka_app.configuration import load_user_config
from anka_app.host_readiness import probe_host
from anka_app.ingress_readiness import probe_start_ingress,_same_process_generations
from anka_app.startup_acceptance import blocker_for,blockers_for,boundary_for,STARTUP_TRACE
from anka_capture.windows_flows import TcpEndpoint
from anka_capture.windows_scope import derive_windows_capture_scope,resolve_scapy_interface
from anka_capture.windows_backend import probe_npcap_presence
from anka_capture.windows_live import WindowsLiveCapture
from anka_client.bridge_discovery import probe_bridge_range
from anka_client.win32_inventory import _candidate_observation
from anka_contracts.client import WindowObservation,WindowScan
from anka_observability.api import LocalDiagnostics
from anka_observability.bundle import verify_incident
from tools.windows_bridge_setup import _detect_bepinex,_missing
from anka_app.release_integrity import verify_release_integrity

CFG=load_user_config(ROOT/'config/user.json')

def win(pid=10,created=20,title='Generic Unity Window',exe='Dofus.exe',hwnd=None,build=None):
    return WindowObservation(hwnd if hwnd is not None else pid,pid,created,exe,title,1280,649,96,False,True,None,build)

class FakeInventory:
    def __init__(self, scan):self.value=scan
    def scan(self):return self.value

def factory(scan):return lambda names:FakeInventory(scan)

class FakeSniffer:
    def __init__(self,**kw):self.kw=kw
    def start(self):pass
    def stop(self):pass

class TestM12002SystemicHardening(unittest.TestCase):
    def test_setup_banner_and_auto_capture_dependency_are_operator_facing(self):
        entry=(ROOT/'tools/windows/_entry.bat').read_text()
        self.assertIn('ANKA SETUP COMPLETED SUCCESSFULLY',entry)
        self.assertIn('STAGE=INSTALL_CAPTURE_DEPENDENCIES',entry)
        self.assertNotIn("cfg.get('server_ports') and cfg.get('interface')",entry)
        self.assertEqual((ROOT/'requirements-windows-capture.txt').read_text().strip().splitlines()[-1],'scapy==2.6.1')

    def test_generic_title_is_kept_when_executable_is_dofus(self):
        self.assertTrue(_candidate_observation(win(title='Completely generic'),hinted=False))
        self.assertFalse(_candidate_observation(win(exe='notepad.exe'),hinted=False))
        self.assertTrue(_candidate_observation(win(exe='notepad.exe'),hinted=True))

    def test_auto_scope_uses_dofus_pid_and_hides_endpoints(self):
        rows=(TcpEndpoint('10.0.0.2',50000,'203.0.113.1',443,10,5),
              TcpEndpoint('10.0.0.2',50001,'2001:db8::1',5555,10,5,'IPv6'),
              TcpEndpoint('10.0.0.2',50002,'198.51.100.1',9999,99,5))
        scope=derive_windows_capture_scope({10},rows)
        self.assertEqual(scope.server_ports,(443,5555))
        safe=scope.safe_receipt()
        self.assertEqual(safe['server_port_count'],2)
        blob=json.dumps(safe)
        self.assertNotIn('203.0.113.1',blob);self.assertNotIn('2001:db8',blob)

    def test_auto_scope_fails_closed_if_too_broad(self):
        rows=tuple(TcpEndpoint('10.0.0.2',40000+i,f'198.51.100.{i+1}',1000+i,10,5) for i in range(33))
        scope=derive_windows_capture_scope({10},rows)
        self.assertFalse(scope.server_ports);self.assertEqual(scope.mode,'TOO_MANY_SERVER_PORTS')


    def test_ipv6_scope_and_live_matching_use_canonical_address_form(self):
        rows=(TcpEndpoint('2001:0db8:0:0:0:0:0:2',50000,'2001:0db8:0:0:0:0:0:9',443,10,5,'IPv6'),)
        scope=derive_windows_capture_scope({10},rows)
        self.assertEqual(scope.allowed_flows,(('2001:db8::2',50000,'2001:db8::9',443),))
        c=WindowsLiveCapture(interface='fake',server_ports=(443,),allowed_flows=scope.allowed_flows,
                             require_windows=False,sniffer_factory=FakeSniffer)
        c.start()
        self.assertTrue(c.ingest_fields(src='2001:db8::2',dst='2001:db8:0:0::9',sport=50000,dport=443,seq=1,flags=2,payload=b''))
        c.stop()

    def test_interface_resolution_requires_every_local_ip_on_one_adapter(self):
        v4=lambda:[('10.0.0.2','Npcap A'),('10.0.0.3','Npcap A')]
        self.assertEqual(resolve_scapy_interface(('10.0.0.2','10.0.0.3'),ipv4_inventory=v4,ipv6_inventory=lambda:()),'Npcap A')
        split=lambda:[('10.0.0.2','Npcap A'),('10.0.0.3','Npcap B')]
        self.assertIsNone(resolve_scapy_interface(('10.0.0.2','10.0.0.3'),ipv4_inventory=split,ipv6_inventory=lambda:()))
        v6=lambda:[('2001:db8::2','Npcap A')]
        self.assertEqual(resolve_scapy_interface(('2001:0db8::2',),ipv4_inventory=lambda:(),ipv6_inventory=v6),'Npcap A')

    def test_npcap_probe_uncertainty_blocks_before_capture_attempt(self):
        host={'platform':'WINDOWS','candidate_windows':2,'issues':[],
              'capture':{'scapy_installed':True,'npcap_driver':'PROBE_INCOMPLETE','server_port_candidates':1,
                         'interface_resolution':'RESOLVED'}}
        result=probe_start_ingress(CFG,host,platform='nt',sample=lambda _cfg: self.fail('capture must not run'))
        self.assertEqual(result['status'],'SKIPPED');self.assertEqual(result['reason'],'NPCAP_NOT_READY')
        self.assertEqual(blocker_for(host,result),'START_NPCAP_NOT_READY')

    def test_interface_ambiguity_blocks_before_capture_attempt(self):
        host={'platform':'WINDOWS','candidate_windows':2,'issues':['CAPTURE_INTERFACE_UNRESOLVED'],
              'capture':{'scapy_installed':True,'npcap_driver':'DETECTED_UNVERIFIED','server_port_candidates':1,
                         'interface_resolution':'UNRESOLVED'}}
        result=probe_start_ingress(CFG,host,platform='nt',sample=lambda _cfg: self.fail('capture must not run'))
        self.assertEqual(result['reason'],'CAPTURE_INTERFACE_UNRESOLVED')
        self.assertEqual(blocker_for(host,result),'START_CAPTURE_INTERFACE_UNRESOLVED')

    def test_start_distinguishes_no_traffic_no_framing_and_semantic_gap(self):
        host={'platform':'WINDOWS','candidate_windows':2,'issues':[],
              'capture':{'scapy_installed':True,'npcap_driver':'DETECTED_UNVERIFIED','server_port_candidates':1,
                         'interface_resolution':'RESOLVED'}}
        base={'status':'CAPTURED_UNCERTIFIED','receipt':{'capture_scope_stability_observed':True,
              'capture_scope_stable':True,'process_generation_stability_observed':True,'process_generation_stable':True}}
        for wire,expected in (({'status':'OBSERVED_UNCERTIFIED','selected_segments':0,'framed_messages':0,'quarantined_streams':0,'unanchored_streams':0},'START_GAME_TRAFFIC_NOT_OBSERVED'),
                              ({'status':'OBSERVED_UNCERTIFIED','selected_segments':3,'framed_messages':0,'quarantined_streams':0,'unanchored_streams':0},'START_PROTOCOL_FRAMING_NOT_OBSERVED'),
                              ({'status':'OBSERVED_UNCERTIFIED','selected_segments':3,'framed_messages':1,'quarantined_streams':1,'unanchored_streams':0},'START_PROTOCOL_STREAM_INCOMPLETE'),
                              ({'status':'OBSERVED_UNCERTIFIED','selected_segments':3,'framed_messages':1,'quarantined_streams':0,'unanchored_streams':0},'CURRENT_CLIENT_SEMANTIC_ADAPTER_UNCERTIFIED')):
            ingress={'status':base['status'],'receipt':{**base['receipt'],'protocol_wire':wire}}
            self.assertEqual(blocker_for(host,ingress),expected)

    def test_live_capture_accepts_default_interface_and_stays_read_only(self):
        c=WindowsLiveCapture(interface=None,server_ports=(443,),require_windows=False,sniffer_factory=FakeSniffer)
        c.start();c.stop()
        self.assertFalse(c.safe_stats()['physical_input_sent'])

    def test_exact_flow_scope_rejects_same_port_unrelated_process_traffic(self):
        allowed=(('10.0.0.2',50000,'203.0.113.1',443),)
        c=WindowsLiveCapture(interface=None,server_ports=(443,),allowed_flows=allowed,require_windows=False,sniffer_factory=FakeSniffer)
        c.start()
        self.assertTrue(c.ingest_fields(src='10.0.0.2',dst='203.0.113.1',sport=50000,dport=443,seq=1,flags=2,payload=b''))
        self.assertFalse(c.ingest_fields(src='10.0.0.2',dst='198.51.100.9',sport=50001,dport=443,seq=1,flags=2,payload=b''))
        poll=c.poll(max_segments=10,timeout_seconds=0)
        self.assertEqual(len(poll.segments),1);self.assertEqual(poll.dropped,1)
        c.stop()

    def test_host_derives_capture_scope_without_user_capture_config(self):
        scan=WindowScan(100,(win(10,20),win(11,21)))
        rows=(TcpEndpoint('10.0.0.2',50000,'203.0.113.1',443,10,5),
              TcpEndpoint('10.0.0.2',50001,'203.0.113.1',443,11,5))
        report=probe_host(CFG,platform='nt',inventory_factory=factory(scan),tcp_snapshot=lambda:rows,
                          scapy_available=lambda:True,bridge_probe=lambda windows:{'status':'NOT_DETECTED','healthy_bridges':0,
                          'process_generation_matches':0,'projection_ready_matches':0,'character_identity_provided':False,
                          'physical_input_permitted':False})
        self.assertEqual(report['capture']['server_port_candidates'],1)
        self.assertEqual(report['capture']['endpoint_selector_candidates'],2)
        self.assertEqual(report['capture']['scope_mode'],'AUTO_PROCESS_TCP')
        self.assertNotIn('CAPTURE_SERVER_PORTS_UNCONFIGURED',report['issues'])
        self.assertFalse(report['physical_input_permitted'])

    def test_observe_only_capture_does_not_require_character_binding(self):
        host={'platform':'WINDOWS','candidate_windows':2,'account_binding_states':['BLOCKED','BLOCKED'],
              'capture':{'scapy_installed':True,'server_port_candidates':1}}
        minimal={'status':'UNCERTIFIED','selected_segments':0,'queue_dropped':0,'invalid_frames':0,
                 'rejected_frames':0,'unsupported_frames':0,'driver_loss_visibility':'UNKNOWN',
                 'transport':{'unanchored_directions':0,'unresolved_gap_directions':0,'observed_generations':0,
                              'reconnections':0,'duplicate_segments':0,'reordered_segments':0,
                              'metadata_limit_reached':False,'packet_order_uncertain':False},
                 'flow_attribution':{'status':'NOT_ATTESTED','counts':{'PROVISIONAL':0,'AMBIGUOUS':0,'UNMATCHED':0}}}
        r=probe_start_ingress(CFG,host,platform='nt',sample=lambda _:minimal)
        self.assertEqual(r['status'],'CAPTURED_UNCERTIFIED');self.assertFalse(r['account_binding_verified'])

    def test_start_blockers_are_specific_and_boundary_owned(self):
        host={'platform':'WINDOWS','candidate_windows':0,'issues':[], 'capture':{'scapy_installed':True,'server_port_candidates':0}}
        code=blocker_for(host,{'status':'SKIPPED'})
        self.assertEqual(code,'START_DOFUS_WINDOW_NOT_FOUND');self.assertEqual(boundary_for(code),'client.host_observation')
        host['candidate_windows']=2;host['capture']['server_port_candidates']=1
        code=blocker_for(host,{'status':'FAILED'})
        self.assertEqual(code,'START_CAPTURE_SAMPLE_FAILED');self.assertEqual(boundary_for(code),'capture.observe_only')

    def test_window_count_ambiguity_blocks_automatic_capture_scope(self):
        scan=WindowScan(100,(win(10,20),win(11,21),win(12,22)))
        rows=tuple(TcpEndpoint('10.0.0.2',50000+i,'203.0.113.1',443,10+i,5) for i in range(3))
        report=probe_host(CFG,platform='nt',inventory_factory=factory(scan),tcp_snapshot=lambda:rows,
                          scapy_available=lambda:True,npcap_probe=lambda:{'status':'DETECTED_UNVERIFIED'},
                          bridge_probe=lambda windows:{'status':'NOT_DETECTED','healthy_bridges':0,'process_generation_matches':0,
                          'projection_ready_matches':0,'character_identity_provided':False,'physical_input_permitted':False})
        self.assertIn('DOFUS_WINDOW_COUNT_AMBIGUOUS',report['issues'])
        self.assertEqual(report['capture']['server_port_candidates'],0)
        self.assertEqual(blocker_for(report,{'status':'SKIPPED'}),'START_DOFUS_WINDOW_COUNT_AMBIGUOUS')

    def test_process_generation_drift_is_detected_even_if_pid_is_reused(self):
        before=WindowScan(100,(win(10,20),win(11,21)))
        same=WindowScan(200,(win(10,20),win(11,21)))
        reused=WindowScan(200,(win(10,99),win(11,21)))
        self.assertTrue(_same_process_generations(before,same,expected_clients=2))
        self.assertFalse(_same_process_generations(before,reused,expected_clients=2))

    def test_scope_drift_is_a_capture_boundary_blocker(self):
        ingress={'status':'CAPTURED_UNCERTIFIED','receipt':{
            'capture_scope_stability_observed':True,'capture_scope_stable':False,
            'process_generation_stability_observed':True,'process_generation_stable':True}}
        host={'platform':'WINDOWS','candidate_windows':2,'issues':[],
              'capture':{'scapy_installed':True,'npcap_driver':'DETECTED_UNVERIFIED','server_port_candidates':1}}
        code=blocker_for(host,ingress)
        self.assertEqual(code,'START_CAPTURE_SCOPE_DRIFT');self.assertEqual(boundary_for(code),'capture.observe_only')

    def test_capture_failure_code_is_allowlisted_not_exception_text(self):
        host={'platform':'WINDOWS','candidate_windows':2,
              'capture':{'scapy_installed':True,'server_port_candidates':1}}
        def bad(_): raise RuntimeError('secret path C:/Users/private')
        result=probe_start_ingress(CFG,host,platform='nt',sample=bad)
        self.assertEqual(result['error_code'],'UNCLASSIFIED_CAPTURE_FAILURE')
        self.assertNotIn('private',json.dumps(result))

    def test_npcap_probe_can_be_falsified_with_injected_windows_tree(self):
        class Done:
            returncode=0;stdout='SERVICE_NAME: npcap'
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);folder=root/'System32'/'Npcap';folder.mkdir(parents=True)
            (folder/'wpcap.dll').write_bytes(b'x');(folder/'Packet.dll').write_bytes(b'y')
            r=probe_npcap_presence(platform='nt',system_root=td,runner=lambda *a,**k:Done())
            self.assertEqual(r['status'],'DETECTED_UNVERIFIED')
            (folder/'Packet.dll').unlink()
            r=probe_npcap_presence(platform='nt',system_root=td,runner=lambda *a,**k:Done())
            self.assertEqual(r['status'],'SERVICE_PRESENT_DLLS_MISSING')

    def test_npcap_dlls_allow_bounded_backend_attempt_when_service_probe_is_unconfirmed(self):
        class Failed:
            returncode=1;stdout=''
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);folder=root/'System32'/'Npcap';folder.mkdir(parents=True)
            (folder/'wpcap.dll').write_bytes(b'x');(folder/'Packet.dll').write_bytes(b'y')
            r=probe_npcap_presence(platform='nt',system_root=td,runner=lambda *a,**k:Failed())
            self.assertEqual(r['status'],'DLLS_PRESENT_SERVICE_UNCONFIRMED')
            host={'platform':'WINDOWS','candidate_windows':2,'issues':[],
                  'capture':{'scapy_installed':True,'npcap_driver':r['status'],'server_port_candidates':1,
                             'interface_resolution':'RESOLVED'}}
            result=probe_start_ingress(CFG,host,platform='nt',sample=lambda _:{'status':'UNCERTIFIED','selected_segments':0})
            self.assertTrue(result['capture_attempted'])

    def test_live_capture_dependency_error_is_preserved(self):
        c=WindowsLiveCapture(interface=None,server_ports=(443,),require_windows=False,sniffer_factory=None)
        with patch.object(c,'_ensure_factory',side_effect=RuntimeError('SCAPY_NOT_INSTALLED_OPTIONAL_CAPTURE_DEPENDENCY')):
            with self.assertRaisesRegex(RuntimeError,'SCAPY_NOT_INSTALLED_OPTIONAL_CAPTURE_DEPENDENCY'):
                c.start()

    def test_bridge_scan_matches_exact_process_generation_only(self):
        class Reader:
            def get_json(self,port,route):
                if port!=8766:raise OSError()
                return {'source':'unity_bridge','available':True,'processId':10,'processStartTime':20,
                        'bridgePort':8766,'status':'MAP_COORDINATES_READY','sourceVerified':True,'loadedMapId':123}
        r=probe_bridge_range((win(),),port_start=8765,port_count=3,reader_factory=Reader)
        self.assertEqual(r['process_generation_matches'],1);self.assertEqual(r['projection_ready_matches'],1)
        self.assertFalse(r['character_identity_provided']);self.assertFalse(r['physical_input_permitted'])

    def test_bridge_requires_unique_coverage_for_every_process_generation(self):
        class Reader:
            def __init__(self, mode):self.mode=mode
            def get_json(self,port,route):
                if self.mode=='partial':
                    if port!=8765:raise OSError()
                    pid,created=10,20
                else:
                    if port not in (8765,8766):raise OSError()
                    pid,created=(10,20)
                return {'source':'unity_bridge','available':True,'processId':pid,'processStartTime':created,
                        'bridgePort':port,'status':'MAP_COORDINATES_READY','sourceVerified':True,'loadedMapId':123}
        windows=(win(10,20),win(11,21))
        partial=probe_bridge_range(windows,port_start=8765,port_count=2,reader_factory=lambda:Reader('partial'))
        self.assertEqual(partial['status'],'PARTIAL_PROCESS_MATCH');self.assertEqual(partial['matched_process_generations'],1)
        duplicate=probe_bridge_range(windows,port_start=8765,port_count=2,reader_factory=lambda:Reader('duplicate'))
        self.assertEqual(duplicate['status'],'AMBIGUOUS_PROCESS_MATCH');self.assertEqual(duplicate['duplicate_process_generation_matches'],1)

    def test_host_reports_consistent_build_without_certifying_semantics(self):
        scan=WindowScan(100,(win(10,20,build='3.7.11.11'),win(11,21,build='3.7.11.11')))
        rows=(TcpEndpoint('10.0.0.2',50000,'203.0.113.1',443,10,5),
              TcpEndpoint('10.0.0.2',50001,'203.0.113.1',443,11,5))
        report=probe_host(CFG,platform='nt',inventory_factory=factory(scan),tcp_snapshot=lambda:rows,
                          scapy_available=lambda:True,npcap_probe=lambda:{'status':'DETECTED_UNVERIFIED'},
                          bridge_probe=lambda windows:{'status':'COMPLETE_PROCESS_MATCH','healthy_bridges':2,
                          'matched_process_generations':2,'process_generation_matches':2,'projection_ready_matches':2,
                          'character_identity_provided':False,'physical_input_permitted':False})
        self.assertEqual(report['client_build'],{'status':'CONSISTENT','version':'3.7.11.11','reported_clients':2})
        self.assertFalse(report['live_certified']);self.assertFalse(report['physical_input_permitted'])

    def test_host_detects_cross_account_build_mismatch(self):
        scan=WindowScan(100,(win(10,20,build='3.7.11.11'),win(11,21,build='3.7.12.12')))
        report=probe_host(CFG,platform='nt',inventory_factory=factory(scan),tcp_snapshot=lambda:(),
                          scapy_available=lambda:True,npcap_probe=lambda:{'status':'DETECTED_UNVERIFIED'},
                          bridge_probe=lambda windows:{'status':'NOT_DETECTED','healthy_bridges':0,'process_generation_matches':0,
                          'projection_ready_matches':0,'character_identity_provided':False,'physical_input_permitted':False})
        self.assertEqual(report['client_build']['status'],'MISMATCH')
        self.assertIn('CURRENT_CLIENT_BUILD_MISMATCH',report['issues'])
        self.assertIn('START_CLIENT_BUILD_MISMATCH',blockers_for(report,{'status':'SKIPPED'}))

    def test_bridge_path_detection_uses_env_without_storing_it(self):
        with tempfile.TemporaryDirectory() as td:
            b=Path(td);(b/'core').mkdir();(b/'interop').mkdir()
            self.assertEqual(_detect_bepinex({'BEPINEX_PATH':td}),b)
            self.assertIn('BepInEx.Core.dll',_missing(b))


    def test_start_assessment_reports_multiple_independent_blockers(self):
        host={'platform':'WINDOWS','candidate_windows':2,
              'issues':['CURRENT_CHARACTER_IDENTITY_EVIDENCE_MISSING'],
              'capture':{'scapy_installed':False,'npcap_driver':'NOT_DETECTED','server_port_candidates':0,
                         'scope_status':'NO_TCP_SCOPE','scope_mode':'AUTO_PROCESS_TCP','interface_resolution':'NO_TCP_SCOPE'},
              'bridge':{'process_generation_matches':0}}
        codes=blockers_for(host,{'status':'SKIPPED','reason':'OPTIONAL_CAPTURE_DEPENDENCY_MISSING'},
                           capture_setup={'status':'STALE_SETUP_RECORD'},bridge_setup={'status':'STALE_SETUP_RECORD'})
        self.assertEqual(codes[0],'START_CAPTURE_DEPENDENCY_MISSING')
        self.assertIn('START_CAPTURE_DEPENDENCY_MISSING',codes)
        self.assertIn('START_NPCAP_NOT_READY',codes)
        self.assertIn('START_DOFUS_TCP_FLOW_NOT_FOUND',codes)
        self.assertIn('START_UNITY_BRIDGE_PROCESS_MATCH_MISSING',codes)
        self.assertIn('START_CHARACTER_IDENTITY_EVIDENCE_MISSING',codes)

    def test_release_integrity_allows_user_config_change_but_rejects_source_change_and_injection(self):
        from hashlib import sha256
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'src/pkg').mkdir(parents=True);(root/'config').mkdir()
            source=root/'src/pkg/a.py';source.write_text('VALUE=1\n')
            user=root/'config/user.json';user.write_text('{"schema_version":1}\n')
            entries=[]
            for path in (source,user):
                raw=path.read_bytes();entries.append({'path':path.relative_to(root).as_posix(),
                    'sha256':sha256(raw).hexdigest(),'size':len(raw)})
            (root/'RELEASE_MANIFEST.json').write_text(json.dumps({'schema_version':1,'release_id':'T','files':entries}))
            self.assertEqual(verify_release_integrity(root).status,'PASS')
            user.write_text('{"schema_version":1,"changed":true}\n')
            self.assertEqual(verify_release_integrity(root).status,'PASS')
            source.write_text('VALUE=2\n')
            self.assertEqual(verify_release_integrity(root).status,'FAIL')
            source.write_text('VALUE=1\n')
            (root/'src/pkg/injected.py').write_text('BAD=True\n')
            r=verify_release_integrity(root)
            self.assertEqual(r.status,'FAIL');self.assertEqual(len(r.unexpected_executable_files),1)

    def test_runtime_integrity_does_not_promote_verification_receipts_to_runtime_authority(self):
        from hashlib import sha256
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'src/pkg').mkdir(parents=True);(root/'verification').mkdir();(root/'docs').mkdir()
            source=root/'src/pkg/a.py';source.write_text('VALUE=1\n')
            receipt=root/'verification/Q9_receipt.json';receipt.write_text('{"status":"PASS"}\n')
            doc=root/'docs/readme.md';doc.write_text('evidence\n')
            entries=[]
            for path in (source,receipt,doc):
                raw=path.read_bytes();entries.append({'path':path.relative_to(root).as_posix(),
                    'sha256':sha256(raw).hexdigest(),'size':len(raw)})
            (root/'RELEASE_MANIFEST.json').write_text(json.dumps({'schema_version':1,'release_id':'T','files':entries}))
            self.assertEqual(verify_release_integrity(root).status,'PASS')
            receipt.write_text('{"status":"FAIL"}\n');doc.write_text('changed evidence\n')
            self.assertEqual(verify_release_integrity(root).status,'PASS')
            source.write_text('VALUE=2\n')
            self.assertEqual(verify_release_integrity(root).status,'FAIL')

    def test_project_info_preserves_versioned_release_contract(self):
        # This retained _002 regression must remain valid for later releases.
        # Exact current-version assertions belong to the current release suite
        # (for example test_m12_003_live_readiness_hardening), otherwise every
        # legitimate version bump makes the historical regression stale.
        info=(ROOT/'PROJECT_INFO.txt').read_text()
        self.assertIn('PROJECT_NAME=ANKA_NEXT',info)
        self.assertRegex(info,r'(?m)^PROJECT_VERSION=ANKA_NEXT_M12_\d{3}$')

    def test_incident_exports_bounded_sanitized_snapshots(self):
        with tempfile.TemporaryDirectory() as td:
            o=LocalDiagnostics(Path(td))
            self.assertEqual(o.register_snapshot('host_observation',{'status':'BLOCKED','token':'super-secret','path':'C:\\Users\\private\\x'}),'RECORDED')
            o.record('start.static_preflight_passed',boundary='startup.static_preflight',owner_system='anka_app')
            p=o.export_incident('START_DOFUS_WINDOW_NOT_FOUND',boundary='client.host_observation',trace_spec=STARTUP_TRACE,control_state='BLOCKED')
            self.assertEqual(verify_incident(p)['status'],'PASS')
            with ZipFile(p) as z:
                self.assertIn('snapshots/host_observation.json',z.namelist())
                blob=b'\n'.join(z.read(n) for n in z.namelist()).decode('utf8','ignore')
            self.assertNotIn('super-secret',blob);self.assertNotIn('private',blob)

if __name__=='__main__':unittest.main()
