"""Shared stdlib verification helpers for definitive M0-M13 gates."""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
import io, json, platform, sys, time, unittest

ROOT=Path(__file__).resolve().parents[1]

def sha256_file(path: Path) -> str:
    h=sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def canonical_hash(obj) -> str:
    return sha256(json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()

def tree_hash(paths: tuple[Path,...], *, exclude_prefixes: tuple[str,...]=()) -> str:
    rows=[]
    for base in paths:
        base=Path(base)
        if not base.exists(): continue
        if base.is_file():
            candidates=[base]
        else:
            candidates=sorted(p for p in base.rglob('*') if p.is_file())
        for p in candidates:
            rel=p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else p.as_posix()
            if '/__pycache__/' in '/'+rel or rel.endswith(('.pyc','.pyo')) or rel.startswith('runtime/'):
                continue
            if any(rel.startswith(x) for x in exclude_prefixes): continue
            rows.append((rel,sha256_file(p),p.stat().st_size))
    return canonical_hash(rows)

def implementation_source_hash() -> str:
    paths=(ROOT/'src',ROOT/'tools',ROOT/'tests',ROOT/'config',ROOT/'assets',ROOT/'native',
           ROOT/'setup.bat',ROOT/'start.bat',ROOT/'pyproject.toml',ROOT/'requirements-p1.txt',ROOT/'requirements-windows-capture.txt',
           ROOT/'PROJECT_INFO.txt')
    return tree_hash(paths,exclude_prefixes=('verification/','runtime/'))

def dependency_manifest_hash() -> str:
    rows=[]
    for name in ('requirements-p1.txt','requirements-windows-capture.txt','pyproject.toml'):
        p=ROOT/name
        if p.exists(): rows.append((name,sha256_file(p)))
    return canonical_hash(rows)

def test_fixture_hash(names: tuple[str,...]) -> str:
    return tree_hash(tuple(ROOT/n for n in names))

def run_unittest_modules(modules: tuple[str,...]) -> dict:
    loader=unittest.defaultTestLoader
    suite=unittest.TestSuite(loader.loadTestsFromName(m) for m in modules)
    stream=io.StringIO(); started=time.monotonic()
    result=unittest.TextTestRunner(stream=stream,verbosity=0).run(suite)
    return {
        'passed': result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'failed': len(result.failures)+len(result.errors),
        'skipped': len(result.skipped),
        'tests_run': result.testsRun,
        'duration_ms': int((time.monotonic()-started)*1000),
        'output': stream.getvalue(),
        'failure_details': [f'{case}: {text[-1200:]}' for case,text in (result.failures+result.errors)],
    }

def environment_pairs() -> tuple[tuple[str,str],...]:
    return tuple(sorted({
        'python':platform.python_version(),
        'implementation':platform.python_implementation(),
        'platform':platform.platform(),
        'machine':platform.machine() or 'unknown',
    }.items()))
