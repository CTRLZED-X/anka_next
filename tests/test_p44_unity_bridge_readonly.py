"""P44 manually authored source-independent positive/negative bridge oracles."""
from __future__ import annotations
import copy
import hashlib
import json
import socket
import threading
import unittest
from pathlib import Path
from anka_client.api import inspect_reference_bridge
from anka_client.unity_bridge import (ReadOnlyBridgeInspector, LocalLoopbackBridgeReader,
                                       BridgeTransportRejected, MAX_REPLY_BYTES)
from anka_contracts.client import WindowObservation
from anka_app.cli import ROOT

PORT=8765
WINDOW=WindowObservation(33,2020,123456000,'Dofus.exe','Dofus',1280,649,96,False)


def good_health():
    return {'processId':2020,'processStartTime':123456000,'bridgePort':PORT,
            'source':'unity_bridge','available':True,'sourceVerified':True,
            'status':'MAP_COORDINATES_READY','loadedMapId':42042,'mapGeneration':3,
            'coordinateGeneration':5,'sourceClientWidth':1280,'sourceClientHeight':649,
            'projectionSignature':'p','windowFingerprint':'w','cameraFingerprint':'c','cellGeometryFingerprint':'g'}


def good_map():
    cells=[{'cellId':i,'clientX':i % 1280,'clientY':i // 2,
            'projectable':True,'insideCameraViewport':True,'sourceVerified':True} for i in range(560)]
    return {'status':'MAP_COORDINATES_READY','mapId':42042,'mapGeneration':3,
            'coordinateGeneration':5,'sourceVerified':True,'sourceClientWidth':1280,
            'sourceClientHeight':649,'totalMapCells':560,'projectableCellCount':560,
            'generatedCoordinateCount':560,
            'projectionSignature':'p','windowFingerprint':'w','cameraFingerprint':'c','cellGeometryFingerprint':'g',
            'cells':cells}


class FakeBridge:
    def __init__(self, health=None, coords=None, health2=None):
        self.health=good_health() if health is None else health
        self.coords=good_map() if coords is None else coords
        self.health2=health2
        self.calls=[]
    def get_json(self, port, route):
        self.calls.append((port,route))
        if route=='/health':
            n=sum(c[1]=='/health' for c in self.calls)
            return copy.deepcopy(self.health if n==1 or self.health2 is None else self.health2)
        if route=='/coordinates':return copy.deepcopy(self.coords)
        raise AssertionError('unexpected route')


