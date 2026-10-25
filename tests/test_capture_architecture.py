"""Executable dependency limits: P4 cannot grab downstream internals."""
import ast
import unittest
from pathlib import Path
from anka_app.cli import ROOT

class TestCaptureDependencies(unittest.TestCase):
    def test_capture_does_not_import_protocol_or_runtime_authority(self):
        forbidden={'anka_protocol','anka_canonical','anka_live_state','anka_decision','anka_execution','anka_coordination','anka_workflow','anka_app'}
        for source in (ROOT/'src/anka_capture').rglob('*.py'):
            tree=ast.parse(source.read_text('utf8'))
            imports=[]
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom): imports.append(node.module or '')
                if isinstance(node,ast.Import): imports.extend(x.name for x in node.names)
            self.assertFalse(any(name.split('.')[0] in forbidden for name in imports),str(source))
    def test_capture_contracts_have_no_internal_dependencies(self):
        source=(ROOT/'src/anka_contracts/capture.py').read_text('utf8')
        self.assertNotIn('anka_capture',source)
        self.assertNotIn('anka_app',source)
        self.assertNotIn('anka_protocol',source)
