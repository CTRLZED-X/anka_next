# P24 — Isolated verification and transparent release diagnostics

## Scope
This milestone improves the **developer's release gate**, not the game-runtime semantics. It is intentionally integrated into the existing `anka_app` composition layer rather than a new independent runtime system. It does **not** add operator batch commands or enable any input driver.

## Verified problem in P23
The single-process `unittest discover` could stall intermittently and had one global 150-second limit. An incomplete run could conceal which module/test was still running and forced later milestone receipts to rely on manually batched test groups. Passing individual groups was meaningful, but there was no **automatic, exhaustive, fail-closed per-group release gate**.

## Implementation
- `anka_app.verification_runner`: discovers all `tests/test_*.py` files and parses each with `ast`; missing, invalid and testless modules fail the gate. Adds newly named test files automatically.
- Deterministic, 8-shard, approximately count-balanced partition; each module is assigned **exactly once**.
- Each shard runs in a fresh Python subprocess with explicit `PYTHONPATH`, bounded execution time, nonzero-exit rejection and recorded last test output.
- A passing `unittest` process is not sufficient: the observed `Ran N tests` must exactly equal the number of static test methods in its assigned modules. A zero-test “OK” or missing completion footer fails.
- `anka_app.cli verify` (internal developer use; **not** a new BAT command) emits `verification.shard_started`, `verification.shard_passed`, and a completion or failure event with precise shard/module names and last test output, for GPT-friendly investigation.
- One legacy P18 verifier regression test was updated to inject errors at the new verifier boundary without reducing the number or intent of inherited tests.

## Threat model and limitations
- Process isolation prevents some cross-module Python global-state interference; it does not prove that no timing-related or resource-related stalls remain.
- A per-shard timeout distinguishes a hung shard and returns an explicit failure; a timeout is **never** converted into a passing result.
- The AST count is an additional undercollection check for this suite, not a general-purpose guarantee for dynamically generated test suites.
- Windows batch commands were not executed on a Windows machine, and Windows/Npcap/current-client evidence is still missing.
- It is still possible for subprocess/grandchild cleanup or host execution to behave differently on Windows. Windows acceptance remains a separate gate.
- The old game kernel, calibration assets, protocol research and safety barriers are unchanged.

## Tests and release expectations
- New P24 tests cover complete file inventory, real isolated subprocesses, process timeout with last output, zero-test false success, missing or malformed source, undercollection, shard-start tracking and incident detail propagation.
- Inherited tests must pass, and the package's `setup` must pass with **only `setup.bat` and `start.bat`** present as operator commands.
- `start` must continue to report `LIVE_RUNTIME_NOT_IMPLEMENTED` with exit code 40 and automatic incident evidence.
- Full P24 tests verified in isolated groups are an **offline release gate only**. They do not certify live gameplay or the current Dofus protocol.

## Next genuinely high-value step
Windows evidence collection and exact-client protocol qualification; authoritative game state cannot be promoted until those are independently proven. Avoid creating new demo tools or tactical scoring layers instead of closing those live gates.
