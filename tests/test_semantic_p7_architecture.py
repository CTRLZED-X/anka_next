from pathlib import Path
import ast,unittest
from anka_app.cli import ROOT
class TestP7Independence(unittest.TestCase):
    def test_protocol_not_import_canonical_implementation(self):
        paths=(ROOT/'src/anka_protocol').rglob('*.py')
        forbidden=('anka_canonical','anka_live_state','anka_capture','anka_app','anka_execution','anka_decision','anka_game_kernel')
        for path in paths:
            for node in ast.walk(ast.parse(path.read_text())):
                imports=([x.name for x in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else [])
                for item in imports:
                    self.assertFalse(any(item==x or item.startswith(x+'.') for x in forbidden),(path,item))
    def test_canonical_does_not_import_protocol_implementation(self):
        for path in (ROOT/'src/anka_canonical').rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                imports=([x.name for x in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else [])
                for item in imports:
                    self.assertFalse(any(item.startswith(x) for x in ('anka_protocol','anka_live_state','anka_capture','anka_app')),(path,item))
if __name__=='__main__':unittest.main()
