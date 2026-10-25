"""Developer-only isolated regression verifier (never part of gameplay execution).

The test inventory is discovered, not maintained by a stale allow-list. Each
bounded shard executes in its own Python interpreter to avoid stale global
state between unrelated test modules. A completed process with zero collected
tests is a failure rather than a false release pass.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import os
import signal
from pathlib import Path
import re
import subprocess
import sys
from tempfile import NamedTemporaryFile, TemporaryFile
from typing import Callable


class VerificationRejected(RuntimeError):
    def __init__(self, code: str, *, shard: int | None = None, modules: tuple[str, ...] = (),
                 output: str = '', completed: int = 0):
        self.code = code
        self.shard = shard
        self.modules = modules
        self.output = output[-1800:]
        self.completed = completed
        super().__init__(code)


@dataclass(frozen=True)
class VerificationSummary:
    status: str
    tests_passed: int
    test_files_discovered: int
    test_files_executed: int
    shards_completed: int
    shards_expected: int
    shard_tests: tuple[int, ...]
    resumed_modules: int = 0
    input_fingerprint: str = ''

    def to_dict(self) -> dict:
        return dict(status=self.status, tests_passed=self.tests_passed,
                    test_files_discovered=self.test_files_discovered,
                    test_files_executed=self.test_files_executed,
                    shards_completed=self.shards_completed,
                    shards_expected=self.shards_expected,
                    shard_tests=list(self.shard_tests), physical_input_sent=False,
                    resumed_modules=self.resumed_modules, input_fingerprint=self.input_fingerprint)


def discover_shards(test_dir: Path, *, shard_count: int = 8) -> tuple[tuple[str, ...], ...]:
    """Plan balanced shards covering every test file exactly once."""
    if not 1 <= shard_count <= 32:
        raise VerificationRejected('VERIFICATION_SHARD_COUNT_INVALID')
    if not test_dir.is_dir():
        raise VerificationRejected('VERIFICATION_TEST_DIRECTORY_MISSING')
    modules = []
    for path in sorted(test_dir.glob('test_*.py')):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise VerificationRejected('VERIFICATION_TEST_SOURCE_INVALID', modules=(path.stem,)) from exc
        count = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and
                    n.name.startswith('test_') for n in ast.walk(tree))
        # Do not silently omit empty or non-test modules from a release gate.
        if count < 1:
            raise VerificationRejected('VERIFICATION_EMPTY_TEST_MODULE', modules=(path.stem,))
        modules.append((path.stem, count))
    if not modules:
        raise VerificationRejected('VERIFICATION_NO_TEST_MODULES')
    groups: list[list[str]] = [[] for _ in range(min(shard_count, len(modules)))]
    weights = [0] * len(groups)
    for name, count in sorted(modules, key=lambda x: (-x[1], x[0])):
        i = min(range(len(groups)), key=lambda n: (weights[n], n))
        groups[i].append(name)
        weights[i] += count
    shards = tuple(tuple(sorted(names)) for names in groups)
    planned = [name for group in shards for name in group]
    if len(planned) != len(set(planned)) or set(planned) != {x[0] for x in modules}:
        raise VerificationRejected('VERIFICATION_TEST_COVERAGE_MISMATCH')
    return shards



# P37: A checkpoint is a convenience to resume a *specific immutable input
# inventory*, not proof of any new live/client behavior. Never skip a module
# merely because its name appears in a prior receipt.
_INPUT_TREES = ('src', 'tests', 'assets', 'config', 'reference', 'qualification',
                'examples', 'provenance', 'protocol_updates', 'tools')
_INPUT_FILES = ('pyproject.toml', 'requirements-p1.txt', 'requirements-windows-capture.txt',
                'PROJECT_INFO.txt', 'RELEASE_MANIFEST.json', 'README.md', 'IMPLEMENTATION_STATUS.md',
                '00_READ_FIRST_NEXT_CHAT.md', 'setup.bat', 'start.bat')
_CHECKPOINT_SCHEMA = 1


def verification_fingerprint(root: Path) -> str:
    """Bind a checkpoint to *all* relevant code, tests, fixtures and host runtime."""
    root = Path(root)
    digest = sha256()
    digest.update(('Python:' + sys.version + '\nExecutable:' + str(Path(sys.executable).resolve())).encode())
    for package in ('pydantic', 'pytest'):
        try:
            release = version(package)
        except PackageNotFoundError:
            release = 'NOT_INSTALLED'
        digest.update((package + ':' + release + '\n').encode())
    candidates = [root / x for x in _INPUT_FILES]
    for directory in _INPUT_TREES:
        tree = root / directory
        if tree.is_dir():
            candidates.extend(f for f in tree.rglob('*') if f.is_file() and
                              '__pycache__' not in f.parts and not f.name.endswith(('.pyc', '.pyo')))
    for path in sorted(set(candidates)):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode('utf-8') + b'\0')
        if not path.is_file():
            digest.update(b'ABSENT\0')
            continue
        digest.update(str(path.stat().st_size).encode('ascii') + b'\0')
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
    return digest.hexdigest()


def _checkpoint_read(path: Path, fingerprint: str, groups: tuple[tuple[str, ...], ...]) -> dict[str, int]:
    if not path.exists():
        return {}
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError) as exc:
        raise VerificationRejected('VERIFICATION_CHECKPOINT_UNREADABLE', output=str(exc)) from exc
    if not isinstance(state, dict) or state.get('schema_version') != _CHECKPOINT_SCHEMA:
        raise VerificationRejected('VERIFICATION_CHECKPOINT_INVALID')
    # A changed input tree invalidates *all* cached results. Re-run; do not
    # quietly import historic PASS as current evidence.
    if state.get('input_fingerprint') != fingerprint:
        return {}
    expected = {group[0] for group in groups}
    stored = state.get('completed')
    if not isinstance(stored, dict) or not set(stored).issubset(expected):
        raise VerificationRejected('VERIFICATION_CHECKPOINT_INVALID')
    for name, count in stored.items():
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise VerificationRejected('VERIFICATION_CHECKPOINT_INVALID')
    return dict(stored)


def _checkpoint_save(path: Path, fingerprint: str, completed: dict[str, int]) -> None:
    """Atomic fsync + replace; unfinished subprocesses are never recorded."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {'schema_version': _CHECKPOINT_SCHEMA, 'input_fingerprint': fingerprint,
               'status': 'INCOMPLETE_OR_REPLAYABLE',
               'completed': {key: completed[key] for key in sorted(completed)}}
    temp = None
    try:
        with NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                prefix='.verification-', suffix='.tmp', delete=False) as out:
            temp = Path(out.name)
            json.dump(payload, out, indent=2, sort_keys=True)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)



