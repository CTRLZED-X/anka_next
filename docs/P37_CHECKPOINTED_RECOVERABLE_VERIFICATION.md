# P37 — Crash-resumable module verification and bounded subprocess trees

**Scope:** reliability of the offline verification infrastructure. This milestone does **not** add network semantic evidence, production Canonical admission, a current-build adapter or real physical input. The project remains intentionally live-blocked.

## Why

P35–P36 repeatedly exceeded the outer environment test-run limits: once interrupted, the verifier discarded all prior module results and made the same expensive modules run again. Some tests launch a second Python CLI, meaning inherited stdout/stderr descriptors can keep a `subprocess.run` parent waiting even when its initial child exits. Falsely counting an interrupted suite as passed would worsen the original recurring bug cycle.

## Implemented

- `anka_app.verification_runner.verification_fingerprint(root)` records a SHA-256 over relevant source, tests, tools, configuration, static assets, research references, evidence fixtures and release files, plus Python runtime and installed pytest/pydantic versions. Runtime logs and generated caches are excluded. **Any changed relevant input invalidates every resumed module.** The fingerprint is a reproducibility guard, not a cryptographic signature against a deliberately malicious local editor.
- Isolated module verification can atomically checkpoint passed module names and exact discovered unittest method counts after each subprocess. Incomplete / killed module is *never* recorded as PASS. Resume skips only verified modules with the same fingerprint. Malformed/corrupt checkpoints and inconsistent method counts are rejected.
- `verify_isolated(..., checkpoint_path=..., module_isolation=True, max_new_modules=N)` supports small batches for environments with strict external execution limits. A partial batch returns **`INCOMPLETE`**, never `PASS`. The normal developer `python -m anka_app.cli verify` uses a local runtime checkpoint and continues until all discovered modules have completed; no extra user-facing BAT launcher was created.
- `run_bounded_tree` starts each verification subprocess in a new process group on POSIX and a new group on Windows; on timeout it attempts to terminate the whole group/tree and reports the exact stalled module. This addresses pipe inheritance and child process leakage. **Windows process-tree cleanup and OS-level behavior still require real Windows acceptance; `taskkill` is best-effort if the root PID has already exited.**
- Existing module-isolation and grouped verification modes preserve their public summaries. No gameplay action, protocol mapping, Kernel rules, Canonical state or input authority was changed.

## Tests actually run

- New `tests/test_p37_checkpointed_verification.py`: **11 tests**, including interruption recovery, source/test/config/fixture invalidation, corrupt/fake checkpoint, partial batch status, negative missing checkpoint and POSIX inherited-pipe timeout.
- Focused P24/P33/P34/P35/P36/P37 plus protocol architecture regression: **153 tests PASS** with independent `unittest` execution.
- `anka_app.cli check`: **PASS**, 13 packages / 247 inspected Python modules; **165/165** existing source assets verified; read-only non-Windows host.
- `anka_app.cli setup`: **PASS**, synthetic integration and research smoke only; no canonical production authority.
- `anka_app.cli start` (15-second externally bounded run): intentional `LIVE_RUNTIME_NOT_IMPLEMENTED`, exit **40**, produces a sanitized incident ZIP; no real input. An earlier unbounded sequential command timed out during `start`, so the bounded check is the independent startup evidence for this milestone.
- Attempted full 54-module checkpointed run: **INCOMPLETE**, outer command execution timeout, checkpoint retained 10 passed modules before the next module started. Their prior run results are not a complete project pass. Separate `test_protocol_architecture` (the module next in the timed-out run) independently passed 4 tests.

**Do not infer full suite acceptance from 10 checkpoint entries, the 153 focused passes, or the previous P36/P35 historical receipts.** In future developer sessions, rerun the same verifier with the exact identical source/test/fixture fingerprint; a code change or distribution update invalidates the checkpoint. Checkpoint files stay in `runtime/` and are excluded from clean project ZIPs.

## Remaining blockers and next highest value

- Current-build CRA+ENU PCAPNG, source-calibrated independent spell/turn/effect witnesses and certified adapter are **not present**. P34–P36 observations cannot prove damage, AP/MP settlement, cast success or authoritative event ordering.
- Production Canonical admission, Windows account/window/calibration, active tactical control, real physical input and server outcome proof remain unavailable; `start` must continue to block.
- Full inherited regression completion and Windows process-tree termination acceptance are still pending.

**Subjective weighted implementation roadmap estimate: 88%. Live full CRA+ENU fight acceptance: 0%.** Not a measured quality score.