class P44ReadOnlyContractTests(unittest.TestCase):
    def test_process_evidence_is_not_character_identity(self):
        reader=FakeBridge()
        o=inspect_reference_bridge(WINDOW,PORT,reader)
        self.assertEqual((o.status,o.reason),('PROCESS_MATCHED','WINDOW_GENERATION_MATCH_ONLY'))
        self.assertTrue(o.window_process_matched)
        self.assertFalse(o.character_identity_verified)
        self.assertFalse(o.input_certified)
        self.assertEqual(reader.calls,[(PORT,'/health')])

    def test_projection_is_research_only_and_sorted(self):
        reader=FakeBridge()
        o=inspect_reference_bridge(WINDOW,PORT,reader,map_id=42042)
        self.assertEqual(o.status,'RESEARCH_PROJECTION_ONLY')
        self.assertEqual(len(o.cells),560)
        self.assertFalse(o.live_certified)
        self.assertFalse(o.input_certified)
        self.assertEqual(reader.calls,[(PORT,'/health'),(PORT,'/coordinates'),(PORT,'/health')])

    def test_wrong_pid_and_reused_process_generation_block(self):
        for key,newval in [('processId',2021),('processStartTime',123456001),('bridgePort',PORT+1)]:
            with self.subTest(key=key):
                health=good_health();health[key]=newval
                o=inspect_reference_bridge(WINDOW,PORT,FakeBridge(health))
                self.assertEqual(o.status,'BLOCKED')
                self.assertIn('GENERATION_MISMATCH',o.reason)

    def test_generation_change_during_probe_blocks(self):
        for field in ('coordinateGeneration','mapGeneration','projectionSignature','cellGeometryFingerprint'):
            with self.subTest(field=field):
                h=good_health();h[field]=6 if 'Generation' in field else 'changed'
                o=ReadOnlyBridgeInspector(FakeBridge(health2=h)).inspect_coordinates(WINDOW,PORT,map_id=42042)
                self.assertEqual((o.status,o.reason),('BLOCKED','BRIDGE_GENERATION_CHANGED_DURING_READ'))

    def test_incomplete_and_wrong_map_rejected(self):
        for key,val,expected in [('mapId',42043,'COORDINATE_MAP_MISMATCH'),
                                  ('coordinateGeneration',4,'COORDINATE_GENERATION_MISMATCH'),
                                  ('sourceVerified',False,'COORDINATE_SOURCE_UNVERIFIED'),
                                  ('status','COORDINATE_NOT_READY','BRIDGE_COORDINATES_NOT_READY'),
                                  ('sourceClientWidth',1279,'COORDINATE_WINDOW_SIZE_MISMATCH'),
                                  ('generatedCoordinateCount',559,'COORDINATE_COUNT_MISMATCH'),
                                  ('cameraFingerprint','different','COORDINATE_PROJECTION_SIGNATURE_MISMATCH')]:
            with self.subTest(key=key):
                coords=good_map();coords[key]=val
                o=ReadOnlyBridgeInspector(FakeBridge(coords=coords)).inspect_coordinates(WINDOW,PORT,map_id=42042)
                self.assertEqual((o.status,o.reason),('BLOCKED',expected))

    def test_reject_partial_map_claiming_ready(self):
        coords=good_map();coords['cells']=coords['cells'][:-1]
        o=ReadOnlyBridgeInspector(FakeBridge(coords=coords)).inspect_coordinates(WINDOW,PORT,map_id=42042)
        self.assertEqual(o.status,'BLOCKED')

    def test_wrong_expected_map_and_generation_rejected(self):
        self.assertEqual(inspect_reference_bridge(WINDOW,PORT,FakeBridge(),map_id=42043).status,'BLOCKED')
        self.assertEqual(ReadOnlyBridgeInspector(FakeBridge()).inspect_coordinates(WINDOW,PORT,map_id=42042,expected_generation=2).reason,'BRIDGE_STALE_MAP_GENERATION')

    def test_invalid_position_and_duplicate_cells_rejected(self):
        cases=[('cellId',560),('cellId',1),('clientX',1280),('clientY',649),('clientX',True),('sourceVerified',1)]
        for key,value in cases:
            with self.subTest(key=key,value=value):
                c=good_map();c['cells'][0][key]=value
                o=ReadOnlyBridgeInspector(FakeBridge(coords=c)).inspect_coordinates(WINDOW,PORT,map_id=42042)
                self.assertEqual(o.status,'BLOCKED')

    def test_missing_proof_while_probe_still_process_match_only(self):
        h=good_health();h['loadedMapId']=None
        self.assertEqual(ReadOnlyBridgeInspector(FakeBridge(health=h)).inspect_identity(WINDOW,PORT).status,'PROCESS_MATCHED')
        self.assertEqual(ReadOnlyBridgeInspector(FakeBridge(health=h)).inspect_coordinates(WINDOW,PORT,map_id=42042).status,'BLOCKED')

    def test_minimized_and_stale_window_dimensions_rejected(self):
        w=WindowObservation(33,2020,123456000,'Dofus.exe','Dofus',1280,649,96,True)
        self.assertEqual(ReadOnlyBridgeInspector(FakeBridge()).inspect_coordinates(w,PORT,map_id=42042).reason,'WINDOW_NOT_USABLE')
        w=WindowObservation(33,2020,123456000,'Dofus.exe','Dofus',1300,649,96,False)
        self.assertEqual(ReadOnlyBridgeInspector(FakeBridge()).inspect_coordinates(w,PORT,map_id=42042).reason,'BRIDGE_WINDOW_SIZE_MISMATCH')

    def test_bad_health_types_never_claim_proof(self):
        for k,v in [('available','true'),('source','not-unity'),('processId',True),('bridgePort',0)]:
            with self.subTest(k=k):
                h=good_health();h[k]=v
                self.assertEqual(ReadOnlyBridgeInspector(FakeBridge(health=h)).inspect_identity(WINDOW,PORT).status,'BLOCKED')

    def test_read_failure_blocks(self):
        class Broken:
            def get_json(self,*_):raise BridgeTransportRejected('SIMULATED_DISCONNECT')
        self.assertEqual(ReadOnlyBridgeInspector(Broken()).inspect_coordinates(WINDOW,PORT,map_id=42042).status,'BLOCKED')

    def test_archived_bridge_hashes_match_and_no_extra_bats(self):
        data=json.loads((ROOT/'provenance/P44_native_bridge_source.json').read_text())
        self.assertEqual(data['mode'],'SOURCE_ONLY_NO_BUILD_NO_INSTALL_NO_INPUT')
        for item in data['files']:
            with self.subTest(path=item['path']):
                self.assertEqual(hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest(),item['sha256'])
                self.assertIsNot(item['legacy_provenance_matches'],False)
        self.assertEqual(sorted(p.name for p in ROOT.rglob('*.bat')),['setup.bat','start.bat']) if not list((ROOT/'tools').rglob('*.bat')) else self.assertEqual(sorted(p.name for p in ROOT.glob('*.bat')),['setup.bat','start.bat'])


