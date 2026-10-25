from __future__ import annotations
import json, unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from anka_app.composition import AnkaCompositionRoot,CompositionBlocked
from anka_app.configuration import load_user_config
from tools.build_release import build_manifest, _validate_windows_release_paths
from tools.verify_release_offline import undeclared_release_files, release_manifest_integrity_failures
from tools.verify_m12 import self_excluding_release_model

ROOT=Path(__file__).resolve().parents[1]

class TestM12CompositionPackaging(unittest.TestCase):
    @staticmethod
    def _temp_manifest(root:Path, rows:list[dict]) -> dict:
        from hashlib import sha256
        payload=json.dumps(rows,sort_keys=True,separators=(',',':')).encode()
        return {'files':rows,'release_file_count':len(rows),'release_content_sha256':sha256(payload).hexdigest()}

    def test_offline_release_manifest_integrity_is_fail_closed_on_malformed_rows(self):
        with TemporaryDirectory() as td:
            root=Path(td)
            manifest={'files':[None],'release_file_count':1,'release_content_sha256':'0'*64}
            failures=release_manifest_integrity_failures(root,manifest)
            self.assertIn('file_row_shape:0',failures)

    def test_offline_release_manifest_integrity_rejects_duplicate_paths_and_bad_aggregate(self):
        from hashlib import sha256
        with TemporaryDirectory() as td:
            root=Path(td);target=root/'a.txt';target.write_text('a',encoding='utf8')
            row={'path':'a.txt','size':1,'sha256':sha256(b'a').hexdigest()}
            manifest=self._temp_manifest(root,[row,row.copy()])
            self.assertIn('duplicate_file:a.txt',release_manifest_integrity_failures(root,manifest))
            good=self._temp_manifest(root,[row]);good['release_content_sha256']='0'*64
            self.assertIn('release_content_hash',release_manifest_integrity_failures(root,good))

    def test_offline_release_manifest_integrity_rejects_unsafe_paths_without_reading_them(self):
        with TemporaryDirectory() as td:
            root=Path(td)
            manifest=self._temp_manifest(root,[{'path':'../escape','size':0,'sha256':'0'*64}])
            self.assertIn('file_path_invalid:0',release_manifest_integrity_failures(root,manifest))

    def test_offline_release_verifier_rejects_undeclared_package_files(self):
        with TemporaryDirectory() as td:
            root=Path(td)
            (root/'declared.txt').write_text('declared',encoding='utf8')
            manifest={'files':[{'path':'declared.txt'}]}
            self.assertEqual(undeclared_release_files(root,manifest),())
            (root/'unexpected.txt').write_text('unexpected',encoding='utf8')
            self.assertEqual(undeclared_release_files(root,manifest),('unexpected.txt',))



    def test_release_builder_rejects_windows_casefold_path_collisions(self):
        rows=[{'path':'provenance/REUSE_MANIFEST.json'},
              {'path':'provenance/reuse_manifest.json'}]
        with self.assertRaisesRegex(ValueError,'RELEASE_WINDOWS_PATH_COLLISION'):
            _validate_windows_release_paths(rows)

    def test_current_release_has_no_windows_casefold_path_collisions(self):
        manifest=build_manifest(ROOT);seen={}
        for row in manifest['files']:
            key=row['path'].casefold()
            self.assertNotIn(key,seen,(seen.get(key),row['path']))
            seen[key]=row['path']

    def test_release_builder_rejects_symlink_files_instead_of_following_them(self):
        with TemporaryDirectory() as td:
            root=Path(td);outside=root.parent/'anka-release-outside-probe.txt'
            outside.write_text('outside',encoding='utf8')
            link=root/'linked.txt'
            try:
                link.symlink_to(outside)
            except (OSError,NotImplementedError):
                self.skipTest('symlink unavailable on this host')
            try:
                with self.assertRaisesRegex(ValueError,'RELEASE_SYMLINK_UNSUPPORTED:linked.txt'):
                    build_manifest(root)
            finally:
                outside.unlink(missing_ok=True)

    def test_definitive_composition_is_live_blocked_and_input_disabled(self):
        s=AnkaCompositionRoot.status()
        self.assertFalse(s.live_ready);self.assertEqual(s.physical_input_state,'DISABLED')
        self.assertIn('CURRENT_CLIENT_SEMANTIC_ADAPTER_UNCERTIFIED',s.blockers)
        self.assertIn('WINDOWS_PHYSICAL_INPUT_SCOPE_NOT_ACCEPTED',s.blockers)
        with self.assertRaisesRegex(CompositionBlocked,'LIVE_RUNTIME_NOT_IMPLEMENTED'):
            AnkaCompositionRoot.build_live_runtime()

    def test_normal_operator_config_is_minimal(self):
        obj=json.loads((ROOT/'config/user.json').read_text())
        self.assertEqual(set(obj),{'schema_version','players','mission'})
        self.assertNotIn('capture',obj)
        self.assertNotIn('protocol',obj)
        self.assertNotIn('calibration',obj)
        cfg=load_user_config(ROOT/'config/user.json')
        self.assertEqual(cfg.capture.server_ports,())

    def test_example_matches_normal_operator_surface(self):
        example=json.loads((ROOT/'config/user.example.json').read_text())
        live=json.loads((ROOT/'config/user.json').read_text())
        self.assertEqual(set(example),set(live))
        self.assertEqual(set(example['mission']),{'route_id','min_monsters','max_monsters','target_wins','max_attempts','stop_on_loss','stop_on_unknown'})

    def test_only_two_top_level_operator_bat_launchers(self):
        bats=sorted(p.name for p in ROOT.glob('*.bat'))
        self.assertEqual(bats,['setup.bat','start.bat'])

    def test_no_ui_runtime_dependency(self):
        pyproject=(ROOT/'pyproject.toml').read_text().lower()
        for ui in ('flask','fastapi','django','streamlit','dash','panel','gradio','pyqt','tkinter'):
            self.assertNotIn(ui,pyproject)

    def test_composition_source_does_not_import_windows_driver(self):
        source=(ROOT/'src/anka_app/composition.py').read_text()
        self.assertNotIn('windows_input',source)
        self.assertNotIn('WindowsPointerInputDriver',source)

    def test_m12_release_model_is_not_circular_on_its_own_receipt(self):
        other={'path':'src/anka_app/composition.py','sha256':'1'*64,'size':10}
        first={'files':[other,{'path':'verification/M12_offline_release_receipt.json','sha256':'a'*64,'size':100}]}
        second={'files':[other,{'path':'verification/M12_offline_release_receipt.json','sha256':'b'*64,'size':999}]}
        one=self_excluding_release_model(first);two=self_excluding_release_model(second)
        self.assertEqual(one,two)
        self.assertEqual(one['release_file_count'],1)
        self.assertNotIn('verification/M12_offline_release_receipt.json',{row['path'] for row in one['files']})

    def test_release_manifest_builder_is_deterministic_and_excludes_runtime(self):
        one=build_manifest(ROOT);two=build_manifest(ROOT)
        self.assertEqual(one['release_content_sha256'],two['release_content_sha256'])
        paths={x['path'] for x in one['files']}
        self.assertIn('setup.bat',paths);self.assertIn('start.bat',paths)
        self.assertIn('config/user.example.json',paths)
        self.assertFalse(any(x.startswith('runtime/') or '/__pycache__/' in '/'+x for x in paths))
        self.assertFalse(any(x.startswith('.venv/') for x in paths))
        self.assertNotIn('.coverage', paths)
        self.assertFalse(any(x.startswith('verification/.') for x in paths))
        self.assertNotIn('verification/.m12_005_full_checkpoint.json', paths)

if __name__=='__main__':unittest.main()
