"""Offline fault injection for the optional Windows capture seam."""
import unittest
from unittest.mock import patch
from anka_contracts.capture import CapturedTcpSegment, CapturePoll
from anka_capture.live import BoundedSegmentQueue, LiveCaptureAudit
from anka_capture.windows_live import WindowsLiveCapture, capture_bounded_sample
from anka_capture.windows_flows import TcpEndpoint,correlate_flows,WindowsTcpOwnership


def seg(seq=1, payload=b'hello', no=1, flags=0, flow='opaque-flow'):
    return CapturedTcpSegment(flow,'client_to_server',seq,payload,no,flags)

class TestLiveQueue(unittest.TestCase):
    def test_count_overflow_is_not_silent(self):
        q=BoundedSegmentQueue(source_generation='x',max_segments=1)
        self.assertTrue(q.push(seg()))
        self.assertFalse(q.push(seg(2,no=2)))
        p=q.poll(max_segments=100,timeout_seconds=0)
        self.assertEqual(p.dropped,1)
        self.assertTrue(p.overflowed)
        self.assertFalse(p.live_loss_accounting_complete)
        self.assertEqual(len(p.segments),1)
        self.assertEqual(q.stats().dropped_total,1)
        self.assertEqual(q.poll(max_segments=1,timeout_seconds=0).dropped,0)
        self.assertEqual(q.stats().dropped_total,1)
    def test_byte_overflow(self):
        q=BoundedSegmentQueue(source_generation='x',max_bytes=5)
        self.assertFalse(q.push(seg(payload=b'123456')))
        self.assertEqual(q.poll(max_segments=1,timeout_seconds=0).dropped,1)
    def test_closed_queue_exhaustion(self):
        q=BoundedSegmentQueue(source_generation='x')
        q.push(seg());q.close()
        first=q.poll(max_segments=1,timeout_seconds=0)
        self.assertTrue(first.exhausted)  # final segment delivered with source exhausted
        self.assertEqual(len(first.segments),1)
        self.assertTrue(q.poll(max_segments=1,timeout_seconds=0).exhausted)
        self.assertFalse(q.push(seg(no=2)))
        self.assertEqual(q.stats().dropped_total,1)
    def test_malformed_segment_is_counted(self):
        q=BoundedSegmentQueue(source_generation='x')
        self.assertFalse(q.push(None))
        self.assertEqual(q.stats().invalid_total,1)
    def test_arguments_rejected(self):
        q=BoundedSegmentQueue(source_generation='x')
        for n,t in ((0,0),(4097,0),(1,-1),(1,20)):
            with self.subTest(n=n,t=t),self.assertRaises(ValueError):q.poll(max_segments=n,timeout_seconds=t)
        with self.assertRaises(ValueError):BoundedSegmentQueue(source_generation='x',max_segments=99999)
    def test_driver_loss_visibility_is_not_falsely_clean(self):
        p=CapturePoll('x',(),0,False,False)
        self.assertTrue(p.transport_evidence_complete)
        self.assertFalse(p.live_loss_accounting_complete)
        self.assertTrue(CapturePoll('x',(),0,False,False,'AVAILABLE_CLEAN').live_loss_accounting_complete)

