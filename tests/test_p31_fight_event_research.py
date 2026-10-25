"""P31 independent golden/negative replay cases. No observed client data."""
from __future__ import annotations
import io,json,shutil,tempfile,unittest
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from anka_protocol.adapters.declarative import load_local_recipe, RecipeRejected
from anka_contracts.protocol import WireMessage
from anka_contracts.fight_semantic import FightResearchDraft
from anka_canonical.research_timeline import replay_research_timeline
from anka_canonical.staging import CanonicalStagingGate
from anka_app.protocol_evidence_compare import compare_pack
from tests.capture_fixtures import packet,pcapng
from tests.test_protocol_wire import framed, any_body, v
from anka_capture.pcapng import read_pcapng_tcp_segments
from anka_app.cli import ROOT

BUILD='Dofus 3.7.11.11'
ADAPTER='research_fight_adapter'
CAPS={
 'fight_start': ('FIGHT_START_OBSERVED',('fight_id_path',),'fight_id'),
 'fight_end': ('FIGHT_END_OBSERVED',('fight_id_path',),'fight_id'),
 'turn_start': ('TURN_START_OBSERVED',('fight_id_path','actor_path','turn_index_path'),'turn_index'),
 'turn_end': ('TURN_END_OBSERVED',('fight_id_path','actor_path','turn_index_path'),'turn_index'),
 'actor_cell': ('ACTOR_CELL_OBSERVED',('fight_id_path','actor_path','cell_path'),'cell_id'),
 'spell_cast': ('SPELL_CAST_OBSERVED',('fight_id_path','actor_path','spell_id_path','target_cell_path'),'spell_id'),
}


def rule(cap,wire=None):
    paths={k:[i+2] for i,k in enumerate(CAPS[cap][1])}
    return {'wire_name':wire or cap+'_wire','direction':'server_to_client','capability':cap,**paths}

def install(root,caps=tuple(CAPS),*,schema=2):
    d=root/'reference/protocol/research_adapters';d.mkdir(parents=True,exist_ok=True)
    obj={'schema':schema,'source_role':'LOCAL_REVIEWED_RESEARCH_ONLY',
         'protocol_build':BUILD,'adapter_id':ADAPTER,'rules':[rule(c) for c in caps]}
    raw=json.dumps(obj,sort_keys=True).encode();(d/'fight.json').write_bytes(raw)
    (d/'registry.json').write_text(json.dumps({'schema':1,'source_role':'LOCAL_REVIEWED_RESEARCH_ONLY',
        'adapters':[{'protocol_build':BUILD,'adapter_id':ADAPTER,'file':'fight.json',
                     'sha256':sha256(raw).hexdigest()}]}))

def msg(cap,packet_number,*,fight=42,actor=777,turn=1,cell=215,spell=123,target=222, wire=None, direction='server_to_client'):
    data={'fight_id_path':fight,'actor_path':actor,'turn_index_path':turn,
          'cell_path':cell,'spell_id_path':spell,'target_cell_path':target}
    body=b''.join(v((i+2)<<3)+v(data[k]) for i,k in enumerate(CAPS[cap][1]))
    return WireMessage(direction,wire or cap+'_wire',body,packet_number,'single-flow',1,0)

