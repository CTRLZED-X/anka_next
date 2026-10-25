"""P30: independently expected synthetic wire layouts; zero current-client authority."""
from __future__ import annotations
import io
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from tests.capture_fixtures import packet, pcapng
from tests.test_protocol_wire import framed, any_body, v, pfield
from anka_capture.pcapng import read_pcapng_tcp_segments
from anka_protocol.adapters.declarative import (
    RecipeRejected, load_local_recipe, DeclarativeResearchAdapter,
)
from anka_contracts.protocol import WireMessage
from anka_app.protocol_evidence_compare import compare_pack
from anka_app.protocol_updates import audit_staged_updates
from anka_app.cli import ROOT

BUILD = 'Dofus 3.7.11.11'
ADAPTER = 'dofus_3_7_11_11_local_research'
WIRE = 'obscured_ap_2'


def recipe(*, wire=WIRE, resource='actor_ap', value_path=None, extra=None):
    r = {'wire_name': wire, 'direction': 'server_to_client', 'capability': resource,
         'actor_path': [5], 'value_path': value_path if value_path is not None else [9, 3]}
    if resource == 'actor_hp':
        r['maximum_path'] = [9, 4]
    if extra:
        r.update(extra)
    return {'schema': 1, 'source_role': 'LOCAL_REVIEWED_RESEARCH_ONLY',
            'protocol_build': BUILD, 'adapter_id': ADAPTER, 'rules': [r]}


def encode_recipe(root, mapping=None, *, wrong_hash=False, duplicate=False):
    mapping = mapping or recipe()
    directory = root / 'reference' / 'protocol' / 'research_adapters'
    directory.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(mapping, sort_keys=True).encode()
    (directory/'case.json').write_bytes(raw)
    record = {'protocol_build': BUILD, 'adapter_id': ADAPTER, 'file': 'case.json',
              'sha256': '0'*64 if wrong_hash else sha256(raw).hexdigest()}
    registry = {'schema':1,'source_role':'LOCAL_REVIEWED_RESEARCH_ONLY',
                'adapters':[record,record] if duplicate else [record]}
    (directory/'registry.json').write_text(json.dumps(registry))


def evidence(*, value=9, expected=9, name=WIRE, capture_gap=False, actor=777, build=BUILD, adapter=ADAPTER):
    wire_data = v((5<<3)|0) + v(actor) + pfield(9, v((3<<3)|0) + v(value) + v((4<<3)|0) + v(20))
    payload = framed(any_body(name, wire_data))
    blocks = [packet(seq=100, flags=2, data=b'', reverse=True),
              packet(seq=101, flags=0x18, data=payload, reverse=True)]
    if capture_gap:
        blocks.append(packet(seq=101+len(payload)+7, flags=0x18, data=b'GAP', reverse=True))
    cap = pcapng(*blocks)
    segments=read_pcapng_tcp_segments(Path('ignored'), server_ports={40400}, raw=cap)
    digest=sha256(segments[1].flow_id.encode()).hexdigest()
    sources = {'captures/fixture.pcapng':cap,
               'oracles/facts.json':json.dumps({'schema':1,'observations':[
                   {'id':'observed_ap','capability':'actor_ap','expected':{'actor_id':actor,'ap':expected}}
               ]}).encode(),
               'witness/evidence.png':b'\x89PNG\r\n\x1a\n'+b'\0'*12}
    manifest = {'schema':1,'package_kind':'ANKA_PROTOCOL_EVIDENCE',
                'protocol_build':build,'adapter_id':adapter,'server_ports':[40400],
                'sources':[{'path':p,'sha256':sha256(raw).hexdigest(),
                            'kind':'pcapng' if p.endswith('.pcapng') else 'oracle' if p.endswith('.json') else 'screenshot'}
                           for p,raw in sources.items()],
                'cases':[{'id':'observed_ap','capability':'actor_ap','capture':'captures/fixture.pcapng',
                          'oracle':'oracles/facts.json','oracle_id':'observed_ap',
                          'witness':'witness/evidence.png','account_role':'leader',
                          'selector':{'packet_number':2,'message_index':0,'wire_name':name,
                                      'direction':'server_to_client','transport_generation':1,
                                      'flow_digest':digest}}]}
    sources['manifest.json']=json.dumps(manifest,sort_keys=True).encode()
    io_obj=io.BytesIO()
    with ZipFile(io_obj,'w',ZIP_DEFLATED) as z:
        for k,data in sources.items():z.writestr(k,data)
    return io_obj.getvalue()


class DeclarativeResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        shutil.copytree(ROOT/'reference/protocol',self.root/'reference/protocol')
        encode_recipe(self.root)

    def compare(self, data=None):
        p=self.root/'update.zip';p.write_bytes(data or evidence())
        return compare_pack(p,root=self.root)

    def test_new_build_exact_match_research_only(self):
        r=self.compare()
        self.assertEqual(r['status'],'RESEARCH_COMPARISON_MATCHED_NOT_CERTIFIED')
        self.assertEqual(r['matched_cases'],1)
        self.assertFalse(r['live_semantic_certified'])
        self.assertFalse(r['adapter_activated'])
        self.assertFalse(r['physical_input_sent'])
        self.assertEqual(r['canonical_commits'],0)
        self.assertNotIn('777',str(r))

    def test_new_build_field_mismatch_clearly_reported(self):
        r=self.compare(evidence(expected=11))
        self.assertEqual(r['case_results'][0]['status'],'FIELD_MISMATCH')
        self.assertEqual(r['case_results'][0]['mismatch_fields'],['ap'])
        self.assertNotIn('11',str(r))

    def test_no_local_mapping_cannot_substitute_historical(self):
        (self.root/'reference/protocol/research_adapters/registry.json').unlink()
        self.assertEqual(self.compare()['status'],'ADAPTER_UNAVAILABLE_FOR_EXACT_BUILD')

    def test_pack_cannot_install_mapping(self):
        # No project-local recipe: importing even apparently valid new-build evidence
        # must not transform this status into semantic support.
        (self.root/'reference/protocol/research_adapters/registry.json').unlink()
        staging=self.root/'protocol_updates';staging.mkdir()
        (staging/'new_version.zip').write_bytes(evidence())
        r=audit_staged_updates(self.root)
        self.assertEqual(r['packs'][0]['semantic_comparison']['status'],'ADAPTER_UNAVAILABLE_FOR_EXACT_BUILD')
        self.assertFalse(r['adapter_activated'])

    def test_wrong_build_is_not_accepted(self):
        self.assertEqual(self.compare(evidence(build='Dofus 3.7.12.0'))['status'],
                         'ADAPTER_UNAVAILABLE_FOR_EXACT_BUILD')

    def test_wrong_adapter_id_is_not_accepted(self):
        self.assertEqual(self.compare(evidence(adapter='different_adapter'))['status'],
                         'ADAPTER_UNAVAILABLE_FOR_EXACT_BUILD')

    def test_hash_mismatch_blocks_even_matching_oracle(self):
        encode_recipe(self.root,wrong_hash=True)
        self.assertEqual(self.compare()['status'],'LOCAL_RESEARCH_RECIPE_REJECTED')

    def test_duplicate_registry_entries_block(self):
        encode_recipe(self.root,duplicate=True)
        self.assertEqual(self.compare()['status'],'LOCAL_RESEARCH_RECIPE_REJECTED')

    def test_layout_change_detected_as_schema_drift(self):
        encode_recipe(self.root,recipe(value_path=[9,7]))
        self.assertEqual(self.compare()['status'],'SEMANTIC_SCHEMA_DRIFT')

    def test_corrupt_capture_late_gap_wont_compare_initial_fact(self):
        self.assertEqual(self.compare(evidence(capture_gap=True))['status'],
                         'TRANSPORT_OR_FRAMING_UNPROVEN')

    def test_unknown_wire_cannot_be_guessed(self):
        r=self.compare(evidence(name='different_wire'))
        self.assertEqual(r['case_results'][0]['status'],'CAPABILITY_NOT_MAPPED_OR_CONTEXT_MISSING')

    def test_repeated_path_is_not_silently_first_match(self):
        adapter,_=load_local_recipe(self.root, build=BUILD,adapter_id=ADAPTER)
        body=v(40)+v(777)+v(40)+v(777)+pfield(9,v(24)+v(9))
        msg=WireMessage('server_to_client',WIRE,body,2,'safeflow',1,0)
        r=adapter.decode(msg)
        self.assertEqual(r.status,'QUARANTINED')
        self.assertEqual(r.failure_code,'P30_SCHEMA_OR_VALUE_DRIFT')
        self.assertFalse(r.candidates)

    def test_nested_field_wrong_type_rejected(self):
        adapter,_=load_local_recipe(self.root, build=BUILD,adapter_id=ADAPTER)
        body=v(40)+v(777)+v((9<<3)|0)+v(9)
        r=adapter.decode(WireMessage('server_to_client',WIRE,body,2,'flow',1,0))
        self.assertEqual(r.status,'QUARANTINED')

    def test_wrong_direction_quarantined(self):
        adapter,_=load_local_recipe(self.root,build=BUILD,adapter_id=ADAPTER)
        r=adapter.decode(WireMessage('client_to_server',WIRE,b'',2,'flow',1,0))
        self.assertEqual(r.failure_code,'P30_DIRECTION_MISMATCH')

    def test_invalid_actor_or_resource_range_quarantined(self):
        adapter,_=load_local_recipe(self.root, build=BUILD,adapter_id=ADAPTER)
        for actor,value in ((0,9),(777,999),(777,2**30)):
            body=v(40)+v(actor)+pfield(9,v(24)+v(value))
            result=adapter.decode(WireMessage('server_to_client',WIRE,body,2,'flow',1,0))
            self.assertEqual(result.status,'QUARANTINED')

    def test_nested_hp_layout_with_explicit_maximum(self):
        encode_recipe(self.root, recipe(resource='actor_hp'))
        adapter,_=load_local_recipe(self.root,build=BUILD,adapter_id=ADAPTER)
        body=v(40)+v(777)+pfield(9,v(24)+v(1200)+v(32)+v(1800))
        r=adapter.decode(WireMessage('server_to_client',WIRE,body,2,'flow',1,0))
        self.assertEqual(r.status,'CANDIDATES_ONLY')
        self.assertEqual((r.candidates[0].value,r.candidates[0].maximum),(1200,1800))
        self.assertEqual(r.candidates[0].authority,'HISTORICAL_CANDIDATE_ONLY')

    def test_hp_exceeds_maximum_quarantined(self):
        encode_recipe(self.root, recipe(resource='actor_hp'))
        adapter,_=load_local_recipe(self.root,build=BUILD,adapter_id=ADAPTER)
        body=v(40)+v(777)+pfield(9,v(24)+v(1900)+v(32)+v(1000))
        r=adapter.decode(WireMessage('server_to_client',WIRE,body,2,'flow',1,0))
        self.assertEqual(r.status,'QUARANTINED')

    def test_renamed_mp_wire_uses_stable_canonical_resource(self):
        encode_recipe(self.root,recipe(resource='actor_mp'))
        adapter,_=load_local_recipe(self.root,build=BUILD,adapter_id=ADAPTER)
        body=v(40)+v(777)+pfield(9,v(24)+v(5))
        r=adapter.decode(WireMessage('server_to_client',WIRE,body,2,'flow',1,0))
        self.assertEqual(r.status,'CANDIDATES_ONLY')
        self.assertEqual((r.candidates[0].resource,r.candidates[0].value),('MP',5))
        self.assertFalse(hasattr(r,'authoritative'))

    def test_unexpected_protobuf_wire_encoding_quarantined(self):
        adapter,_=load_local_recipe(self.root,build=BUILD,adapter_id=ADAPTER)
        body=v(40)+v(777)+pfield(9,b'\xff\xff\xff')
        r=adapter.decode(WireMessage('server_to_client',WIRE,body,2,'flow',1,0))
        self.assertEqual(r.status,'QUARANTINED')

    def test_registry_cannot_use_parent_traversal_or_absolute_path(self):
        reg=self.root/'reference/protocol/research_adapters/registry.json'
        for fname in ('../case.json','/tmp/test.json','evil\\test.json','registry.json'):
            encode_recipe(self.root)
            obj=json.loads(reg.read_text());obj['adapters'][0]['file']=fname
            reg.write_text(json.dumps(obj))
            with self.assertRaises(RecipeRejected):
                load_local_recipe(self.root,build=BUILD,adapter_id=ADAPTER)

    def test_duplicate_json_keys_rejected(self):
        reg=self.root/'reference/protocol/research_adapters/registry.json'
        reg.write_bytes(b'{"schema":1,"schema":1,"source_role":"LOCAL_REVIEWED_RESEARCH_ONLY","adapters":[]}')
        with self.assertRaises(RecipeRejected):
            load_local_recipe(self.root,build=BUILD,adapter_id=ADAPTER)

    def test_unknown_capability_fails_registration(self):
        encode_recipe(self.root,recipe(resource='spell_cast'))
        with self.assertRaises(RecipeRejected):
            load_local_recipe(self.root,build=BUILD,adapter_id=ADAPTER)

    def test_malicious_recipe_cannot_execute_python(self):
        data=recipe()
        data['rules'][0]['expression']='__import__("os").system("true")'
        encode_recipe(self.root,data)
        with self.assertRaises(RecipeRejected):
            load_local_recipe(self.root,build=BUILD,adapter_id=ADAPTER)

    def test_new_recipe_wire_underscores_supported_by_canonical(self):
        adapter,_=load_local_recipe(self.root,build=BUILD,adapter_id=ADAPTER)
        body=v(40)+v(777)+pfield(9,v(24)+v(9))
        r=adapter.decode(WireMessage('server_to_client',WIRE,body,2,'flow',1,0))
        self.assertEqual(r.status,'CANDIDATES_ONLY')
        self.assertEqual(r.candidates[0].evidence.wire_name,WIRE)

    def test_duplicate_rule_names_rejected(self):
        dup=recipe();dup['rules']*=2
        encode_recipe(self.root,dup)
        with self.assertRaises(RecipeRejected):load_local_recipe(self.root,build=BUILD,adapter_id=ADAPTER)

    def test_overlapping_paths_rejected(self):
        encode_recipe(self.root,recipe(value_path=[5]))
        with self.assertRaises(RecipeRejected):load_local_recipe(self.root,build=BUILD,adapter_id=ADAPTER)

    def test_oversized_recipe_rejected(self):
        file=self.root/'reference/protocol/research_adapters/case.json'
        file.write_bytes(b'A'*32769)
        with self.assertRaises(RecipeRejected):load_local_recipe(self.root,build=BUILD,adapter_id=ADAPTER)

    def test_symlink_recipe_rejected(self):
        p=self.root/'reference/protocol/research_adapters/case.json';p.unlink()
        try:p.symlink_to(ROOT/'reference/protocol/manifest.json')
        except (OSError,NotImplementedError):self.skipTest('Symlink unavailable')
        with self.assertRaises(RecipeRejected):load_local_recipe(self.root,build=BUILD,adapter_id=ADAPTER)

    def test_read_only_setup_integration(self):
        staging=self.root/'protocol_updates';staging.mkdir()
        (staging/'new_version.zip').write_bytes(evidence())
        result=audit_staged_updates(self.root)
        self.assertEqual(result['packs'][0]['semantic_comparison']['matched_cases'],1)
        self.assertFalse(result['live_semantic_certified'])
        self.assertFalse(result['physical_input_sent'])

    def test_registry_boolean_schema_rejected(self):
        registry=self.root/'reference/protocol/research_adapters/registry.json'
        doc=json.loads(registry.read_text());doc['schema']=True
        registry.write_text(json.dumps(doc))
        with self.assertRaises(RecipeRejected):load_local_recipe(self.root,build=BUILD,adapter_id=ADAPTER)


if __name__=='__main__':unittest.main()
