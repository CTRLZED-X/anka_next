"""P29 independent oracle and hostile-packet comparisons (never live authority)."""
from __future__ import annotations
import io
import json
import tempfile
import shutil
import unittest
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from unittest.mock import patch

from tests.capture_fixtures import packet, pcapng
from tests.test_protocol_wire import framed, any_body
from tests.test_semantic_p7 import jtk
from anka_capture.pcapng import read_pcapng_tcp_segments
from anka_protocol.adapters.historical_semantic import BUILD, ADAPTER_ID, HistoricalSemanticAdapter
from anka_protocol.evidence_intake import IntakeRejected, inspect_evidence_pack
from anka_app.protocol_evidence_compare import compare_pack
from anka_app.protocol_updates import audit_staged_updates
from anka_app.cli import ROOT


def _payload(): return framed(any_body('jtk', jtk(actor=777)))


def archive(*,expected_ap=9,build=BUILD,adapter=ADAPTER_ID,selector=True,ports=True,
            append_gap=False, extra_message=False, bad_schema=False,
            forge_source=False, actor_only=False):
    payload=_payload()
    frames=[packet(seq=100,flags=2,data=b'',reverse=True),
            packet(seq=101,flags=0x18,data=payload,reverse=True)]
    if extra_message:
        frames.append(packet(seq=101+len(payload),flags=0x18,data=payload,reverse=True))
    if append_gap:
        frames.append(packet(seq=101+len(payload)+5,flags=0x18,data=b'garbage',reverse=True))
    cap=pcapng(*frames)
    raw_segments=read_pcapng_tcp_segments(Path('ignored'),server_ports={40400},raw=cap)
    digest=sha256(raw_segments[1].flow_id.encode('utf8')).hexdigest()
    oracle={'schema':1,'observations':[{'id':'obs1','capability':'actor_ap',
            'expected':({'actor_id':777} if actor_only else {'actor_id':777,'ap':expected_ap})}]}
    files={'captures/evidence.pcapng':cap,
           'oracles/check.json':json.dumps(oracle).encode(),
           'witness/proof.png':b'\x89PNG\r\n\x1a\n' + b'\0'*12}
    manifest={'schema':1,'package_kind':'ANKA_PROTOCOL_EVIDENCE',
              'protocol_build':build,'adapter_id':adapter,
              'sources':[{'path':p,'sha256':sha256(v).hexdigest(),
                'kind':'pcapng' if p.endswith('.pcapng') else 'oracle' if p.endswith('.json') else 'screenshot'}
                for p,v in files.items()],
              'cases':[{'id':'case1','capability':'actor_ap',
                        'capture':'captures/evidence.pcapng','oracle':'oracles/check.json',
                        'oracle_id':'obs1','account_role':'leader','witness':'witness/proof.png'}]}
    if ports: manifest['server_ports']=[40400]
    if selector:
        manifest['cases'][0]['selector']={
            'packet_number':2, 'message_index':0,
            'wire_name':'jtk' if not bad_schema else 'jti',
            'direction':'server_to_client','transport_generation':1,
            'flow_digest':'f'*64 if forge_source else digest}
    files['manifest.json']=json.dumps(manifest,sort_keys=True).encode()
    out=io.BytesIO()
    with ZipFile(out,'w',ZIP_DEFLATED) as z:
        for k,v in files.items(): z.writestr(k,v)
    return out.getvalue()