class P31Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);install(self.root)
        self.adapter,_=load_local_recipe(self.root,build=BUILD,adapter_id=ADAPTER)
    def test_all_six_fight_event_capabilities(self):
        for cap,(kind,_,_) in CAPS.items():
            with self.subTest(cap=cap):
                r=self.adapter.decode_fight(msg(cap,2))
                self.assertEqual(r.status,'CANDIDATES_ONLY')
                self.assertEqual(r.candidates[0].kind,kind)
                self.assertEqual(r.candidates[0].authority,'RESEARCH_ONLY_NOT_CANONICAL')
                self.assertEqual(self.adapter.decode(msg(cap,2)).status,'NO_SEMANTIC_MAPPING')
    def test_no_canonical_admission(self):
        r=self.adapter.decode_fight(msg('turn_start',2))
        self.assertFalse(hasattr(r.candidates[0],'origin'))
        gate=CanonicalStagingGate()
        result=gate.inspect(r,transport_complete=True,account_attested=True)
        self.assertEqual(result.status,'QUARANTINED')
        self.assertEqual(gate.staged_count,0)
        self.assertEqual(result.committed_events,0)
    def test_reject_wrong_direction(self):
        self.assertEqual(self.adapter.decode_fight(msg('turn_start',2,direction='client_to_server')).failure_code,'P31_DIRECTION_MISMATCH')
    def test_reject_wrong_wire(self):
        self.assertEqual(self.adapter.decode_fight(msg('turn_start',2,wire='unknown')).status,'NO_SEMANTIC_MAPPING')
    def test_reject_missing_required_field(self):
        original=msg('turn_start',2);missing=replace(original,body=original.body[:-2])
        self.assertEqual(self.adapter.decode_fight(missing).status,'QUARANTINED')
    def test_reject_duplicate_field(self):
        original=msg('turn_start',2)
        self.assertEqual(self.adapter.decode_fight(replace(original,body=original.body+original.body[:2])).status,'QUARANTINED')
    def test_reject_negative_and_zero_identity(self):
        for cap in ('turn_start','actor_cell','spell_cast'):
            self.assertEqual(self.adapter.decode_fight(msg(cap,2,actor=0)).status,'QUARANTINED')
    def test_reject_out_of_range_cell(self):
        for cap in ('actor_cell','spell_cast'):
            self.assertEqual(self.adapter.decode_fight(msg(cap,2,cell=100001,target=100001)).status,'QUARANTINED')
    def test_reject_bogus_turn(self):
        self.assertEqual(self.adapter.decode_fight(msg('turn_start',2,turn=1000001)).status,'QUARANTINED')
    def test_strict_schema(self):
        install(self.root,schema=1)
        with self.assertRaises(RecipeRejected):load_local_recipe(self.root,build=BUILD,adapter_id=ADAPTER)
    def test_path_collision_refused(self):
        d=self.root/'reference/protocol/research_adapters'
        obj=json.loads((d/'fight.json').read_text());obj['rules'][2]['turn_index_path']=obj['rules'][2]['actor_path']
        raw=json.dumps(obj).encode();(d/'fight.json').write_bytes(raw)
        reg=json.loads((d/'registry.json').read_text());reg['adapters'][0]['sha256']=sha256(raw).hexdigest()
        (d/'registry.json').write_text(json.dumps(reg))
        with self.assertRaises(RecipeRejected):load_local_recipe(self.root,build=BUILD,adapter_id=ADAPTER)
    def test_hash_pinning(self):
        (self.root/'reference/protocol/research_adapters/fight.json').write_text('{}')
        with self.assertRaises(RecipeRejected):load_local_recipe(self.root,build=BUILD,adapter_id=ADAPTER)
    def sequence(self,caps=('fight_start','turn_start','spell_cast','turn_end','fight_end')):
        return tuple(self.adapter.decode_fight(msg(cap,i+1)).candidates[0] for i,cap in enumerate(caps))
    def test_research_timeline_complete(self):
        t=replay_research_timeline(self.sequence());self.assertEqual(t.status,'CONSISTENT_RESEARCH_ONLY')
        self.assertEqual((t.turn_starts,t.turn_ends,t.spell_casts),(1,1,1))
        self.assertEqual(t.to_dict()['canonical_commits'],0)
        self.assertFalse(t.to_dict()['actionable'])
    def test_research_timeline_start_missing(self):
        self.assertEqual(replay_research_timeline(self.sequence(('turn_start','turn_end'))).reason,'FIGHT_START_NOT_OBSERVED')
    def test_research_timeline_overlapping_turn(self):
        self.assertEqual(replay_research_timeline(self.sequence(('fight_start','turn_start','turn_start'))).reason,'TURN_OVERLAP_OR_REWIND')
    def test_research_timeline_wrong_end_actor(self):
        seq=self.sequence(('fight_start','turn_start','turn_end'))
        self.assertEqual(replay_research_timeline(seq[:2]+(replace(seq[2],actor_id=99),)).reason,'TURN_END_OWNER_OR_EPOCH_MISMATCH')
    def test_research_timeline_cast_without_turn(self):
        self.assertEqual(replay_research_timeline(self.sequence(('fight_start','spell_cast'))).reason,'CAST_WITHOUT_OBSERVED_OWNER')
    def test_research_timeline_mixed_flow(self):
        seq=self.sequence();e=seq[1].evidence
        self.assertEqual(replay_research_timeline(seq[:1]+(replace(seq[1],evidence=replace(e,flow_digest='f'*64)),)+seq[2:]).reason,'STREAM_SCOPE_CHANGED')
    def test_research_timeline_duplicate(self):
        seq=self.sequence()
        self.assertEqual(replay_research_timeline((seq[0],seq[0])).reason,'DUPLICATE_OR_OUT_OF_ORDER_SOURCE')
    def test_research_timeline_post_end(self):
        seq=self.sequence()
        self.assertEqual(replay_research_timeline(seq+(self.adapter.decode_fight(msg('actor_cell',7)).candidates[0],)).reason,'EVENT_AFTER_FIGHT_END')
    def test_research_timeline_unfinished_turn(self):
        self.assertEqual(replay_research_timeline(self.sequence(('fight_start','turn_start'))).reason,'TURN_END_NOT_OBSERVED')
    def test_research_timeline_fight_id_change(self):
        seq=self.sequence()
        self.assertEqual(replay_research_timeline(seq[:1]+(replace(seq[1],fight_id=7),)+seq[2:]).reason,'FIGHT_ID_CHANGED')
    def test_draft_missing_provenance_rejected(self):
        with self.assertRaisesRegex(ValueError,'FIGHT_RESEARCH_PROVENANCE_REQUIRED'):
            FightResearchDraft('FIGHT_START_OBSERVED',None,42)
    def test_result_cross_adapter_evidence_rejected(self):
        from anka_contracts.fight_semantic import FightResearchResult
        draft=self.sequence()[0]
        with self.assertRaisesRegex(ValueError,'FIGHT_RESEARCH_CANDIDATE_PROVENANCE_INVALID'):
            FightResearchResult('CANDIDATES_ONLY','other_adapter',BUILD,draft.evidence.wire_name,(draft,))
    def test_empty_and_excessive_timeline_bounded(self):
        self.assertEqual(replay_research_timeline(()).status,'INCOMPLETE_RESEARCH')
        self.assertEqual(replay_research_timeline((self.sequence()[0],)*4097).reason,
                         'EMPTY_OR_EXCESSIVE_RESEARCH_EVENTS')
    def test_unknown_fields_not_silently_counted_as_known(self):
        r=self.adapter.decode_fight(replace(msg('fight_start',2),body=msg('fight_start',2).body+v(80)+v(10)))
        # Scalar research mappings select exact paths; additional fields do not
        # by themselves prove a version drift or carry unrelated game meaning.
        self.assertEqual(r.status,'CANDIDATES_ONLY')
    def test_wrong_build_not_loaded(self):
        self.assertIsNone(load_local_recipe(self.root,build='Dofus 3.7.99.1',adapter_id=ADAPTER))
    def test_no_operator_launchers_added(self):
        self.assertEqual({p.name for p in ROOT.glob('*.bat')},{'setup.bat','start.bat'})
    def test_forged_authority_rejected(self):
        from dataclasses import replace
        with self.assertRaises((TypeError,ValueError)):
            FightResearchDraft('FIGHT_START_OBSERVED',self.sequence()[0].evidence,42,authority='LIVE')

