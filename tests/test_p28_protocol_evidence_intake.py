"""P28 independent hostile-archive, provenance, admission and operator tests."""
from __future__ import annotations

from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import warnings
from unittest.mock import patch

from anka_protocol.evidence_intake import inspect_evidence_pack, IntakeRejected, REQUIRED_CAPABILITIES
from anka_app.protocol_updates import audit_staged_updates


def packed(caps=('actor_hp',), *, witness=True, build='Dofus 3.7.11.11',
           mutate=None, extra=None, duplicate=None, name='evidence.zip') -> bytes:
    capture = b'\x0a\x0d\x0d\x0a' + b'\0' * 20  # only an intake signature, not a real full PCAPNG
    oracle = {'schema':1,'observations':[]}
    items = []
    for idx,cap in enumerate(caps):
        oracle['observations'].append({'id':f'obs{idx}','capability':cap,
                                       'expected':{'actor_id':123,'value':idx+1}})
        row = {'id':f'case{idx}','capability':cap,'capture':'captures/session.pcapng',
               'oracle':'oracles/annotated.json','oracle_id':f'obs{idx}',
               'account_role':'leader'}
        if witness:row['witness']='witness/screenshot.png'
        items.append(row)
    files = {'captures/session.pcapng':capture,
             'oracles/annotated.json':json.dumps(oracle,sort_keys=True).encode(),
             'witness/screenshot.png':b'\x89PNG\r\n\x1a\n' + b'\0'*12}
    if not witness: del files['witness/screenshot.png']
    sources = []
    for path, value in files.items():
        sources.append({'path':path,'sha256':sha256(value).hexdigest(),
                        'kind':'pcapng' if path.endswith('pcapng') else 'oracle' if path.endswith('json') else 'screenshot'})
    manifest = {'schema':1,'package_kind':'ANKA_PROTOCOL_EVIDENCE',
                'protocol_build':build,'adapter_id':'dofus_r28_candidate',
                'sources':sources,'cases':items}
    if mutate:mutate(manifest,files)
    files['manifest.json']=json.dumps(manifest,sort_keys=True).encode()
    if extra:files.update(extra)
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for path,value in files.items():archive.writestr(path,value)
        if duplicate:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore',UserWarning)
                archive.writestr(duplicate,files.get(duplicate,b''))
    return output.getvalue()