class TestPollAudit(unittest.TestCase):
    def test_cumulative_loss_survives_later_clean_poll(self):
        a=LiveCaptureAudit()
        a.observe(CapturePoll('x',(seg(no=1),),2,True,False))
        a.observe(CapturePoll('x',(),0,False,True))
        r=a.receipt()
        self.assertEqual(r['queue_dropped'],2)
        self.assertEqual(r['status'],'LOSS_DETECTED')
        self.assertEqual(r['driver_drop_visibility'],'UNKNOWN')
        self.assertTrue(r['source_exhausted'])
        self.assertNotIn('hello',str(r))
    def test_generation_swap_rejected(self):
        a=LiveCaptureAudit();a.observe(CapturePoll('x',(),0,False,False))
        with self.assertRaisesRegex(ValueError,'CAPTURE_GENERATION_CHANGED'):
            a.observe(CapturePoll('y',(),0,False,False))
    def test_subsequent_poll_after_final_rejected(self):
        a=LiveCaptureAudit();a.observe(CapturePoll('x',(),0,False,True))
        with self.assertRaisesRegex(ValueError,'CAPTURE_AFTER_EXHAUSTION'):
            a.observe(CapturePoll('x',(),0,False,True))
    def test_earlier_gap_survives_reconnect(self):
        a=LiveCaptureAudit()
        a.observe(CapturePoll('x',(seg(100,b'',1,2),seg(110,b'z',2)),0,False,False))
        a.observe(CapturePoll('x',(seg(500,b'',3,2),seg(501,b'new',4)),0,False,True))
        r=a.receipt();self.assertEqual(r['status'],'TRANSPORT_UNCERTAIN')
        self.assertEqual(r['transport']['reconnections'],1)
        self.assertEqual(r['transport']['unresolved_gap_directions'],1)

class FakeSniffer:
    def __init__(self,**kw):self.kw=kw;self.started=False;self.stopped=False
    def start(self):self.started=True
    def stop(self):self.stopped=True

class TestLiveBackend(unittest.TestCase):
    def source(self,**extra):
        return WindowsLiveCapture(interface='fake-npcap',server_ports=(40400,),
                                  require_windows=False,sniffer_factory=FakeSniffer,**extra)
    def test_read_only_ingress_and_direction(self):
        source=self.source();source.start()
        source.ingest_fields(src='192.0.2.5',dst='198.51.100.7',sport=55000,dport=40400,seq=100,flags=2,payload=b'')
        source.ingest_fields(src='198.51.100.7',dst='192.0.2.5',sport=40400,dport=55000,seq=200,flags=0,payload=b'safe')
        p=source.poll(max_segments=10,timeout_seconds=0)
        self.assertEqual(len(p.segments),2)
        self.assertEqual(p.segments[0].flow_id,p.segments[1].flow_id)
        self.assertEqual(p.segments[0].direction,'client_to_server')
        self.assertEqual(p.segments[1].direction,'server_to_client')
        self.assertNotIn('192.0.2.5',repr(p.segments))
        self.assertNotIn('safe',repr(p.segments))
        self.assertEqual(source.safe_stats()['physical_input_sent'],False)
        source.stop()
        self.assertTrue(source.poll(max_segments=10,timeout_seconds=0).exhausted)
    def test_fail_closed_when_ports_ambiguous(self):
        source=self.source();source.start()
        source.ingest_fields(src='a',dst='b',sport=40400,dport=40400,seq=10,flags=0,payload=b'secret')
        p=source.poll(max_segments=5,timeout_seconds=0)
        self.assertEqual(p.dropped,1)
        self.assertFalse(p.segments)
        source.stop()
    def test_missing_source_dependency_fails_cleanly(self):
        source=WindowsLiveCapture(interface='fake-npcap',server_ports=(40400,),require_windows=False,
                                  sniffer_factory=lambda **kw: (_ for _ in ()).throw(OSError('sensitive device path')))
        with self.assertRaisesRegex(RuntimeError,'LIVE_CAPTURE_START_FAILED'):source.start()
        self.assertTrue(source.queue.stats().source_closed)
    def test_bad_interface_rejected(self):
        with self.assertRaisesRegex(ValueError,'CAPTURE_INTERFACE_INVALID'):
            WindowsLiveCapture(interface='\n',server_ports=(40400,),require_windows=False,sniffer_factory=FakeSniffer)
    def test_randomized_flow_tokens(self):
        a=self.source();b=self.source();a.start();b.start()
        for source in (a,b):
            source.ingest_fields(src='127.0.0.1',dst='127.0.0.2',sport=5555,dport=40400,seq=0,flags=2,payload=b'')
        self.assertNotEqual(a.poll(max_segments=2,timeout_seconds=0).segments[0].flow_id,
                            b.poll(max_segments=2,timeout_seconds=0).segments[0].flow_id)
        a.stop();b.stop()
    def test_source_cannot_restart(self):
        s=self.source();s.start();s.stop()
        with self.assertRaises(RuntimeError):s.start()
    def test_no_raw_data_in_receipt(self):
        s=self.source();s.start()
        s.ingest_fields(src='192.0.2.1',dst='192.0.2.2',sport=55000,dport=40400,seq=0,flags=0,payload=b'SECRETPAYLOAD')
        s.stop()
        r=s.safe_stats()
        self.assertNotIn('192.0.2.',str(r))
        self.assertNotIn('SECRET',str(r))
    def test_sample_end_to_end_with_fake_source(self):
        s=self.source()
        receipt=capture_bounded_sample(interface='fake-npcap',server_ports=(40400,),duration_seconds=1,
                                       source=s,require_windows=False)
        self.assertEqual(receipt['selected_segments'],0)
        self.assertEqual(receipt['status'],'UNCERTIFIED')
        self.assertFalse(receipt['account_binding_verified'])
        self.assertFalse(receipt['physical_input_sent'])
        self.assertTrue(receipt['source_exhausted'])

