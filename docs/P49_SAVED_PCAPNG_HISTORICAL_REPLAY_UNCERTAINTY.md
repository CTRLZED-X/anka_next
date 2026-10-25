# P49 — Saved PCAPNG → Historical Research Replay, Without False Capture Proof

**Status:** Implemented and verified through focused offline tests, 21 October 2026.  
**Baseline:** P48 complete replacement ZIP; **no source modification to original R5.198**.  
**Live game status:** Explicitly BLOCKED. **No** modern client adapter, authoritative Canonical commits or physical input.

## Reason and threat model

P48 could combine real `CapturePoll`/TCP chunks with the P45/P46 historical fight decoder, but a future investigator with an ordinary saved `.pcapng` needed to reconstruct an equivalent `CapturePoll` and might inadvertently mark its packet-loss visibility `AVAILABLE_CLEAN`. **A PCAPNG file, even with valid SYNs and no visible TCP gaps, does not contain a trusted capture-driver dropped-packet counter or current account/window binding.** It must not be turned into complete or authoritative evidence by the conversion.

P49 adds one **application composition entry point** to connect the existing P4 PCAPNG parser and P48 historical replay, explicitly preserving that missing proof. It recovers research observations where byte framing is coherent while every resulting file report remains `BLOCKED_EVIDENCE`.

## Implemented source and exact contracts

- `src/anka_app/historical_pcapng_bridge.py`: `inspect_historical_pcapng(path, root, ports, scope)` returns immutable `HistoricalPcapngResearch`. It first uses existing bounded `inspect_pcapng`, rereads the same file and checks the entire original SHA-256 and selected segment count; changed evidence is rejected. It converts at most 100,000 selected segments into bounded `CapturePoll` objects of at most 4,096 segments, using **`driver_drop_visibility='UNKNOWN'`**. It never adds a receipt claiming an independently verified account, source completeness, current build, Canonical commits or input.
- `src/anka_app/historical_transport_bridge.py`: additive, default-off `forensic_without_driver_proof=True`. This permits *read-only decoding* of unknown-driver-loss capture polls **only** when no dropped or overflowed packets were reported, poll generation is consistent, order and SYN continuity are observed, the final poll is exhausted, and the transport audit found no gaps. The hard blocker `P48_CAPTURE_LOSS_OR_DRIVER_VISIBILITY_UNKNOWN` stays in force. A corrupt frame, unsupported client build or wrong scope still fails. Normal P48 behavior stays unchanged when flag omitted.
- `src/anka_app/historical_pcapng_offline.py`: tiny fully synthetic PCAPNG fixture used by the existing `check`/`setup` preflight. It verifies that plausible round/turn/fight-boundary research is produced *while authority and driver proof remain false*. It does not install a capture driver, read live game data or write any packet bodies to diagnostic bundles.
- `src/anka_app/cli.py`: automatically includes that read-only P49 smoke during `check` and `setup`; no new user command or BAT launcher.
- `tests/test_p49_pcapng_capture_research.py`, `tests/test_p49_pcapng_setup_smoke.py`: positive and adversarial test oracles based on independent packet fixtures.

### Safety semantics

| Observable condition | Result | What it does **not** prove |
|---|---|---|
| Valid old-build PCAPNG with SYN and framed `jvj` / `jup` / `jwp` | Historical research observations, **BLOCKED_EVIDENCE** | Full packet completeness, CRA/ENU account, damage, fight victory or click authority |
| Packet-driver loss counters unavailable | **P49_DRIVER_LOSS_AND_ACCOUNT_PROOF_MISSING** | Never `AVAILABLE_CLEAN`; no authoritative promotion |
| Wrong named flow or zero selected flow | **P49_NO_SELECTED_FLOW_PROOF**, 0 relevant observations | Caller-supplied flow digest is not independently attested |
| Bad build/invalid wire/unknown game message | Blocked or explicitly partial underlying protocol research | Cannot silently omit malformed or unclassified messages |
| PCAPNG changed across inspection and parsing | **P49_CAPTURE_CHANGED**, no replay | Two versions of the file cannot be combined |
| Missing/corrupt file, invalid ports or invalid scope | Typed blocked reason, no raw path/payload in report | No exception-based guessed success |
| Explicit dropped/overflowed live poll, even with forensic flag | No historical decoding, **BLOCKED_EVIDENCE** | Debug flag cannot waive known evidence loss |

The nested `HistoricalTransportResearch` status and timeline carry the precise wire/framing research diagnoses, but the outer file-level result **always** reports `BLOCKED_EVIDENCE`. This is intentional; generic source files cannot attest driver, process or current-build truth. Do not interpret a decoded historical message as a production event.

## Tests actually run on the final implementation

- `tests/test_p49_pcapng_capture_research.py` + `tests/test_p49_pcapng_setup_smoke.py` + both P48 test modules: **31 tests and 6 subtests passed**.
- Twenty-two selected P4/P6/P23/P28/P29/P31/P40/P42/P43/P44–P49 test modules: **342 tests and 119 subtests passed**.
- Ten selected diagnostic/bootstrap/architecture/lifecycle/P45–P49 modules: **128 tests and 32 subtests passed**. These groups overlap; **do not sum their totals**.
- `python -m anka_app.cli check`: PASS, 13 package boundaries, 165/165 reused assets, and automatic P49 forensic smoke.
- `python -m anka_app.cli setup`: PASS, including P49 and the existing offline integrity/mission smokes.
- `python -m anka_app.cli start`: **intentionally returns exit code 40 / `LIVE_RUNTIME_NOT_IMPLEMENTED`**. The generated incident ZIP passed `verify_incident`.
- Combined inherited test-suite attempt: **INCOMPLETE due to outer tool time limit/stall around early progress**. No all-modules PASS claim. Prior P48 receipts remain historical evidence only.

This is a non-Windows offline environment. No real driver-drop counters, Npcap ownership, Windows process/HWND binding, current Dofus client, BepInEx build or independent gameplay witness was supplied or tested.

## Current readiness and next substantive gate

The captured-file-to-research pipeline is now integrated with the *existing* capture/parser and historical fight decoders. **The principal remaining work cannot be completed by adding more synthetic evidence assertions**: obtain an explicitly authorized, current-build PCAPNG and independently witnessed account/fight/turn/resource/settlement observations, then qualify exact build, account-to-flow scope, every required Canonical capability and real Windows client projection. Production Canonical admission and physical input remain separate, protected milestones. The estimated roadmap scope is still **92%** (subjective historical estimate); real end-to-end CRA/ENU live-fight acceptance remains **0%**.

**Operator interface remains exactly `setup.bat` and `start.bat`.** All P49 diagnostics remain local, read-only and privacy-aware. No separate continuation handoff file was created.
