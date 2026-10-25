# M12_003 — Live-readiness concurrency and authority hardening

`ANKA_NEXT_M12_003` is a pre-live systemic hardening release. It does **not** grant current-client or physical-input acceptance. Its purpose is to eliminate races and stale-authority paths that could otherwise turn Q10/Q11/Q12 into repeated live-test cycles.

## Root causes hardened

- **Process-generation TOCTOU before passive capture:** Dofus PID/process-generation stability is rechecked before starting the sniffer; a recycled/restarted process aborts the sample.
- **Mixed config/release evidence:** `start` loads one effective config, binds host/capture observations to it, then revalidates both config SHA and release-manifest SHA after the bounded observation. A mid-run edit invalidates the whole acceptance attempt.
- **Competing ANKA starts:** Windows uses a kernel named mutex for one host-wide `start` authority. A crash releases the handle automatically; a second start fails closed rather than observing/controlling the same clients concurrently.
- **Capture callback/shutdown race:** live capture now has explicit start/quiesce state serialization. Concurrent `stop()` callers wait for the single sniffer shutdown before evidence can be sealed.
- **Mutable-owner races:** Capture transport assembly, transport auditing, Protocol observation/decoder transactions/registry, Canonical writing, Coordination, and Workflow now have explicit serialization at their mutable ownership boundaries.
- **Win32 mixed-generation snapshot:** the process handle stays live for the complete window observation and HWND→PID is rechecked before acceptance.
- **Future physical-scope staleness:** an enabled Windows input scope must be bound to the exact release manifest, effective config, Q12 acceptance receipt, run id/generation, exact build and action kinds. The driver is still uncomposed.
- **Input-arbiter failures:** acquire/release corruption is a run-level safety fault. The Execution service disarms and requires reconstruction rather than continuing.
- **Operator interrupt:** Ctrl+C exits 130 with `INTERRUPTED` diagnostics and explicit `NOT_SENT` physical-input evidence.

## Verification added

`tests/test_m12_003_live_readiness_hardening.py` permanently covers the new races and fences, including concurrent shutdown, Protocol serialization, Canonical concurrent duplicate commits, Coordination/Workflow serialization, run-authority exclusivity, config/release drift, Windows identity generation drift, and safe interruption.

The M12 release gate includes this suite so these protections cannot silently disappear in a future package.

## Remaining evidence gates

This release is the maximum offline/live-preparation scope. It still requires:

1. **Q10:** clean Windows host/setup/start acceptance.
2. **Q11:** current Dofus build observe-only capture/protocol/identity evidence.
3. **Q12:** one physical action scope at a time, accepted from current evidence.
4. **Q13:** bounded CRA+ENU mission acceptance.

Unknown current-client semantics, missing identity/loadout/calibration proof, or ambiguous physical side effects remain blockers, never guessed facts.
## Final M12_003 offline verification

The frozen M12_003 implementation was verified after all concurrency/authority hardening and retained-regression fixture updates. The broad sweep covered **all 113 top-level test files** and passed **1,859 tests plus 707 subtests**. Definitive Q0–Q9 gates all pass on one implementation source hash; M12 passes with **50 tests + 2 subtests**, **13 packages / 355 modules / 0 architecture violations**, and **0 physical-input attempts**.

This is the maximum evidence-backed offline/pre-live state. It is **not** a claim of Windows/current-client/live-action acceptance. Q10–Q13 remain evidence-gated.

