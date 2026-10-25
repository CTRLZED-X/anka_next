# P65 — Interrupted Windows passive capture sealing and evidence integrity

**Date:** 2026-10-22. **Status:** full offline regression verified; Windows/Npcap/current-client acceptance unverified. Historical/live Canonical admission and input remain blocked.

## Reproduced P64 defect

P64 persisted optional, explicitly consented raw network frames to a bounded PCAPNG. Its normal stop closed the recorder correctly, but when `capture_bounded_sample` raised in a poll or its protocol consumer, its `finally: live.stop()` still finalized a PCAPNG without a loss marker. Likewise, a failing `AsyncSniffer.stop()` could finalize a seemingly normal zero-gap PCAPNG. Closing the source before it had started could also produce a clean-looking empty file. Existing uncertainty (`driver_loss_visibility=UNKNOWN`) remained, but those *known interrupted observation windows* were not durably represented.

Four of the original six P65 tests failed against unmodified P64, independently reproducing a nonexistent interruption guard and three wrongly clean finalized captures. The seventh test additionally checks stop before source start.

## Changes

- `WindowsLiveCapture.mark_capture_interrupted()` seals a failed observation window in the existing `ConsentedPcapngRecorder`; repeated calls are ignored for the same source.
- `capture_bounded_sample()` marks interruption before cleanup when a capture poll, transport audit, downstream wire consumer, or other sampling step raises. The original exception is still raised; no private exception detail enters the recording receipt.
- `WindowsLiveCapture.stop()` marks the recording incomplete when the sniffer cannot stop successfully and when stop occurs before a capture ever started. All paths still close the queue and recorder.
- The recorder writes a positive PCAPNG interface drop count on interruption. P62's existing PCAPNG reader then rejects that saved file as incomplete evidence.
- The existing automatic `check` and `setup` synthetic evidence-recorder smoke now runs three cases, including an interrupted polling window. No new user BAT command, dashboard, or mode is created.

## Contract and safety limitations

These are **integrity improvements to optional local research evidence**, not current-client certification. A recording with zero known gaps is still only `RECORDED_UNCERTIFIED` because Scapy/Npcap driver loss visibility is `UNKNOWN`. Incomplete recordings remain private and must not be promoted into Canonical state or used to authorize physical input. Raw PCAPNG frames are never embedded into incident or release ZIPs. No Windows Npcap session was run by this milestone.

## Verification

- Seven P65 adversarial methods pass, including polling/consumer failures, failed sniffer shutdown, premature stop, normal shutdown, failed start, and idempotent abort.
- Focused P26/P27/capture-live/P64/P65 group: 98 pytest tests plus 37 subtests PASS.
- Source-bound module-isolated full regression: **92/92 modules, 1,580/1,580 tests PASS**. The slow P37 verifier also passed on its own and within the complete checkpoint.
- Normal `check` / `setup`: exit 0 with three-case P65-integrated recorder smoke.
- `start`: expected exit 40 `LIVE_RUNTIME_NOT_IMPLEMENTED`; incident ZIP `verify_incident` PASS.
- Release must preserve all 595 P64 ZIP entries, keep a single `ANKA_NEXT/` top-level folder, include exactly `setup.bat` and `start.bat` at root, exclude runtime/evidence, runtime/runs, verification checkpoints and Python caches.

## Next acceptance priority

Run an explicitly consented bounded capture on the real Windows/Npcap host, document capture start/stop reliability and raw-file location privately, then verify current-build protocol semantics and independent process/window/socket/character identity. A saved packet capture cannot independently establish driver completeness or gameplay authority.
