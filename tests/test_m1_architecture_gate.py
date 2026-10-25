"""M1 Q1 architecture/authority mutant tests."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path

from anka_app.architecture_guard import SYSTEM_IMPORTS, AUTHORITY_OWNERS, audit_source_boundaries
from anka_app.cli import ROOT


class M1ArchitectureGateTests(unittest.TestCase):
    def _layout(self, base: Path) -> Path:
        src=base/'src'
        for package in SYSTEM_IMPORTS:
            (src/package).mkdir(parents=True,exist_ok=True)
            (src/package/'__init__.py').write_text('',encoding='utf8')
        return src

    def test_real_graph_has_no_cycle_and_one_declared_owner_per_authority(self):
        audit=audit_source_boundaries(ROOT/'src')
        self.assertEqual(audit.status,'PASS',audit.violations)
        self.assertEqual(audit.strongly_connected_components,())
        self.assertEqual(dict(audit.authority_owners),AUTHORITY_OWNERS)
        self.assertEqual(len(AUTHORITY_OWNERS),len(set(AUTHORITY_OWNERS)))

    def test_two_node_cycle_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            src=self._layout(Path(d))
            (src/'anka_capture'/'bad.py').write_text('import anka_protocol\n')
            (src/'anka_protocol'/'bad.py').write_text('import anka_capture\n')
            audit=audit_source_boundaries(src)
            self.assertTrue(any(x.startswith('ARCH_DEPENDENCY_CYCLE:') for x in audit.violations))

    def test_nonliteral_dynamic_import_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            src=self._layout(Path(d))
            (src/'anka_protocol'/'bad.py').write_text("import importlib\nname='anka_execution.ledger'\nimportlib.import_module(name)\n")
            audit=audit_source_boundaries(src)
            self.assertTrue(any(x.startswith('ARCH_DYNAMIC_IMPORT_NON_LITERAL:') for x in audit.violations))

    def test_import_module_alias_cannot_bypass_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            src=self._layout(Path(d))
            (src/'anka_protocol'/'bad.py').write_text("from importlib import import_module as im\nim('anka_execution.ledger')\n")
            audit=audit_source_boundaries(src)
            self.assertTrue(any('anka_protocol->anka_execution' in x for x in audit.violations))

    def test_getattr_dynamic_import_cannot_bypass_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            src=self._layout(Path(d))
            (src/'anka_protocol'/'bad.py').write_text("import importlib as il\ngetattr(il,'import_module')('anka_execution.ledger')\n")
            audit=audit_source_boundaries(src)
            self.assertTrue(any('anka_protocol->anka_execution' in x for x in audit.violations))

    def test_input_primitive_outside_execution_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            src=self._layout(Path(d))
            (src/'anka_decision'/'bad.py').write_text("def f():\n    SendInput(1)\n")
            audit=audit_source_boundaries(src)
            self.assertTrue(any(x.startswith('ARCH_INPUT_AUTHORITY_BYPASS:') for x in audit.violations))

    def test_execution_is_declared_sole_physical_input_owner(self):
        self.assertEqual(AUTHORITY_OWNERS['physical_input_and_settlement'],'anka_execution')
        self.assertNotIn('anka_execution',SYSTEM_IMPORTS['anka_decision'])
        self.assertNotIn('anka_execution',SYSTEM_IMPORTS['anka_workflow'])
        self.assertNotIn('anka_execution',SYSTEM_IMPORTS['anka_coordination'])

    def test_domain_systems_never_import_app(self):
        audit=audit_source_boundaries(ROOT/'src')
        forbidden=[edge for edge in audit.edges if edge.endswith('->anka_app') and not edge.startswith('anka_app->')]
        self.assertEqual(forbidden,[])

if __name__=='__main__': unittest.main()