class P29Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
    def run_pack(self,raw):
        file=self.root/'evidence.zip';file.write_bytes(raw)
        return compare_pack(file, root=ROOT)
    def test_exact_historical_comparison_not_certified(self):
        report=self.run_pack(archive())
        self.assertEqual(report['status'],'RESEARCH_COMPARISON_MATCHED_NOT_CERTIFIED')
        self.assertEqual(report['matched_cases'],1)
        self.assertFalse(report['live_semantic_certified'])
        self.assertFalse(report['physical_input_sent'])
        self.assertEqual(report['canonical_commits'],0)
        self.assertFalse(report['adapter_activated'])
        self.assertNotIn('777',str(report))
        self.assertNotIn('captures/evidence',str(report))
    def test_explicit_field_mismatch(self):
        report=self.run_pack(archive(expected_ap=11))
        self.assertEqual(report['status'],'RESEARCH_COMPARISON_BLOCKED')
        self.assertEqual(report['case_results'][0]['status'],'FIELD_MISMATCH')
        self.assertEqual(report['case_results'][0]['mismatch_fields'],['ap'])
        self.assertNotIn('11',str(report))
    def test_current_build_not_falsely_reused(self):
        r=self.run_pack(archive(build='Dofus 3.7.11.11',adapter='dofus_new_candidate'))
        self.assertEqual(r['status'],'ADAPTER_UNAVAILABLE_FOR_EXACT_BUILD')
        self.assertFalse(r['live_semantic_certified'])
    def test_same_build_wrong_adapter_rejected(self):
        self.assertEqual(self.run_pack(archive(adapter='unreviewed_new_adapter'))['status'],
                         'ADAPTER_UNAVAILABLE_FOR_EXACT_BUILD')
    def test_missing_selector_not_autoguessed(self):
        self.assertEqual(self.run_pack(archive(selector=False))['status'],'EXACT_SOURCE_SELECTOR_REQUIRED')
    def test_no_port_not_guessed(self):
        self.assertEqual(self.run_pack(archive(ports=False))['status'],'CAPTURE_PORTS_UNSPECIFIED')
    def test_wrong_wire_selector(self):
        r=self.run_pack(archive(bad_schema=True))
        self.assertEqual(r['case_results'][0]['status'],'SOURCE_MESSAGE_NOT_FOUND')
    def test_flow_digest_prevents_cross_flow_match(self):
        r=self.run_pack(archive(forge_source=True))
        self.assertEqual(r['case_results'][0]['status'],'SOURCE_MESSAGE_NOT_FOUND')
    def test_transport_gap_invalidates_early_valid_fact(self):
        self.assertEqual(self.run_pack(archive(append_gap=True))['status'],
                         'TRANSPORT_OR_FRAMING_UNPROVEN')
    def test_duplicate_messages_do_not_make_selector_ambiguous(self):
        r=self.run_pack(archive(extra_message=True))
        self.assertEqual(r['matched_cases'],1)
    def test_actor_only_oracle_not_vacuously_accepted(self):
        r=self.run_pack(archive(actor_only=True))
        self.assertEqual(r['case_results'][0]['status'],'ORACLE_FIELDS_NOT_COMPARABLE')
    def test_pack_selector_type_validation(self):
        raw=archive()
        with ZipFile(io.BytesIO(raw)) as z:
            files={name:z.read(name) for name in z.namelist()}
        manifest=json.loads(files['manifest.json'])
        manifest['cases'][0]['selector']['packet_number']=True
        files['manifest.json']=json.dumps(manifest).encode()
        out=io.BytesIO()
        with ZipFile(out,'w') as z:
            for name,contents in files.items():z.writestr(name,contents)
        p=self.root/'bad.zip';p.write_bytes(out.getvalue())
        with self.assertRaises(IntakeRejected) as raised:inspect_evidence_pack(p)
        self.assertEqual(str(raised.exception),'P28_SELECTOR_INVALID')
    def test_setup_pipeline_reports_comparison(self):
        staging=self.root/'protocol_updates';staging.mkdir()
        shutil.copytree(ROOT/'reference/protocol', self.root/'reference/protocol')
        (staging/'update.zip').write_bytes(archive())
        r=audit_staged_updates(self.root)
        self.assertEqual(r['packs'][0]['semantic_comparison']['matched_cases'],1)
        self.assertFalse(r['adapter_activated'])
    def test_replaced_archive_between_intake_and_comparison(self):
        raw=archive()
        p=self.root/'evidence.zip';p.write_bytes(raw)
        true_inspect=inspect_evidence_pack
        def replace_after_inspection(path):
            report=true_inspect(path)
            Path(path).write_bytes(archive(expected_ap=90))
            return report
        with patch('anka_app.protocol_evidence_compare.inspect_evidence_pack',replace_after_inspection):
            r=compare_pack(p,root=ROOT)
        self.assertEqual(r['status'],'PACK_CHANGED_DURING_COMPARISON')
    def test_forged_decoder_source_is_rejected(self):
        original=HistoricalSemanticAdapter.decode
        class Forged(HistoricalSemanticAdapter):
            def decode(self,message,*,context=None):
                from dataclasses import replace
                response=original(self,message,context=context)
                return replace(response,candidates=tuple(replace(d,evidence=replace(d.evidence,packet_number=999))
                                                         for d in response.candidates))
        p=self.root/'evidence.zip';p.write_bytes(archive())
        r=compare_pack(p,root=ROOT,adapter_factory=Forged)
        self.assertEqual(r['status'],'DECODED_SOURCE_PROVENANCE_INVALID')
    def test_forged_decoder_status_does_not_pass(self):
        original=HistoricalSemanticAdapter.decode
        class ForgedStatus(HistoricalSemanticAdapter):
            def decode(self, message, *, context=None):
                from dataclasses import replace
                response=original(self,message,context=context)
                return replace(response,status='BUILD_MISMATCH')
        p=self.root/'evidence.zip';p.write_bytes(archive())
        self.assertEqual(compare_pack(p,root=ROOT,adapter_factory=ForgedStatus)['status'],
                         'TRANSPORT_OR_FRAMING_UNPROVEN')

    def test_port_boolean_is_rejected_by_intake(self):
        raw=archive()
        with ZipFile(io.BytesIO(raw)) as z:files={n:z.read(n) for n in z.namelist()}
        man=json.loads(files['manifest.json'])
        man['server_ports']=[True]
        files['manifest.json']=json.dumps(man).encode()
        p=self.root/'bad.zip'
        out=io.BytesIO()
        with ZipFile(out,'w') as z:
            for n,d in files.items():z.writestr(n,d)
        p.write_bytes(out.getvalue())
        with self.assertRaises(IntakeRejected) as exc:inspect_evidence_pack(p)
        self.assertEqual(str(exc.exception),'P28_PORTS_INVALID')

    def test_malformed_selected_capture_rejected_even_if_p28_intake_passes(self):
        p=self.root/'evidence.zip'
        raw=archive()
        with ZipFile(io.BytesIO(raw)) as z:files={n:z.read(n) for n in z.namelist()}
        man=json.loads(files['manifest.json'])
        files['captures/evidence.pcapng']=b'\x0a\x0d\x0d\x0a' + b'\0'*20
        man['sources'][0]['sha256']=sha256(files['captures/evidence.pcapng']).hexdigest()
        files['manifest.json']=json.dumps(man).encode()
        out=io.BytesIO()
        with ZipFile(out,'w') as z:
            for n,d in files.items(): z.writestr(n,d)
        p.write_bytes(out.getvalue())
        self.assertEqual(compare_pack(p,root=ROOT)['status'],'CAPTURE_MALFORMED_OR_UNSUPPORTED')
