# ANKA_NEXT M12_006

ANKA_NEXT M12_006 is the current **offline / zero-physical-input / pre-live** release candidate. It preserves the existing subsystem architecture and adds hardening only where falsification found concrete weaknesses. Physical input remains disabled and no current Dofus protocol adapter is certified for live authority.

## Current acceptance boundary

Q0-Q9 are offline acceptance gates. Q10 still requires a real Windows clean-host run, Q11 requires observe-only evidence for the exact current Dofus build, Q12 requires separately accepted physical action scopes, and Q13 requires a bounded real CRA+ENU mission. Passing the offline suite must never be interpreted as live-game acceptance.

The current implementation source SHA-256 is `9f7d27d098bf70bbddac38cbfaaf441c278001c0ebe92d23e9b58039dd846c56`. Fresh source-bound gate receipts currently PASS through Q9 and M12; Q8 covers 112 tests + 7 subtests, Q9 covers 22 + 9, and M12 covers 202 + 21 with zero physical OS input. Final whole-project isolated verification is performed only after the release manifest is frozen.

Normal operator entry points are only:

- `setup.bat` — installs/verifies the Windows environment and records release-bound prerequisite evidence.
- `start.bat` — performs release/config/host/capture/bridge/current-wire observation and **fails closed** while live acceptance is incomplete.

On this non-Windows verification host, `start` is expected to stop at `START_WINDOWS_REQUIRED` (exit 40). `LIVE_RUNTIME_NOT_IMPLEMENTED` remains present only in historical P-series evidence and the deliberate composition-level guard; it is not the current top-level startup diagnosis on this host.

## Architecture

The source tree is organized into independent systems under `src/`:

`anka_capture -> anka_protocol -> anka_canonical -> anka_live_state`, with `anka_coordination` and `anka_workflow` controlling party/mission state, `anka_decision` using the isolated `anka_game_kernel`, `anka_execution` as the sole physical-input/settlement owner, `anka_client` for read-only client/window/bridge evidence, `anka_observability` for bounded diagnostics, `anka_contracts` for stable cross-system DTOs, and `anka_app` as the only concrete composition layer.

The architecture guard enforces package dependencies and rejects obvious physical window/input control primitives outside `anka_execution`.

## M12_006 hardening

M12_006 is a causal-debugging and full-chain hardening revision built after falsifying M12_005. It closes reproduced gaps in pre-turn authority, world/fight-entry integration, JOIN target binding, unresolved pre-turn fences, real Workflow/Execution diagnostic publication, post-commit Live-State evidence, and per-action forensic reconstruction.

Observability now uses a bounded dual-lane flight recorder, non-blocking asynchronous journals, priority persistence, fault-contained export, party-aware READY analysis, action/Decision/Execution trace correlation, machine-readable `analysis/gpt_summary.json`, historical-similarity hints that are explicitly non-causal, recovery/proven-facts reports, and verifier-enforced required bundle artifacts. Evidence truncation/loss is explicit, redundant timeline views are self-audited, and the next `start` can recover validated durable journals from a prior unclean process exit into a `PARTIAL` crash incident without inventing the missing tail. Diagnostic failures cannot grant gameplay authority or alter committed system state.

The Q9 synthetic lifecycle now traverses world movement -> fight entry -> follower join -> placement -> Ready -> first turn -> combat -> End Turn/handoff -> fight end -> world re-entry through Decision, scoped authorization, Execution, Canonical settlement, Coordination and Workflow while the driver remains fake-only and OS physical input stays zero.

See `docs/M12_006_CAUSAL_DIAGNOSTIC_AND_FULL_CHAIN_HARDENING.md` for reproduced defects and the forensic trust model.

## Where to read next

- `IMPLEMENTATION_STATUS.md` — current verified implementation state and remaining acceptance gates.
- `00_READ_FIRST_NEXT_CHAT.md` — compact handoff for continuing development in another chat.
- `reference/master_specification/ANKA_NEXT_DEFINITIVE_BLUEPRINT/` — definitive target architecture/specification.
- `docs/history/` and `docs/P*.md` — historical engineering evidence; these files may intentionally contain obsolete release behavior and must not override current source/status documentation.

## Safety rule

Do not enable or construct real physical input merely because offline tests, simulations, historical replay, or protocol framing succeed. Unknown/missing evidence remains unknown, unresolved external side effects remain fenced, and current-build/live acceptance must proceed Q10 -> Q11 -> Q12 -> Q13.
