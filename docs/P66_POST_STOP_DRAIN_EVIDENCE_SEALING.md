# P66 — Final buffered-drain evidence sealing

**Date:** 2026-10-22. **Status:** verified offline; real Windows/Npcap/current-client acceptance **not verified**. No gameplay control or current-build Canonical admission.

## Reproduced P65 defect

`capture_bounded_sample()` called `WindowsLiveCapture.stop()` **before** auditing the final queued `CapturePoll` objects. `stop()` finalized the consented PCAPNG immediately. When post-stop `poll()`, `LiveCaptureAudit.observe()`, or the `on_poll()` protocol consumer failed, P65's `mark_capture_interrupted()` ran only after the file was already closed. The recording could incorrectly remain `RECORDED_UNCERTIFIED` with zero recorded gaps, despite a known incomplete downstream observation window. Tests reproduced four failures plus one missing split-shutdown method against unmodified P65.

## Changes and exact contract

- Introduced `WindowsLiveCapture.quiesce()` to stop the Npcap sniffer and close its in-memory queue **without sealing optional PCAPNG evidence**. A stop failure still marks the recording interrupted and raises.
- `capture_bounded_sample()` quiesces the source, drains every buffered poll through the transport auditor and optional protocol consumer, and **only then** finalizes via existing `stop()` in `finally`. It retains a fallback for mock/legacy sources that do not offer `quiesce()`.
- Exceptions during the final drain mark the still-open recorder incomplete; its final PCAPNG includes a positive loss counter and is rejected by the existing P62 PCAPNG parser.
- The traditional direct `WindowsLiveCapture.stop()` still performs the full shutdown and recorder close. Quiescing then calling `stop()` is idempotent, including interruption marking. Recorder output remains bounded, local and consent gated.
- `check` and `setup` now exercise a fourth deterministic synthetic evidence-recording smoke scenario: post-stop consumer failure. No additional operator commands are introduced.

**Correct sequencing:** `start → sampling → quiesce sniffer → close queue → drain + audit + consumer → stop/finalize recorder → privacy-safe receipt`.

## Verification

- Six new P66 tests, including post-stop consumer/poll/auditor failures, successful-drain finalization ordering, direct-stop compatibility and idempotent quiesce+abort.
- Focused P64–P66 / inherited capture regressions: **78 pytest tests + 29 subtests PASS**.
- Complete source-fingerprinted, module-isolated regression suite: **93/93 modules and 1,586/1,586 unittest methods PASS**. The P37 slow verifier self-test independently passed and is included in the exact-source checkpoint.
- `check` / `setup`: both exit **0**, now reporting four synthetic recorder smoke cases.
- `start`: intentionally exits **40** with `LIVE_RUNTIME_NOT_IMPLEMENTED`; incident ZIP verifies using the existing bundle-integrity tool.
- Architecture: **13 packages**, zero source-boundary violations; reused reference asset checks **165/165**.

## Hard boundaries and next acceptance

These are file-evidence integrity guarantees, **not evidence of complete driver capture**. Pcap recording is opt-in, uses `config/user.json` `capture.save_raw_evidence`, and stores sensitive packet bytes only in ignored local `runtime/evidence/`. Normal receipts retain `driver_loss_visibility='UNKNOWN'`. A clean saved file still cannot prove current-client protocol semantics, player/character/breed identity, completed gameplay or authoritative Canonical state. The gameplay `start` path remains blocked. The next acceptance step requires an operator-controlled real Windows/Npcap test and independent current-build/identity evidence, not a synthetic declaration.