class TestFlowHints(unittest.TestCase):
    def test_unique_match_still_not_attestation(self):
        key=('192.0.2.5',55000,'198.51.100.7',40400)
        row=TcpEndpoint(*key,123,5)
        r=correlate_flows({'opaque':key},(row,),{123:'process_gen_1'})
        self.assertEqual(r['counts']['PROVISIONAL'],1)
        self.assertFalse(r['account_binding_verified'])
    def test_ambiguous_and_unmatched(self):
        key=('192.0.2.5',55000,'198.51.100.7',40400)
        rows=(TcpEndpoint(*key,123,5),TcpEndpoint(*key,124,5))
        r=correlate_flows({'a':key,'b':('127.0.0.1',1,'127.0.0.2',2)},rows,{123:'g1',124:'g2'})
        self.assertEqual(r['counts']['AMBIGUOUS'],1)
        self.assertEqual(r['counts']['UNMATCHED'],1)
    def test_windows_source_rejects_non_windows(self):
        import os
        if os.name!='nt':
            with self.assertRaisesRegex(RuntimeError,'TCP_OWNER_TABLE_WINDOWS_ONLY'):
                WindowsTcpOwnership().snapshot()

class TestLiveCommandPolicy(unittest.TestCase):
    def test_live_command_requires_configured_ports(self):
        import subprocess,sys
        from anka_app.cli import ROOT
        p=subprocess.run([sys.executable,'-m','anka_app.cli','capture-live'],cwd=ROOT,
                         capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,40)
        self.assertIn('ANKA_FAILURE=CAPTURE_PORTS_NOT_CONFIGURED',p.stdout)
        self.assertIn('ANKA_BUNDLE=',p.stdout)
    def test_capture_start_still_blocked(self):
        import subprocess,sys
        from anka_app.cli import ROOT
        p=subprocess.run([sys.executable,'-m','anka_app.cli','start'],cwd=ROOT,
                         capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,40)
        self.assertIn('ANKA_FAILURE=START_WINDOWS_REQUIRED',p.stdout)
    def test_interface_settings_accept_null_and_reject_control_chars(self):
        import json,tempfile
        from pathlib import Path
        from anka_app.configuration import load_user_config,ConfigurationError
        from anka_app.cli import ROOT
        obj=json.loads((ROOT/'config/user.json').read_text())
        obj.setdefault('capture',{})
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'user.json'
            obj['capture']['interface']='\\Device\\NPF_{SAMPLE}'
            obj['capture']['duration_seconds']=10
            p.write_text(json.dumps(obj))
            self.assertEqual(load_user_config(p).capture.duration_seconds,10)
            obj['capture']['interface']='bad\niface'
            p.write_text(json.dumps(obj))
            with self.assertRaisesRegex(ConfigurationError,'INVALID_CAPTURE_INTERFACE'):
                load_user_config(p)
            obj['capture']['interface']=None
            obj['capture']['duration_seconds']=61
            p.write_text(json.dumps(obj))
            with self.assertRaisesRegex(ConfigurationError,'INVALID_INTEGER'):
                load_user_config(p)
