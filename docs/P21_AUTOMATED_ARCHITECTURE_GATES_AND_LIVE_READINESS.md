# P21 — Automated system boundaries and evidence-based readiness

## Purpose

Strengthen the foundation of ANKA_NEXT without adding a dashboard, operator commands,
physical-input code, or invented protocol compatibility. The user still has only
`setup.bat` and `start.bat`.

## Source changes

- `src/anka_app/architecture_guard.py` encodes the 13-package allow-list (11
  independent runtime systems, shared contracts and the composition package),
  and scans Python source through `ast` without importing packages. Missing,
  unknown, syntactically broken and statically forbidden cross-system imports
  fail the audit. Constant-string `importlib.import_module` and `__import__`
  calls are also examined. Dynamic imports assembled at runtime cannot be
  conclusively audited statically, so this is a strong but not exhaustive check.
- `src/anka_app/readiness.py` identifies unresolved production gates; it does
  not accept evidence or provide a grant/promote function. Passing synthetic
  tests cannot enable physical input.
- `setup` performs preflight (including the preserved kernel), architecture
  boundary audit, live-readiness reporting and a small offline handoff smoke.
- `start` performs light preflight, architecture boundary audit and records
  nine explicit live-readiness blockers; it intentionally stops rather than
  loading the whole kernel and replaying synthetic fights each time.
- The **full nine-case historical synthetic regression matrix** runs through
  the developer test suite; expected first-failure reasons are an independent
  oracle, rather than blindly accepting any `BLOCKED` result.
- `tests/test_p21_architecture_readiness.py` tests the checker by inserting
  forbidden imports, bad syntax, unreviewed packages, a relative escape and
  forged readiness; also tests both operator flows.

## Explicit non-goals

This milestone does not create current-client semantics, actual live Canonical
admission, verified physical account-window bindings, real movement/casting,
server-confirmed action outcomes, or 200-zone acceptance. The existing fake
execution and synthetic fight tests remain isolated and non-actionable.

The architecture checker is a Python static audit, not a sandbox/security
boundary. It cannot see runtime-generated imports or prove third-party code
safe. Any future live-input path requires separate authority and current-client
acceptance; this milestone grants none.

## Operator commands

Only `setup.bat` and `start.bat` remain at the root. The new checks run
internally. On a failed start, `runtime/runs/<run-id>/` contains a bounded
trace and incident report with the unresolved readiness blockers.

## Acceptance and verification

Acceptance requires all of:

1. The complete inherited+P21 test suite finishes with zero failures.
2. The archive is extracted cleanly and its own test suite passes.
3. `setup` succeeds only when architecture, assets, configuration and synthetic
   smoke tests pass; a forbidden import must cause a failure.
4. `start` fails closed and clearly identifies the outstanding live gates.
5. No new root BAT command, dashboard, physical input, live authority or
   unreconciled dependency is introduced.

Open restrictions: Windows command interpreter and Npcap cannot be certified in
this Linux development environment. Current protocol-build evidence is absent.
The test runner has a history of occasional long-running subprocesses; a
passing focused test must never be presented as full release certification.
