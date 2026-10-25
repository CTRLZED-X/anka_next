# P52 — Multi-account socket/process topology (read-only, synthetic acceptance)

Date: 2026-10-21. Baseline: P51. **Not live-ready or game-authoritative.**

## Why this boundary matters

P51 detects contradictory Windows TCP owner rows and checks a process/window generation before counting an individual provisional socket hint. But the original aggregate receipt does not distinguish (a) two distinct candidate processes, (b) two TCP sockets owned by **one** client process, and (c) the **same** TCP socket listed under two candidate flow tokens. Therefore it cannot help assess how far a multi-client topology is from independently verifiable CRA/ENU ownership.

P52 introduces `anka_app.ingress_readiness.stable_multi_account_topology(...)` and a private candidate-evaluation helper. This **reuses**, not duplicates, P51's fail-closed matching criteria for both Win32 snapshots and both owner tables. The public P51 `stable_flow_hints(...)` interface and its privacy-safe response remain unchanged.

## Supported research output

- `CANDIDATES_ONLY` when the OS evidence is sufficiently well-formed to count *process candidates*, with reasons indicating incomplete/extra candidate processes, ambiguous owner rows, or candidate topology only.
- `BLOCKED_AMBIGUOUS` for repeated endpoint keys selected under distinct flow tokens. A repeated 4-tuple is not two independently proven sockets/accounts.
- `UNAVAILABLE` for malformed/stale/contradictory host scan data or input shape. Data is not promoted by optimistic defaults.
- Counts: provisional/ambiguous/unmatched flows, distinct candidate *processes*, multiple-socket candidate processes, configured expected clients. The counts do **not** identify characters.

Internally, candidate PIDs are ephemeral and used only to determine cardinality. Neither PIDs nor HWNDs, endpoints, source names, characters, process filenames, or flow tokens leave the audit as report fields. A single game process can own multiple sockets; this never counts as multiple independent game clients. Two process candidates **do not** establish ownership by CRA and ENU. Titles do not enter the correlation.

The module explicitly reports `account_binding_verified=false`, `current_build_certified=false`, `independent_character_witnesses=0`, `canonical_commits=0`, `actionable=false`, `physical_input_sent=false` for a candidate result. Unavailable/ambiguous results also cannot confer authority. The reader remains offline/synthetic; Windows API validation is still necessary.

## Verification

- 20 new adversarial tests covering alias selectors, contradictions in snapshots, PID reuse, executable and window geometry changes, incomplete inputs, two sockets per PID, missing/extra candidate processes, and private output.
- All 28 inherited P51 owner tests and 2 P51 preflight tests pass.
- Internal 3-scenario P52 smoke is run by existing `check` and `setup`. No additional operator BAT files.
- Complete P52 source-bound module-isolated regression inventory: **78/78 test files, 1,356 tests PASS**; source fingerprint and exact counts are in `verification/P52_offline_acceptance_receipt.json`.
- `check` and `setup`: exit 0. `start`: deliberately blocked with exit 40 (`LIVE_RUNTIME_NOT_IMPLEMENTED`); most recent diagnostic ZIP passed integrity verification.
- 13 architecture packages, 267 Python source modules and 165 reused reference assets passed preflight.

## Unresolved limitations and next milestone

This is **not** independent character evidence. Two non-atomic IPv4 owner snapshots cannot prove continuous TCP socket identity between timestamps, cannot detect every same-4-tuple reconnection, and cannot identify an account from a window title. Capture driver loss/IPv6 support, current-client semantic adapters and a verified character-to-process witness are absent. The correct next step is obtaining real Windows/current-client evidence and independently correlating process/window/socket with a witnessed character identity, then verifying actual gameplay fields; not claiming those are solved by P52.

No native plugin installed or compiled, no Windows game inputs, no authoritative Canonical commits, no changes to the game Kernel or historical source. Exactly `setup.bat` and `start.bat` are operator commands.
