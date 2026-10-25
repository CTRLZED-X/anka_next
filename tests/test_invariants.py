import ast
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import tempfile
import unittest
from anka_app.cli import ROOT
from anka_observability.api import LocalDiagnostics
from anka_observability.redaction import sanitize

class TestArchitecturalInvariants(unittest.TestCase):
    def test_dependency_direction_public_packages(self):
        forbidden={
            'anka_contracts':('anka_app','anka_capture','anka_protocol','anka_execution','anka_observability'),
            'anka_game_kernel':('anka_app','anka_capture','anka_protocol','anka_execution','anka_observability'),
            'anka_observability':('anka_app','anka_capture','anka_protocol','anka_execution','anka_decision','anka_client'),
            'anka_client':('anka_execution','anka_decision')
        }
        for owner, disallowed in forbidden.items():
            for f in (ROOT/'src'/owner).rglob('*.py'):
                t=ast.parse(f.read_text(encoding='utf8'))
                imports=[x.module for x in ast.walk(t) if isinstance(x,ast.ImportFrom) and x.module]
                imports += [a.name for x in ast.walk(t) if isinstance(x,ast.Import) for a in x.names]
                for imp in imports:
                    self.assertFalse(any(imp==bad or imp.startswith(bad+'.') for bad in disallowed),(owner,str(f),imp))
    def test_concurrent_events_have_coherent_sequences(self):
        with tempfile.TemporaryDirectory() as d:
            o=LocalDiagnostics(Path(d),max_recent=1000)
            with ThreadPoolExecutor(max_workers=8) as ex:
                results=list(ex.map(lambda n:o.record('test.parallel',payload={'index':n}),range(100)))
            self.assertEqual(results.count('RECORDED'),100)
            # Runtime recording is intentionally asynchronous: producer order is
            # authoritative immediately in the bounded in-memory flight recorder,
            # while durable journal completeness is guaranteed only after an
            # explicit bounded flush.  Reading events.jsonl before that flush would
            # incorrectly turn healthy writer lag into apparent evidence loss.
            memory_seq=[row['producer_seq'] for row in o.freeze().recent]
            self.assertEqual(memory_seq,list(range(1,101)))
            self.assertTrue(o.flush_journals(timeout_seconds=2.0))
            seq=[json.loads(s)['producer_seq'] for s in (o.folder/'events.jsonl').read_text().splitlines()]
            self.assertEqual(seq,list(range(1,101)))
            o.finish('CLOSED')
    def test_nonfinite_values_are_not_logged_as_nonstandard_json(self):
        self.assertEqual(sanitize({'measurement':math.nan})['measurement'],'[NONFINITE_FLOAT]')