class P31ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);install(self.root)
    def pack(self,cap='turn_start',*,expected_patch=None,missing=False,gap=False):
        message=msg(cap,2)
        payload=framed(any_body(message.name,message.body))
        blocks=[packet(seq=100,flags=2,data=b'',reverse=True),packet(seq=101,flags=0x18,data=payload,reverse=True)]
        if gap: blocks.append(packet(seq=101+len(payload)+5,flags=0x18,data=b'bad',reverse=True))
        capbytes=pcapng(*blocks)
        segs=read_pcapng_tcp_segments(Path('none'),server_ports={40400},raw=capbytes)
        digest=sha256(segs[1].flow_id.encode()).hexdigest()
        decoded=load_local_recipe(self.root,build=BUILD,adapter_id=ADAPTER)[0].decode_fight(message).candidates[0]
        keys={'fight_start':('fight_id',),'fight_end':('fight_id',),
              'turn_start':('fight_id','actor_id','turn_index'),
              'turn_end':('fight_id','actor_id','turn_index'),
              'actor_cell':('fight_id','actor_id','cell_id'),
              'spell_cast':('fight_id','actor_id','spell_id','target_cell')}[cap]
        expected={k:getattr(decoded,k) for k in keys}
        if expected_patch:expected.update(expected_patch)
        if missing:expected.pop(keys[-1])
        sources={'captures/fixture.pcapng':capbytes,
          'oracles/facts.json':json.dumps({'schema':1,'observations':[{'id':'obs','capability':cap,'expected':expected}]}).encode(),
          'witness/proof.png':b'\x89PNG\r\n\x1a\n'+b'\0'*12}
        manifest={'schema':1,'package_kind':'ANKA_PROTOCOL_EVIDENCE','protocol_build':BUILD,'adapter_id':ADAPTER,
          'server_ports':[40400],'sources':[{'path':p,'sha256':sha256(v).hexdigest(),'kind':'pcapng' if p.endswith('.pcapng') else 'oracle' if p.endswith('.json') else 'screenshot'} for p,v in sources.items()],
          'cases':[{'id':'obs','capability':cap,'capture':'captures/fixture.pcapng','oracle':'oracles/facts.json','oracle_id':'obs','witness':'witness/proof.png','account_role':'leader',
                    'selector':{'packet_number':2,'message_index':0,'wire_name':message.name,'direction':'server_to_client','transport_generation':1,'flow_digest':digest}}]}
        sources['manifest.json']=json.dumps(manifest).encode()
        out=io.BytesIO()
        with ZipFile(out,'w',ZIP_DEFLATED) as z:
            for p,v in sources.items():z.writestr(p,v)
        path=self.root/'evidence.zip';path.write_bytes(out.getvalue())
        return path
    def test_each_new_capability_against_independent_oracle(self):
        for cap in CAPS:
            with self.subTest(cap=cap):
                r=compare_pack(self.pack(cap),root=self.root)
                self.assertEqual(r['status'],'RESEARCH_COMPARISON_MATCHED_NOT_CERTIFIED',r)
                self.assertEqual(r['matched_cases'],1)
                self.assertEqual(r['canonical_commits'],0)
    def test_mismatch_never_exposes_sensitive_values(self):
        r=compare_pack(self.pack('turn_start',expected_patch={'actor_id':99999999}),root=self.root)
        self.assertEqual(r['case_results'][0]['status'],'FIELD_MISMATCH')
        self.assertIn('actor_id',r['case_results'][0]['mismatch_fields'])
        self.assertNotIn('99999999',str(r))
    def test_partial_oracle_cannot_pass(self):
        r=compare_pack(self.pack('spell_cast',missing=True),root=self.root)
        self.assertEqual(r['case_results'][0]['status'],'ORACLE_FIELDS_NOT_COMPARABLE')
    def test_late_gap_blocks_initial_correct_event(self):
        self.assertEqual(compare_pack(self.pack('turn_start',gap=True),root=self.root)['status'],'TRANSPORT_OR_FRAMING_UNPROVEN')
    def test_setup_staged_pack_checks_fight_semantics_research_only(self):
        from anka_app.protocol_updates import audit_staged_updates
        staging=self.root/'protocol_updates';staging.mkdir()
        (staging/'sample.zip').write_bytes(self.pack('turn_start').read_bytes())
        result=audit_staged_updates(self.root)
        self.assertEqual(result['status'],'RESEARCH_PACKS_AUDITED_NOT_ACTIVATED')
        self.assertEqual(result['packs'][0]['semantic_comparison']['matched_cases'],1)
        self.assertFalse(result['adapter_activated'])
        self.assertFalse(result['physical_input_sent'])
    def test_unregistered_recipe_cannot_decode_fight_case(self):
        archive=self.pack('turn_start')
        (self.root/'reference/protocol/research_adapters/registry.json').unlink()
        self.assertEqual(compare_pack(archive,root=self.root)['status'],
                         'ADAPTER_UNAVAILABLE_FOR_EXACT_BUILD')
    def test_no_live_authority_even_matching_oracle(self):
        r=compare_pack(self.pack('fight_start'),root=self.root)
        self.assertFalse(r['live_semantic_certified'])
        self.assertFalse(r['adapter_activated'])
        self.assertFalse(r['physical_input_sent'])
