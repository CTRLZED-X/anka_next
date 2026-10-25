"""P3 package boundary, diagnostic and non-Windows negative acceptance."""
import ast
import os
import unittest
from pathlib import Path
from anka_client.api import inspect_local_clients
from anka_app.cli import ROOT


class TestClientSafetyBoundary(unittest.TestCase):
    def test_client_package_does_not_own_input_actions(self):
        forbidden={'SendInput','mouse_event','keybd_event','SetForegroundWindow',
                   'PostMessageW','SendMessageW','SetCursorPos','mouse_left_down',
                   'click_screen','set_foreground','move_screen','send_key'}
        files=list((ROOT/'src/anka_client').rglob('*.py'))
        self.assertGreaterEqual(len(files),4)
        for file in files:
            tree=ast.parse(file.read_text(encoding='utf8'))
            for node in ast.walk(tree):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
                    self.assertNotIn(node.func.attr,forbidden, str(file))
    def test_client_contracts_no_runtime_implementation_dependencies(self):
        p=ROOT/'src/anka_contracts/client.py'
        t=ast.parse(p.read_text())
        imported=[]
        for item in ast.walk(t):
            if isinstance(item,ast.ImportFrom): imported.append(item.module or '')
        self.assertFalse([x for x in imported if x.startswith('anka_client')],imported)
    @unittest.skipIf(os.name=='nt','Linux-only negative acceptance')
    def test_non_windows_client_scan_is_explicitly_unavailable(self):
        r=inspect_local_clients(('Curseni','Sosoking'))
        self.assertEqual((r['status'],r['reason']),('NOT_AVAILABLE','WINDOWS_REQUIRED'))
        self.assertFalse(r['physical_input_permitted'])
    @unittest.skipIf(os.name=='nt','Linux-only negative acceptance')
    def test_win32_backend_cannot_initialize_on_linux(self):
        from anka_client.win32_inventory import NativeWindowsInventory
        with self.assertRaisesRegex(RuntimeError,'WINDOW_DISCOVERY_REQUIRES_WINDOWS'):
            NativeWindowsInventory(('Curseni',))

if __name__=='__main__':unittest.main()

class TestClientDiagnosticsAcceptance(unittest.TestCase):
    def test_inspection_evidence_is_exported_as_partial_identity(self):
        import json
        import tempfile
        from zipfile import ZipFile
        from anka_observability.api import LocalDiagnostics
        from anka_observability.bundle import verify_incident
        with tempfile.TemporaryDirectory() as tmp:
            d=LocalDiagnostics(Path(tmp))
            d.record('client.inspection_completed',boundary='client.read_only_inspection',
                     payload={'account_states':['BLOCKED'],'reasons':['AMBIGUOUS_WINDOWS'],'physical_input':False})
            zpath=d.export_incident('CLIENT_IDENTITY_INCOMPLETE',boundary='client.read_only_inspection')
            self.assertEqual(verify_incident(zpath)['status'],'PASS')
            with ZipFile(zpath) as z:
                matrix=json.loads(z.read('evidence_matrix.json'))
                self.assertEqual(matrix['sections']['identity'],'PARTIAL')
                self.assertEqual(matrix['sections']['execution'],'MISSING')