class P28Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def file(self,data,name='test.zip'):
        p=self.root/name;p.write_bytes(data);return p

    def inspect(self,data):return inspect_evidence_pack(self.file(data))

    def rejects(self,data,code):
        with self.assertRaises(IntakeRejected) as exc:self.inspect(data)
        self.assertEqual(str(exc.exception),'P28_'+code)

    def test_intake_is_never_live_certified(self):
        report=self.inspect(packed())
        d=report.to_dict()
        self.assertEqual(d['status'],'EVIDENCE_INTAKE_INCOMPLETE')
        self.assertEqual(d['case_count'],1)
        self.assertEqual(d['covered_capabilities'],['actor_hp'])
        self.assertFalse(d['adapter_activated'])
        self.assertFalse(d['live_semantic_certified'])
        self.assertFalse(d['physical_input_sent'])
        self.assertEqual(d['canonical_commits'],0)
        self.assertEqual(len(d['archive_sha256']),64)

    def test_all_capabilities_are_intake_only(self):
        r=self.inspect(packed(sorted(REQUIRED_CAPABILITIES)))
        self.assertEqual(r.missing_capabilities,())
        self.assertTrue(r.intake_complete)
        self.assertEqual(r.to_dict()['status'],'EVIDENCE_INTAKE_READY_FOR_MANUAL_REVIEW')
        self.assertFalse(r.to_dict()['live_semantic_certified'])
        self.assertIn('CURRENT_BUILD_SEMANTIC_ADAPTER_NOT_CERTIFIED',r.to_dict()['blockers'])

    def test_missing_witness_explicit_not_certified(self):
        r=self.inspect(packed(witness=False))
        self.assertEqual(r.cases_with_witness,0)
        self.assertIn('VISUAL_OR_LOG_WITNESS_MISSING',r.to_dict()['blockers'])

    def test_exact_build_preserved_not_inferred(self):
        self.assertEqual(self.inspect(packed(build='Dofus 3.7.11.11')).protocol_build,'Dofus 3.7.11.11')
        self.rejects(packed(build='../../../../secret'),'IDENTIFIER_INVALID')

    def test_traversal_rejected(self):
        self.rejects(packed(extra={'../payload.py':b'evil'}),'PATH_UNSAFE')

    def test_windows_separator_rejected(self):
        self.rejects(packed(extra={'C:\\tmp\\x':b'evil'}),'PATH_UNSAFE')

    def test_unlisted_extra_member_rejected(self):
        self.rejects(packed(extra={'notes.txt':b'private'}),'UNDECLARED_ARCHIVE_MEMBER')

    def test_case_insensitive_duplicate_rejected(self):
        self.rejects(packed(extra={'MANIFEST.JSON':b'{}'}),'ARCHIVE_DUPLICATE_NAME')

    def test_exact_duplicate_rejected(self):
        self.rejects(packed(duplicate='manifest.json'),'ARCHIVE_DUPLICATE_NAME')

    def test_bad_manifest_digest_rejected(self):
        def modify(m,files):m['sources'][0]['sha256']='0'*64
        self.rejects(packed(mutate=modify),'FILE_HASH_MISMATCH')

    def test_swapped_oracle_capability_rejected(self):
        def modify(m,files):m['cases'][0]['capability']='turn_start'
        self.rejects(packed(mutate=modify),'CASE_ORACLE_MISMATCH')

    def test_missing_capture_reference_rejected(self):
        def modify(m,files):m['cases'][0]['capture']='captures/missing.pcapng'
        self.rejects(packed(mutate=modify),'CASE_SOURCE_MISMATCH')

    def test_wrong_witness_kind_rejected(self):
        def modify(m,files):m['cases'][0]['witness']='captures/session.pcapng'
        self.rejects(packed(mutate=modify),'CASE_WITNESS_MISMATCH')

    def test_wrong_magic_rejected(self):
        def modify(m,files):
            files['captures/session.pcapng']=b'NOT_PCAPNG'
            m['sources'][0]['sha256']=sha256(files['captures/session.pcapng']).hexdigest()
        self.rejects(packed(mutate=modify),'PCAPNG_SIGNATURE_INVALID')

    def test_forged_png_witness_rejected(self):
        def modify(m,files):
            files['witness/screenshot.png']=b'not a real png'
            m['sources'][2]['sha256']=sha256(files['witness/screenshot.png']).hexdigest()
        self.rejects(packed(mutate=modify),'WITNESS_FORMAT_INVALID')

    def test_manifest_extra_key_fails(self):
        def modify(m,files):m['activate']=True
        self.rejects(packed(mutate=modify),'SCHEMA_INVALID')

    def test_unsupported_package_kind_fails(self):
        def modify(m,files):m['package_kind']='INSTALL_ADAPTER'
        self.rejects(packed(mutate=modify),'MANIFEST_VERSION_UNSUPPORTED')

    def test_unsupported_schema_fails(self):
        def modify(m,files):m['schema']=2
        self.rejects(packed(mutate=modify),'MANIFEST_VERSION_UNSUPPORTED')

    def test_unbounded_case_rejected(self):
        def modify(m,files):m['cases'] *= 129
        self.rejects(packed(mutate=modify),'CASE_COUNT_INVALID')

    def test_duplicate_case_rejected(self):
        def modify(m,files):m['cases'].append(dict(m['cases'][0]))
        self.rejects(packed(mutate=modify),'CASE_INVALID')

    def test_nonfinite_json_rejected(self):
        # This specifically tests Python's non-standard NaN JSON parser behavior.
        def modify(m,files):
            data=json.loads(files['oracles/annotated.json'])
            data['observations'][0]['expected']['value']=float('nan')
            files['oracles/annotated.json']=json.dumps(data).encode()
            m['sources'][1]['sha256']=sha256(files['oracles/annotated.json']).hexdigest()
        self.rejects(packed(mutate=modify),'NONFINITE_JSON')

    def test_bad_binary_pack_rejected(self):
        self.rejects(b'not zip','ARCHIVE_INVALID')

    def test_bad_json_rejected(self):
        def modify(m,files):m['cases'][0]['account_role']={'evil':True}
        self.rejects(packed(mutate=modify),'CASE_INVALID')

    def test_unhashable_source_kind_fails_closed(self):
        def modify(m,files):m['sources'][0]['kind']=['pcapng']
        self.rejects(packed(mutate=modify),'SOURCE_INVALID')

    def test_unhashable_capability_fails_closed(self):
        def modify(m,files):m['cases'][0]['capability']=['actor_hp']
        self.rejects(packed(mutate=modify),'CASE_INVALID')

    def test_unhashable_case_capture_fails_closed(self):
        def modify(m,files):m['cases'][0]['capture']={'path':'captures/session.pcapng'}
        self.rejects(packed(mutate=modify),'CASE_SOURCE_MISMATCH')

    def test_unhashable_oracle_id_fails_closed(self):
        def modify(m,files):m['cases'][0]['oracle_id']=['obs0']
        self.rejects(packed(mutate=modify),'CASE_ORACLE_MISMATCH')

    def test_unhashable_witness_fails_closed(self):
        def modify(m,files):m['cases'][0]['witness']=['witness/screenshot.png']
        self.rejects(packed(mutate=modify),'CASE_WITNESS_MISMATCH')

    def test_unhashable_oracle_capability_fails_closed(self):
        def modify(m,files):
            data=json.loads(files['oracles/annotated.json'])
            data['observations'][0]['capability']=['actor_hp']
            files['oracles/annotated.json']=json.dumps(data).encode()
            m['sources'][1]['sha256']=sha256(files['oracles/annotated.json']).hexdigest()
        self.rejects(packed(mutate=modify),'ORACLE_OBSERVATION_INVALID')

    def test_no_staged_directory_safe(self):
        result=audit_staged_updates(self.root)
        self.assertEqual(result['status'],'NO_PACK_STAGED')
        self.assertFalse(result['adapter_activated'])

    def test_readonly_staging_and_privacy(self):
        folder=self.root/'protocol_updates';folder.mkdir()
        raw=packed();(folder/'new.zip').write_bytes(raw)
        result=audit_staged_updates(self.root)
        self.assertEqual(result['status'],'RESEARCH_PACKS_AUDITED_NOT_ACTIVATED')
        self.assertEqual(result['packs'][0]['protocol_build'],'Dofus 3.7.11.11')
        self.assertNotIn('captures/session.pcapng',str(result))
        self.assertNotIn('Curseni',str(result))
        self.assertEqual((folder/'new.zip').read_bytes(),raw)
        self.assertEqual(list(folder.iterdir()),[folder/'new.zip'])

    def test_duplicate_build_staging_rejected(self):
        folder=self.root/'protocol_updates';folder.mkdir()
        (folder/'a.zip').write_bytes(packed())
        (folder/'b.zip').write_bytes(packed())
        with self.assertRaisesRegex(IntakeRejected,'P28_DUPLICATE_STAGED_BUILD'):
            audit_staged_updates(self.root)

    def test_symlinked_staging_rejected(self):
        original=self.root/'other';original.mkdir()
        (self.root/'protocol_updates').symlink_to(original,target_is_directory=True)
        with self.assertRaisesRegex(IntakeRejected,'P28_STAGING_DIRECTORY_INVALID'):
            audit_staged_updates(self.root)

    def test_nonzip_staging_rejected(self):
        folder=self.root/'protocol_updates';folder.mkdir()
        (folder/'adaptor.py').write_text('print("attack")')
        with self.assertRaisesRegex(IntakeRejected,'P28_STAGING_ENTRY_INVALID'):
            audit_staged_updates(self.root)

    def test_too_many_pack_files_fails(self):
        folder=self.root/'protocol_updates';folder.mkdir()
        for n in range(4):(folder/f'{n}.zip').write_bytes(packed())
        with self.assertRaisesRegex(IntakeRejected,'P28_TOO_MANY_STAGED_PACKS'):
            audit_staged_updates(self.root)

    def test_no_mutation_of_code_packages(self):
        before=list(self.root.rglob('*.py'))
        folder=self.root/'protocol_updates';folder.mkdir()
        (folder/'new.zip').write_bytes(packed())
        audit_staged_updates(self.root)
        self.assertEqual(before,list(self.root.rglob('*.py')))

    def test_observer_sanitized_events(self):
        class Sink:
            def __init__(self):self.events=[]
            def record(self,name,**kw):self.events.append((name,kw))
        sink=Sink()
        folder=self.root/'protocol_updates';folder.mkdir()
        (folder/'update.zip').write_bytes(packed())
        audit_staged_updates(self.root,observer=sink)
        dumped=str(sink.events)
        self.assertIn('protocol.evidence_pack_audited',dumped)
        self.assertNotIn('captures/',dumped)
        self.assertNotIn('oracles/',dumped)
        self.assertNotIn('witness/',dumped)

if __name__=='__main__':unittest.main()
