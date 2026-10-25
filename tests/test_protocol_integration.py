import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from anka_app.cli import ROOT, _command
from anka_app.configuration import load_user_config
from anka_capture.pcapng import read_pcapng_tcp_segments
from anka_contracts.capture import CapturedTcpSegment, CapturePoll
from anka_contracts.protocol import WireMessage
from anka_protocol.adapters.historical import load_reference,CatalogRejected
from anka_protocol.api import ProtocolInspector,synthetic_wire_demo
from anka_app.protocol_offline import inspect_protocol_pcapng
from anka_observability.api import LocalDiagnostics
from tests.capture_fixtures import pcapng,packet
from tests.test_protocol_wire import framed,any_body


def seg(seq,body=b'',number=1,flags=0x18,direction='server_to_client',flow='connection-1'):
    return CapturedTcpSegment(flow,direction,seq,body,number,flags)

class TestProtocolSystem(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.catalog=load_reference(ROOT)
    def observer(self):return LocalDiagnostics(self.root/'runtime')
    def inspector(self,build='Dofus 3.7.10.10',observer=None):
        return ProtocolInspector(self.catalog,requested_build=build,observer=observer)
    def test_historical_manifest_checks_sha(self):
        self.assertGreater(len(self.catalog.known_keys),40)
        self.assertFalse(self.catalog.semantic_certified)
        self.assertIn(('jsq','server_to_client'),self.catalog.known_keys)
    def test_tampered_reference_detected(self):
        folder=self.root/'reference/protocol';folder.mkdir(parents=True)
        for p in (ROOT/'reference/protocol').glob('*.json'):shutil.copy2(p,folder/p.name)
        with (folder/'dofus_3_7_10_10_wire_catalog.json').open('a') as f:f.write(' ')
        with self.assertRaisesRegex(CatalogRejected,'REFERENCE_HASH_MISMATCH'):load_reference(self.root)
    def test_known_observation_only_never_authoritative(self):
        p=self.inspector();p.consume(seg(100,flags=2));p.consume(seg(101,framed(any_body())))
        r=p.finish()
        self.assertEqual(r.framed_messages,1)
        self.assertEqual(r.classified_observations,1)
        self.assertEqual(r.canonical_events_emitted,0)
        self.assertFalse(r.gameplay_capabilities_certified)
        self.assertFalse(r.account_identity_certified)
        self.assertEqual(r.status,'HISTORICAL_WIRE_OBSERVATION_ONLY')
    def test_unknown_message_is_nonmutating(self):
        p=self.inspector();p.consume(seg(100,flags=2));p.consume(seg(101,framed(any_body('brand_new'))))
        r=p.finish()
        self.assertEqual(r.unknown_messages,1);self.assertEqual(r.canonical_events_emitted,0)
        self.assertEqual(r.findings[0].category,'UNKNOWN_WIRE')
    def test_wrong_direction_observed_not_classified(self):
        p=self.inspector();p.consume(seg(100,flags=2,direction='client_to_server'))
        p.consume(seg(101,framed(any_body('jsq')),direction='client_to_server'))
        self.assertEqual(p.finish().direction_mismatches,1)
    def test_new_version_cannot_autopromote(self):
        p=self.inspector('Dofus 9.9.9.9');p.consume(seg(100,flags=2));p.consume(seg(101,framed(any_body())))
        self.assertEqual(p.finish().status,'UNSUPPORTED_BUILD_OBSERVATION_ONLY')
    def test_missing_syn_quarantines_evidence_readiness(self):
        p=self.inspector();p.consume(seg(101,framed(any_body())))
        r=p.finish();self.assertEqual(r.unanchored_streams,1)
        self.assertEqual(r.framed_messages,0)
        self.assertEqual(r.status,'INCOMPLETE_EVIDENCE_OBSERVATION_ONLY')
    def test_gap_blocks_continuation_in_generation(self):
        p=self.inspector();p.consume(seg(100,flags=2))
        p.consume(seg(102,framed(any_body())))
        p.consume(seg(101,framed(any_body())))
        r=p.finish();self.assertEqual(r.quarantined_streams,1);self.assertEqual(r.framed_messages,0)
    def test_identical_retransmission_does_not_duplicate_events(self):
        p=self.inspector();packetbody=framed(any_body())
        p.consume(seg(100,flags=2));p.consume(seg(101,packetbody));p.consume(seg(101,packetbody))
        self.assertEqual(p.finish().framed_messages,1)
    def test_partial_frame_at_reconnect_stays_failed(self):
        p=self.inspector();p.consume(seg(100,flags=2));p.consume(seg(101,framed(any_body())[:-2]))
        p.consume(seg(300,flags=2));p.consume(seg(301,framed(any_body())))
        r=p.finish();self.assertEqual(r.framed_messages,1)
        self.assertEqual(r.quarantined_streams,1)
        self.assertEqual(r.status,'INCOMPLETE_EVIDENCE_OBSERVATION_ONLY')
    def test_capture_source_restart_requires_new_syn(self):
        p=self.inspector()
        p.consume_poll(CapturePoll('old',(seg(100,flags=2),seg(101,framed(any_body()))),0,False,False,'AVAILABLE_CLEAN'))
        p.consume_poll(CapturePoll('new',(seg(101,framed(any_body())),),0,False,True,'AVAILABLE_CLEAN'))
        r=p.finish();self.assertEqual(r.framed_messages,1)
        self.assertTrue(r.packet_loss_reported)
        self.assertGreaterEqual(r.quarantined_streams,1)
        self.assertEqual(r.status,'INCOMPLETE_EVIDENCE_OBSERVATION_ONLY')
    def test_same_source_multiple_poll_batches_retains_stream(self):
        p=self.inspector();body=framed(any_body());cut=5
        p.consume_poll(CapturePoll('same',(seg(100,flags=2),seg(101,body[:cut])),0,False,False,'AVAILABLE_CLEAN'))
        p.consume_poll(CapturePoll('same',(seg(101+cut,body[cut:]),),0,False,True,'AVAILABLE_CLEAN'))
        self.assertEqual(p.finish().framed_messages,1)
    def test_new_syn_cannot_erase_prior_quarantine(self):
        p=self.inspector();p.consume(seg(100,flags=2));p.consume(seg(102,framed(any_body())))
        p.consume(seg(1000,flags=2));p.consume(seg(1001,framed(any_body())))
        r=p.finish();self.assertEqual(r.quarantined_streams,1);self.assertEqual(r.framed_messages,1)
        self.assertEqual(r.status,'INCOMPLETE_EVIDENCE_OBSERVATION_ONLY')
    def test_incomplete_end_of_capture_not_treated_complete(self):
        p=self.inspector();p.consume(seg(100,flags=2));p.consume(seg(101,framed(any_body())[:-3]))
        r=p.finish();self.assertEqual(r.quarantined_streams,1);self.assertEqual(r.framed_messages,0)
    def test_capture_loss_visible_without_erasing_message_classification(self):
        p=self.inspector();batch=CapturePoll('gen-1',(seg(100,flags=2),seg(101,framed(any_body()))),2,True,True,'AVAILABLE_DROPPED')
        p.consume_poll(batch)
        r=p.finish();self.assertTrue(r.packet_loss_reported)
        self.assertEqual(r.framed_messages,1)
        self.assertEqual(r.status,'INCOMPLETE_EVIDENCE_OBSERVATION_ONLY')
    def test_unknown_driver_visibility_is_not_certified(self):
        p=self.inspector();p.consume_poll(CapturePoll('gen-1',(),0,False,True,'UNKNOWN'))
        self.assertTrue(p.finish().packet_loss_reported)
    def test_observer_bundle_contains_no_payload(self):
        obs=self.observer();p=self.inspector(observer=obs)
        p.consume(seg(100,flags=2));p.consume(seg(101,framed(any_body(payload=b'SECRET_NETWORK_PAYLOAD'))))
        report=p.finish();self.assertEqual(report.framed_messages,1)
        bundle=obs.export_incident('PROTOCOL_TEST',boundary='protocol.inspect')
        with zipfile.ZipFile(bundle) as z:
            contents=b'\n'.join(z.read(x) for x in z.namelist())
        self.assertNotIn(b'SECRET_NETWORK_PAYLOAD',contents)
        self.assertNotIn(b'connection-1',contents)
    def test_synthetic_pcapng_replay(self):
        data=framed(any_body())
        self.path=self.root/'synthetic.pcapng'
        self.path.write_bytes(pcapng(packet(100,flags=2,data=b'',reverse=True),packet(101,flags=0x18,data=data,reverse=True)))
        report=inspect_protocol_pcapng(self.path,root=ROOT,ports=(40400,),build='Dofus 3.7.10.10')
        self.assertEqual(report['protocol']['framed_messages'],1)
        self.assertFalse(report['protocol']['gameplay_capabilities_certified'])
        self.assertFalse(report['physical_input_sent'])
    def test_command_refuses_ports_without_override(self):
        obs=self.observer()
        with self.assertRaisesRegex(RuntimeError,'CAPTURE_PORTS_NOT_CONFIGURED'):
            _command('protocol-audit',obs,['synthetic.pcapng','Dofus 3.7.10.10'])
    def test_wire_demo_safe(self):
        result=synthetic_wire_demo(root=ROOT)
        self.assertEqual(result['observed_names'],['jsq'])
        self.assertFalse(result['live_ready'])
    def test_invalid_wire_contract_rejects_payload_type(self):
        with self.assertRaisesRegex(ValueError,'PROTOCOL_BODY_INVALID'):
            WireMessage('server_to_client','jsq','secret')
    def test_many_flow_keys_limit(self):
        p=self.inspector()
        for k in range(64):p.consume(seg(100,flags=2,flow=f'flow{k}'))
        with self.assertRaisesRegex(ValueError,'PROTOCOL_FLOW_LIMIT'):p.consume(seg(100,flags=2,flow='flow64'))

if __name__=='__main__':unittest.main()
