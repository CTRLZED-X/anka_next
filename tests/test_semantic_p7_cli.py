import json,os,subprocess,sys,tempfile,unittest,zipfile
from pathlib import Path
from anka_app.cli import ROOT
from anka_app.semantic_offline import inspect_semantic_pcapng
from tests.capture_fixtures import pcapng,packet
from tests.test_protocol_wire import framed,any_body

class TestP7Commands(unittest.TestCase):
    def test_semantic_demo_cli(self):
        proc=subprocess.run([sys.executable,'-m','anka_app.cli','semantic-demo'],cwd=ROOT,capture_output=True,text=True,timeout=35)
        self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
        result=json.loads(next(s.split('=',1)[1] for s in proc.stdout.splitlines() if s.startswith('ANKA_RESULT=')))
        self.assertEqual(result['staged_candidates'],3)
        self.assertEqual(result['canonical_events_emitted'],0)
        self.assertIs(result['live_ready'],False)
    def test_live_start_still_fails_closed(self):
        proc=subprocess.run([sys.executable,'-m','anka_app.cli','start'],cwd=ROOT,capture_output=True,text=True,timeout=35)
        self.assertEqual(proc.returncode,40)
        self.assertIn('ANKA_FAILURE=START_WINDOWS_REQUIRED',proc.stdout)
    def test_synthetic_historical_capture_audit_stages_nothing_if_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'case.pcapng'
            wire=framed(any_body()) # jsq historical name, no supported semantic mapping
            target.write_bytes(pcapng(packet(100,flags=2,data=b'',reverse=True),packet(101,flags=0x18,data=wire,reverse=True)))
            report=inspect_semantic_pcapng(target,root=ROOT,ports=(40400,),build='Dofus 3.7.10.10')
            self.assertEqual(report['staged_candidates'],0)
            self.assertEqual(report['semantic_status_counts']['NO_SEMANTIC_MAPPING'],1)
            self.assertFalse(report['live_ready'])
    def test_semantic_audit_requires_ports(self):
        proc=subprocess.run([sys.executable,'-m','anka_app.cli','semantic-audit','evidence.pcapng','Dofus 3.7.10.10'],cwd=ROOT,capture_output=True,text=True,timeout=35)
        self.assertEqual(proc.returncode,40)
        self.assertIn('ANKA_FAILURE=CAPTURE_PORTS_NOT_CONFIGURED',proc.stdout)
        self.assertIn('ANKA_BUNDLE=',proc.stdout)

if __name__=='__main__':unittest.main()

class TestP7AuditProof(unittest.TestCase):
    def _audit(self,body,build='Dofus 3.7.10.10'):
        from tests.test_semantic_p7 import jtk
        with tempfile.TemporaryDirectory() as td:
            dst=Path(td)/'synthetic.pcapng'
            data=framed(any_body('jtk',body))
            dst.write_bytes(pcapng(packet(100,flags=2,data=b'',reverse=True),packet(101,flags=0x18,data=data,reverse=True)))
            return inspect_semantic_pcapng(dst,root=ROOT,ports=(40400,),build=build)
    def test_synthetic_historical_jtk_can_stage_but_not_commit(self):
        from tests.test_semantic_p7 import jtk
        r=self._audit(jtk())
        self.assertEqual(r['staged_candidates'],2)
        self.assertEqual(r['candidate_kinds'],{'ACTOR_RESOURCE_ABSOLUTE':2})
        self.assertEqual(r['committed_events'],0)
        self.assertFalse(r['live_state_mutated'])
        self.assertFalse(r['physical_input_sent'])
        self.assertFalse(r['gameplay_capabilities_certified'])
    def test_new_build_never_inherits_historical_semantics(self):
        from tests.test_semantic_p7 import jtk
        r=self._audit(jtk(),'Dofus 3.7.11.11')
        self.assertEqual(r['staged_candidates'],0)
        self.assertEqual(r['semantic_status_counts']['BUILD_MISMATCH'],1)
    def test_duplicate_messages_in_frame_are_counted_not_erased(self):
        from tests.test_semantic_p7 import jtk,b
        with tempfile.TemporaryDirectory() as td:
            dst=Path(td)/'repeated.pcapng'
            inner=any_body('jtk',jtk())
            data=framed(b(3,inner)+b(3,inner))
            dst.write_bytes(pcapng(packet(100,flags=2,data=b'',reverse=True),packet(101,flags=0x18,data=data,reverse=True)))
            r=inspect_semantic_pcapng(dst,root=ROOT,ports=(40400,),build='Dofus 3.7.10.10')
            self.assertEqual(r['wire']['framed_messages'],2)
            self.assertEqual(r['staged_candidates'],4)
    def test_callback_failure_quarantines_stream(self):
        from anka_protocol.api import ProtocolInspector
        from anka_protocol.adapters.historical import load_reference
        from anka_contracts.capture import CapturedTcpSegment
        def explode(_):raise RuntimeError('synthetic failure')
        inspector=ProtocolInspector(load_reference(ROOT),requested_build='Dofus 3.7.10.10',on_message=explode)
        inspector.consume(CapturedTcpSegment('synthetic','server_to_client',100,b'',1,2))
        inspector.consume(CapturedTcpSegment('synthetic','server_to_client',101,framed(any_body()),2,0x18))
        self.assertGreater(inspector.finish().quarantined_streams,0)