def run_bounded_tree(argv, *, cwd, env, text, capture_output, timeout):
    """Run one verification command with a hard process-family wall clock.

    Captured stdout/stderr deliberately use seekable temporary files rather than
    ``subprocess.PIPE``.  A test may start a descendant which inherits standard
    output and then let its immediate pytest/unittest parent exit.  With pipes,
    ``communicate(timeout=...)`` can remain blocked waiting for EOF from that
    orphan even though the process we are actually verifying already finished.
    A regular file has no EOF-owner lifetime, so ``wait(timeout)`` remains the
    sole wall-clock authority.  Any surviving POSIX process-group members are
    killed after the verified parent exits; timeout cleanup uses the same group.
    """
    if not capture_output:
        raise ValueError('VERIFICATION_REQUIRES_CAPTURED_OUTPUT')

    def read_capture(handle):
        try:
            handle.flush();handle.seek(0);raw=handle.read()
        except (OSError,ValueError):
            raw=b''
        if text:
            if isinstance(raw,bytes):return raw.decode('utf-8','replace')
            return str(raw)
        return raw if isinstance(raw,bytes) else str(raw).encode('utf-8','replace')

    def terminate_family(process):
        if os.name == 'nt':
            try:
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                               timeout=5,check=False)
            except (OSError,subprocess.TimeoutExpired):
                try:process.kill()
                except OSError:pass
        else:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass

    with TemporaryFile(mode='w+b') as stdout_file, TemporaryFile(mode='w+b') as stderr_file:
        kwargs=dict(cwd=cwd,env=env,stdout=stdout_file,stderr=stderr_file)
        if os.name == 'nt':
            kwargs['creationflags']=subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs['start_new_session']=True
        process=subprocess.Popen(argv,**kwargs)
        try:
            process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired,KeyboardInterrupt) as error:
            terminate_family(process)
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:process.kill();process.wait(timeout=2)
                except (OSError,subprocess.TimeoutExpired):pass
            stdout=read_capture(stdout_file);stderr=read_capture(stderr_file)
            if isinstance(error,KeyboardInterrupt):raise
            raise subprocess.TimeoutExpired(argv,timeout,output=stdout,stderr=stderr) from error
        else:
            # The verified parent is complete.  A POSIX descendant may still be
            # alive in the dedicated process group; remove it so one test cannot
            # leak work into the next module or keep release verification noisy.
            if os.name != 'nt':terminate_family(process)
            stdout=read_capture(stdout_file);stderr=read_capture(stderr_file)
            return subprocess.CompletedProcess(argv,process.returncode,stdout,stderr)


