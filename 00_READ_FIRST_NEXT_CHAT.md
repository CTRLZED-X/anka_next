# READ THIS FIRST — ANKA_NEXT_M12_006

This is the current ANKA_NEXT offline/zero-input release candidate. Read this file, `IMPLEMENTATION_STATUS.md`, `docs/M12_006_CAUSAL_DIAGNOSTIC_AND_FULL_CHAIN_HARDENING.md`, and the current source before using historical P-series documents. Historical documents are evidence/provenance, not current authority.

## Current state

- Release: `ANKA_NEXT_M12_006`
- Python: 3.13 only (`>=3.13,<3.14`)
- Physical input default: **DISABLED**
- Current-build Protocol adapter: **none certified**
- Offline gates: Q0-Q9 + M12 must PASS on the final sealed source identity
- Current implementation source SHA-256: `9f7d27d098bf70bbddac38cbfaaf441c278001c0ebe92d23e9b58039dd846c56`; fresh Q0-Q9 + M12 receipts PASS on this source before final package-manifest sealing
- Fresh diagnostic/full-chain counts: Q8 **112 tests + 7 subtests**, Q9 **22 + 9**, M12 **202 + 21**; physical OS input remains zero
- Live gates: Q10 Windows -> Q11 exact-current-build observation -> Q12 individual action scopes -> Q13 bounded real CRA+ENU mission remain evidence-gated
- Operator BAT files: only `setup.bat` and `start.bat`
- Configuration: JSON only; no dashboard/operator UI

The intended architecture remains Capture -> Protocol -> Canonical -> Live State, with Coordination/Workflow, Decision/Game Kernel, Execution, Client and Observability separated by `anka_contracts`; `anka_app` is the concrete composition layer. Execution is the sole physical-input/settlement authority. Observability is passive evidence only.

## What changed in M12_006

M12_006 fixes reproduced full-chain and diagnostic weaknesses rather than replacing working architecture. The production-style zero-input chain now covers world movement, fight entry, follower join, placement, Ready, first-turn ownership, combat actions, End Turn/handoff, fight end and world re-entry through Decision -> scoped authority -> Execution -> Canonical evidence/settlement. Pre-turn actions no longer depend circularly on a combat-turn permit, JOIN authority is bound to the exact target fight, and unresolved placement/Ready side effects fence Workflow progress.

The incident system is now a bounded dual-lane flight recorder with asynchronous non-blocking journals, priority safety evidence, exporter fault containment, per-account/latest-epoch READY reconstruction, Decision-to-Execution action traces, post-commit Live-State summaries, exact settlement reports, recovery/proven-facts/historical-similarity artifacts, and a verifier-cross-checked `analysis/gpt_summary.json`. A structurally incomplete, causally reordered, internally contradictory, or falsely-complete schema-2 bundle is rejected even if its ZIP manifest is recomputed. On the next `start`, validated journals from a previous unclean process exit are exported once as a `PARTIAL` crash-recovery incident with an explicitly uncertain tail.

When diagnosing a live failure, begin with `GPT_READ_FIRST.md` and `analysis/gpt_summary.json`, then `analysis/diagnosis.json`, `analysis/action_lifecycles.json`, `analysis/party_ready.json`, `analysis/boundary_graph.json`, `analysis/evidence_gaps.json`, snapshots, and the bounded timelines. Diagnose the **first evidence-supported divergence**. Do not reuse historical similarity as root-cause proof and do not infer missing evidence.

## Rules for future work

Treat every proposal—including prior GPT recommendations and user suggestions—as a hypothesis. Prefer reproduced failures, invariant checks, mutation/fault injection, replay evidence, and source-bound receipts. Never promote offline/synthetic success to live acceptance. Preserve the versioned one-folder ZIP delivery rule and do not add user-facing BAT launchers beyond `setup.bat` and `start.bat`.
