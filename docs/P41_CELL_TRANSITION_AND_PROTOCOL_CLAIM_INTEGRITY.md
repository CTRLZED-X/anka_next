# P41 — Observed cell-transition integrity and protocol claim uniqueness

**Date:** 2026-10-21. **Release:** P41 research-only. **User-facing commands:** `setup.bat`, `start.bat` only. **Live accepted:** 0%. **Estimated roadmap coverage:** 88%, unchanged and subjective.

## Confirmed defects reproduced against P40

1. **Position refresh incorrectly classified as observed movement.** P35 marked an MP resource window ambiguous whenever a same-actor cell observation appeared between baseline and post-cast snapshot, even when independent observations showed the same cell before and after the cast. P36 made a similar mistake for target-cell updates after casting. This hid useful research distinctions and was an overly broad safety guard rather than evidence of movement.
2. **Duplicate same-account/same-capability protocol source inflated research case counts.** P40 prevented the exact packet from being relabeled as leader *and* follower, but a case using the **same exact packet selector, same role and same capability**, with a freshly labeled oracle observation, still yielded two P29 `MATCHED_RESEARCH_ONLY` results. A single transport message must not become multiple independent wire samples merely because two annotations share it.

Both issues were independently reproduced in failing P41 regression tests **before** modifying implementation. The unmodified P40 comparison showed `intake.case_count=2` and `compare.matched_cases=2` for the duplicated AP packet and role.

## Implemented and boundaries preserved

- New `anka_app.cell_transition_evidence.observed_cell_change(...)` is a **pure research classifier**, shared by existing P35 and P36 consumers, with four substantive states plus `PRE_ONLY`:
  - `DISPLACEMENT`: at least one pair of consecutive observed same-actor cells differs inside the selected, validated window.
  - `SAME_CELL`: explicit before-cast and after-cast positions agree, with no observed transition. A repeated cell observation alone does **not** prove movement.
  - `UNANCHORED_POST_OBSERVATION`: a new post-cast cell is seen without a pre-cast position anchor. Keep an explicit ambiguity and `P41_CELL_TRANSITION_BASELINE_MISSING` caveat.
  - `PRE_ONLY`: an unanchored pre-cast observation with no after-cast cell. For P35 MP this remains conservative/ambiguous (existing P38 contract); P36 continues to evaluate separate target/turn evidence.
  - `NONE`: no position observations in the scoped research window.
- New `selector_capability_claims` in `anka_protocol.evidence_intake` rejects `P28_DUPLICATE_SOURCE_CAPABILITY_CLAIM` whenever two manifest cases claim the same byte-content capture, exact packet/message/generation/flow selector, **same role and same capability**. Validation occurs on read-only ZIP intake, before comparisons or capability aggregation. `P28_CROSS_ROLE_SOURCE_REUSE` remains the stricter cross-role check.
- **False-blocking counterexamples:** one source message can legitimately support both actor AP and actor MP, if it has distinct oracle observations. Independent packet selectors remain valid for separate samples. A position refresh on the same cell must not be labeled a displacement; genuine departure-and-return still confounds.
- All P35/P36 research reports still declare `server_effect_proven=false`, `actionable=false`, `committed_events=0`, `physical_input_sent=false`. No runtime input, Canonical admission, or modern client adapter was added.

## Source changes

- `src/anka_app/cell_transition_evidence.py` — **added**, pure shared cell transition classifier.
- `src/anka_app/effect_reconciliation_offline.py` — reuse classifier for MP window confounders.
- `src/anka_app/target_effect_research_offline.py` — reuse classifier for target movement evidence.
- `src/anka_protocol/evidence_intake.py` — case source/capability uniqueness at intake.
- `tests/test_p41_cell_transition_evidence.py` — **added**, 11 regression cases.
- `tests/test_p41_packet_claim_uniqueness.py` — **added**, 6 regression cases.

## Verification

**Strongest completed offline gate:** developer-only `verify_isolated(root, module_isolation=True, checkpoint_path=..., max_new_modules=..., per_shard_timeout=...)` across **all 59 test files and 1,121 unittest test methods, PASS**, using repeatable bounded batches and one immutable SHA-256 source/test/config/asset/environment fingerprint. This run includes the 17 newly added P41 tests and all inherited test modules; one P37 module needed an increased timeout because it intentionally spawns children and tests timeouts. It passed after using a suitable `per_shard_timeout` (70 seconds). A temporary shorter-timeout attempt was `INCOMPLETE`, not a test assertion failure. Checkpoint under `runtime/verification/` was *not* packed into the release ZIP.

Additional independent gate: focused `pytest` for P28–P41 + architecture **336 tests + 12 subtests PASS**. `python -m anka_app.cli check`: exit 0. `setup`: exit 0 (including 13 package boundaries / 165 reused assets). `start`: exit 40, `LIVE_RUNTIME_NOT_IMPLEMENTED` intentionally; generated incident bundle integrity `PASS`.

**External limitations:** all included evidence is offline/synthetic/historical research. No contemporary Dofus PCAPNG+independent current-build witness, no Windows/Npcap/Unity acceptance, no authoritative Canonical admission, no real input driver, and **0% complete CRA+ENU live-fight acceptance**. The project package version remains `0.40.0` (unchanged metadata to keep the source/config/asset fingerprint of the complete verification exact); the **milestone release identity is P41** in the ZIP name, docs and receipt. This is not a claim of 0.41.0 pip publication.

## Next highest-value dependency

Supply **authentic current-client** evidence (PCAPNG, version, actor/client/flow identity, witnessed AP/MP/HP/cells, cast/turn/Ready/end outcomes). Only then can the research adapter be certified for a new build and Canonical production admission designed using real effect and causality proofs. More synthetic planning cannot replace this evidence. Keep raw captures private; the default GPT incident bundle remains sanitized. No additional BAT commands or dashboard.