def verify_isolated(root: Path, *, shards: int = 8, per_shard_timeout: int = 120,
                    run: Callable | None = None, notify: Callable | None = None,
                    notify_start: Callable | None = None,
                    module_isolation: bool = False,
                    checkpoint_path: Path | None = None,
                    max_new_modules: int | None = None) -> VerificationSummary:
    if not 1 <= per_shard_timeout <= 600:
        raise VerificationRejected('VERIFICATION_TIMEOUT_INVALID')
    if max_new_modules is not None and not 1 <= max_new_modules <= 1000:
        raise VerificationRejected('VERIFICATION_BATCH_LIMIT_INVALID')
    if max_new_modules is not None and checkpoint_path is None:
        raise VerificationRejected('VERIFICATION_BATCH_REQUIRES_CHECKPOINT')
    run = run or run_bounded_tree
    groups = discover_shards(root / 'tests', shard_count=shards)
    if module_isolation:
        # One interpreter per module keeps historic slow/stalling cross-module
        # globals from disguising independently passing tests. The inventory
        # and exact method-count check below are unchanged.
        groups = tuple((name,) for group in groups for name in group)
    if checkpoint_path is not None and not module_isolation:
        raise VerificationRejected('VERIFICATION_CHECKPOINT_REQUIRES_MODULE_ISOLATION')
    fingerprint = verification_fingerprint(root) if checkpoint_path is not None else ''
    checkpoint_path = Path(checkpoint_path) if checkpoint_path is not None else None
    completed = (_checkpoint_read(checkpoint_path, fingerprint, groups)
                 if checkpoint_path is not None else {})
    # Before skipping any test, inspect its AST count. A manipulated count or
    # changed module is never trusted merely from checkpoint JSON.
    for group in groups:
        name = group[0]
        if name in completed:
            tree = ast.parse((root / 'tests' / f'{name}.py').read_text(encoding='utf8'))
            methods = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and
                          n.name.startswith('test_') for n in ast.walk(tree))
            if completed[name] != methods:
                raise VerificationRejected('VERIFICATION_CHECKPOINT_COUNT_MISMATCH', modules=(name,))
    resumed = len(completed)
    env = os.environ.copy()
    pythonpath = [str(root / 'src'), str(root / 'tests')]
    if env.get('PYTHONPATH'):
        pythonpath.append(env['PYTHONPATH'])
    env['PYTHONPATH'] = os.pathsep.join(pythonpath)
    tests_passed = 0
    executed = 0
    counts = []
    new_modules = 0
    for number, modules in enumerate(groups, 1):
        if checkpoint_path is not None and modules[0] in completed:
            counts.append(completed[modules[0]])
            tests_passed += completed[modules[0]]
            executed += 1
            continue
        if max_new_modules is not None and new_modules >= max_new_modules:
            break
        if notify_start is not None:
            notify_start(number, len(groups), modules)
        argv = [sys.executable, '-m', 'unittest', '-v', *modules]
        try:
            result = run(argv, cwd=root, env=env, text=True, capture_output=True,
                         timeout=per_shard_timeout)
        except subprocess.TimeoutExpired as exc:
            chunks = (exc.stdout or b'', exc.stderr or b'')
            tail = '\n'.join(v.decode('utf-8', 'replace') if isinstance(v, bytes) else str(v) for v in chunks)
            raise VerificationRejected('OFFLINE_TEST_SUITE_TIMEOUT', shard=number,
                                       modules=modules, output=tail, completed=executed) from exc
        except OSError as exc:
            raise VerificationRejected('VERIFICATION_LAUNCH_FAILED', shard=number,
                                       modules=modules, output=str(exc), completed=executed) from exc
        out = (result.stdout or '') + '\n' + (result.stderr or '')
        counts_found = re.findall(r'(?m)^Ran (\d+) tests? in ', out)
        expected_methods = 0
        for name in modules:
            tree = ast.parse((root/'tests'/f'{name}.py').read_text(encoding='utf8'))
            expected_methods += sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and
                                    n.name.startswith('test_') for n in ast.walk(tree))
        if (result.returncode != 0 or len(counts_found) != 1 or int(counts_found[0]) != expected_methods
                or not re.search(r'(?m)^OK(?: \(.*\))?$', out)):
            raise VerificationRejected('OFFLINE_TEST_SUITE_FAILED', shard=number,
                                       modules=modules, output=out, completed=executed)
        count = int(counts_found[0])
        counts.append(count)
        executed += len(modules)
        tests_passed += count
        new_modules += len(modules)
        if checkpoint_path is not None:
            completed[modules[0]] = count
            _checkpoint_save(checkpoint_path, fingerprint, completed)
        if notify is not None:
            notify(number, len(groups), count, len(modules))
    expected = sum(map(len, groups))
    if checkpoint_path is not None and verification_fingerprint(root) != fingerprint:
        raise VerificationRejected('VERIFICATION_INPUT_CHANGED_DURING_RUN', completed=executed)
    if executed != expected and max_new_modules is None:
        raise VerificationRejected('VERIFICATION_TEST_COVERAGE_MISMATCH', completed=executed)
    status = 'PASS' if executed == expected else 'INCOMPLETE'
    return VerificationSummary(status, tests_passed, expected, executed,
                               len(groups) if status == 'PASS' else executed, len(groups), tuple(counts),
                               resumed, fingerprint)
