"""Definitive architecture-boundary audit.

The audit is intentionally stdlib-only so setup/start can run it before optional
runtime dependencies.  It enforces package imports, detects common dynamic-import
bypasses, reports the top-level dependency graph/SCCs, and checks that obvious OS
input primitives do not appear outside the sole Execution authority.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

SYSTEM_IMPORTS: dict[str, frozenset[str]] = {
    'anka_contracts': frozenset(),
    'anka_game_kernel': frozenset(),
    'anka_client': frozenset({'anka_contracts'}),
    'anka_capture': frozenset({'anka_contracts'}),
    'anka_protocol': frozenset({'anka_contracts'}),
    'anka_canonical': frozenset({'anka_contracts'}),
    'anka_live_state': frozenset({'anka_contracts'}),
    'anka_decision': frozenset({'anka_contracts', 'anka_game_kernel'}),
    'anka_coordination': frozenset({'anka_contracts'}),
    'anka_workflow': frozenset({'anka_contracts'}),
    'anka_execution': frozenset({'anka_contracts'}),
    'anka_observability': frozenset({'anka_contracts'}),
    'anka_app': frozenset({
        'anka_contracts', 'anka_game_kernel', 'anka_client', 'anka_capture',
        'anka_protocol', 'anka_canonical', 'anka_live_state', 'anka_decision',
        'anka_coordination', 'anka_workflow', 'anka_execution', 'anka_observability',
    }),
}

# One explicit owner per mutable authority.  This table is itself audited and is
# also useful in machine-readable Q1 receipts.
AUTHORITY_OWNERS: dict[str, str] = {
    'wire_continuity': 'anka_capture',
    'wire_semantics': 'anka_protocol',
    'canonical_history': 'anka_canonical',
    'current_state_semantics': 'anka_live_state',
    'game_mechanics': 'anka_game_kernel',
    'proposed_actions': 'anka_decision',
    'physical_input_and_settlement': 'anka_execution',
    'party_turn_permit': 'anka_coordination',
    'mission_run_phase': 'anka_workflow',
    'client_window_projection': 'anka_client',
    'diagnostic_evidence': 'anka_observability',
    'composition_lifecycle': 'anka_app',
}

# These calls would be direct physical-input authority if present in Python.
# They may appear only under anka_execution. Window observation APIs are not here.
PHYSICAL_INPUT_MODULES = frozenset({
    'pyautogui', 'pydirectinput', 'pynput', 'keyboard', 'mouse',
})

PHYSICAL_INPUT_PRIMITIVES = frozenset({
    'SendInput', 'mouse_event', 'keybd_event', 'SetCursorPos',
    'SetForegroundWindow', 'SetActiveWindow', 'SetFocus', 'PostMessageW', 'SendMessageW',
    'click', 'press', 'keyDown', 'keyUp', 'moveTo',
})


@dataclass(frozen=True)
class ArchitectureAudit:
    packages: int
    modules: int
    violations: tuple[str, ...]
    edges: tuple[str, ...] = ()
    strongly_connected_components: tuple[tuple[str, ...], ...] = ()
    dynamic_import_sites: tuple[str, ...] = ()
    authority_owners: tuple[tuple[str, str], ...] = ()

    @property
    def status(self) -> str:
        return 'PASS' if not self.violations else 'FAIL'

    def to_dict(self) -> dict:
        return {
            'status': self.status,
            'packages': self.packages,
            'modules': self.modules,
            'violations': list(self.violations),
            'edges': list(self.edges),
            'strongly_connected_components': [list(x) for x in self.strongly_connected_components],
            'dynamic_import_sites': list(self.dynamic_import_sites),
            'authority_owners': dict(self.authority_owners),
        }


def _scc(graph: dict[str, set[str]]) -> tuple[tuple[str, ...], ...]:
    """Tarjan SCCs, returning only real cycles (>1 node or self-loop)."""
    index=0; stack=[]; on_stack=set(); indices={}; low={}; cycles=[]
    def visit(v: str) -> None:
        nonlocal index
        indices[v]=low[v]=index; index+=1; stack.append(v); on_stack.add(v)
        for w in sorted(graph.get(v, ())):
            if w not in indices:
                visit(w); low[v]=min(low[v],low[w])
            elif w in on_stack:
                low[v]=min(low[v],indices[w])
        if low[v]==indices[v]:
            comp=[]
            while True:
                w=stack.pop(); on_stack.remove(w); comp.append(w)
                if w==v: break
            comp=sorted(comp)
            if len(comp)>1 or (len(comp)==1 and comp[0] in graph.get(comp[0],set())):
                cycles.append(tuple(comp))
    for v in sorted(graph):
        if v not in indices: visit(v)
    return tuple(sorted(cycles))


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name): return node.func.id
    if isinstance(node.func, ast.Attribute): return node.func.attr
    return None


def audit_source_boundaries(src: Path) -> ArchitectureAudit:
    """Enforce code-level imports and basic authority constraints without imports."""
    src=Path(src); failures=[]; dynamic_sites=[]; edge_set=set()
    names={p.name for p in src.iterdir() if p.is_dir() and p.name.startswith('anka_')} if src.is_dir() else set()
    for name in sorted(set(SYSTEM_IMPORTS)-names): failures.append(f'ARCH_PACKAGE_MISSING:{name}')
    for name in sorted(names-set(SYSTEM_IMPORTS)): failures.append(f'ARCH_UNREVIEWED_PACKAGE:{name}')
    if set(AUTHORITY_OWNERS.values())-names:
        failures.append('ARCH_AUTHORITY_OWNER_PACKAGE_MISSING')

    inspected=0
    for package in sorted(names):
        for path in sorted((src/package).rglob('*.py')):
            inspected+=1; relative=path.relative_to(src).as_posix()
            try: root=ast.parse(path.read_text(encoding='utf-8'),filename=relative)
            except (SyntaxError,UnicodeError,OSError) as error:
                failures.append(f'ARCH_SOURCE_UNREADABLE:{relative}:{type(error).__name__}'); continue

            importlib_aliases={'importlib'}; import_module_aliases=set()
            for node in ast.walk(root):
                if isinstance(node, ast.Import):
                    for item in node.names:
                        if item.name=='importlib': importlib_aliases.add(item.asname or 'importlib')
                elif isinstance(node, ast.ImportFrom) and node.module=='importlib':
                    for item in node.names:
                        if item.name=='import_module': import_module_aliases.add(item.asname or item.name)

            for node in ast.walk(root):
                targets=[]
                if isinstance(node,ast.Import):
                    targets=[item.name.split('.')[0] for item in node.names]
                    if package!='anka_execution':
                        for target in targets:
                            if target in PHYSICAL_INPUT_MODULES:
                                failures.append(f'ARCH_INPUT_MODULE_BYPASS:{relative}:{node.lineno}:{target}')
                elif isinstance(node,ast.ImportFrom):
                    if node.level:
                        # Relative imports are legal only within the owning package.
                        parts=path.relative_to(src).parts[:-1]
                        if node.level>len(parts): failures.append(f'ARCH_RELATIVE_ESCAPE:{relative}:{node.lineno}')
                        continue
                    targets=[(node.module or '').split('.')[0]]
                    if package!='anka_execution' and targets[0] in PHYSICAL_INPUT_MODULES:
                        failures.append(f'ARCH_INPUT_MODULE_BYPASS:{relative}:{node.lineno}:{targets[0]}')
                elif isinstance(node,ast.Call):
                    is_dynamic=False
                    fn=node.func
                    if isinstance(fn,ast.Name) and (fn.id=='__import__' or fn.id in import_module_aliases): is_dynamic=True
                    elif isinstance(fn,ast.Attribute) and fn.attr=='import_module' and isinstance(fn.value,ast.Name) and fn.value.id in importlib_aliases: is_dynamic=True
                    elif isinstance(fn,ast.Call) and isinstance(fn.func,ast.Name) and fn.func.id=='getattr':
                        # getattr(importlib_alias, 'import_module')(...)
                        args=fn.args
                        if len(args)>=2 and isinstance(args[0],ast.Name) and args[0].id in importlib_aliases and isinstance(args[1],ast.Constant) and args[1].value=='import_module':
                            is_dynamic=True
                    if is_dynamic:
                        dynamic_sites.append(f'{relative}:{node.lineno}')
                        if node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str):
                            targets=[node.args[0].value.split('.')[0]]
                        else:
                            failures.append(f'ARCH_DYNAMIC_IMPORT_NON_LITERAL:{relative}:{node.lineno}')
                    # Direct physical input primitives outside Execution are forbidden.
                    call=_call_name(node)
                    if package!='anka_execution' and call in PHYSICAL_INPUT_PRIMITIVES:
                        # Avoid false-positive ordinary object .click() by requiring a known bare
                        # primitive or known module-ish receiver for generic names.
                        definite=isinstance(node.func,ast.Name) or call in {
                            'SendInput','mouse_event','keybd_event','SetCursorPos',
                            'SetForegroundWindow','SetActiveWindow','SetFocus','PostMessageW','SendMessageW'}
                        if isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id in {'pyautogui','mouse','keyboard','win32api','user32'}:
                            definite=True
                        if definite: failures.append(f'ARCH_INPUT_AUTHORITY_BYPASS:{relative}:{node.lineno}:{call}')

                for target in targets:
                    if target in names and target!=package:
                        edge_set.add((package,target))
                        if target not in SYSTEM_IMPORTS.get(package,frozenset()):
                            failures.append(f'ARCH_FORBIDDEN_IMPORT:{relative}:{node.lineno}:{package}->{target}')

    graph={name:set() for name in names}
    for a,b in edge_set: graph[a].add(b)
    cycles=_scc(graph)
    for comp in cycles: failures.append('ARCH_DEPENDENCY_CYCLE:'+','.join(comp))
    edges=tuple(f'{a}->{b}' for a,b in sorted(edge_set))
    return ArchitectureAudit(
        len(names),inspected,tuple(sorted(set(failures))),edges,cycles,
        tuple(sorted(set(dynamic_sites))),tuple(sorted(AUTHORITY_OWNERS.items())),
    )