class P44TransportContractTests(unittest.TestCase):
    def test_routes_ports_and_budget(self):
        reader=LocalLoopbackBridgeReader()
        for port,route in [(0,'/health'),(True,'/health'),(PORT,'/resolve'),(PORT,'http://evil/')]:
            with self.subTest(port=port,route=route):
                with self.assertRaises(BridgeTransportRejected):reader.get_json(port,route)
        with self.assertRaises(ValueError):LocalLoopbackBridgeReader(timeout_seconds=0)

    def test_real_loopback_http_json_with_duplicate_and_oversize_rejection(self):
        # Server in this test is intentionally separate from the app; GET only.
        def serve(payload):
            listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
            listener.bind(('127.0.0.1',0));listener.listen(1)
            port=listener.getsockname()[1]
            def worker():
                try:
                    listener.settimeout(3)
                    conn,_=listener.accept()
                    with conn:
                        conn.settimeout(3)
                        data=conn.recv(4096)
                        self.assertIn(b'GET /health HTTP/1.1',data)
                        body=payload
                        try:
                            conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body)).encode()+b'\r\nConnection: close\r\n\r\n'+body)
                        except (ConnectionResetError,BrokenPipeError):
                            # Expected when the bounded client rejects an oversized
                            # response and closes before the test server finishes.
                            pass
                finally:listener.close()
            thread=threading.Thread(target=worker,daemon=True);thread.start()
            return port,thread
        port,t=serve(b'{"ok":true}');self.assertEqual(LocalLoopbackBridgeReader().get_json(port,'/health'),{'ok':True});t.join(2)
        port,t=serve(b'{"ok":true,"ok":false}')
        with self.assertRaisesRegex(BridgeTransportRejected,'DUPLICATE_BRIDGE_JSON_FIELD'):
            LocalLoopbackBridgeReader().get_json(port,'/health')
        t.join(2)
        port,t=serve(b'x'*(MAX_REPLY_BYTES+1))
        with self.assertRaisesRegex(BridgeTransportRejected,'BRIDGE_REPLY_TOO_LARGE'):
            LocalLoopbackBridgeReader().get_json(port,'/health')
        t.join(2)

if __name__=='__main__':unittest.main()
