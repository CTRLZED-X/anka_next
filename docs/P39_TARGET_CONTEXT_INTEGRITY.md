# P39 — Turn-scoped target witness and pre-cast MP-movement research guards

**Scope:** research-only evidence classification; no physical driver, no protocol activation, no production Canonical commits. Built on P38; all previous source and test modules remain present.

## Root causes and counterexamples

1. P36 checked whether a target's earlier cell observation was superseded by a **later cell observation**, but not whether the supposed witness was separated from a cast by an entire completed turn. It could report `MATCHED_OBSERVATION` or `MISMATCHED_OBSERVATION` even after `TURN_END` elapsed. This is not a valid current-turn location attestation. **P39 labels the location `STALE_OBSERVATION` with `P39_TARGET_CELL_WITNESS_CROSSES_COMPLETED_TURN`.** A later current-turn cell observation still supersedes the witness using the existing P36 classification.
2. P36 checked cell activity after a cast but not **observed target movement before the cast** within an MP-resource comparison. A target's MP could change during that earlier movement; the cast cannot be assumed relevant. P39 checks for at least two different observed target cell IDs in the before/cast window and marks the MP comparison `AMBIGUOUS`, adding `P39_TARGET_MOVED_BEFORE_CAST`. This is evidence of a changed observed cell, **not proof of walking/path/MP cost**.
3. The new checks are narrowly scoped to avoid false blocks: a repeated identical target-cell report or movement by an unrelated actor does **not** trigger the new MP guard; location evidence collected after a completed turn, even before the current `TURN_START`, remains eligible. P38's legitimate resource-before-`TURN_START` behavior is preserved.

Every report remains `RESEARCH_ONLY_NOT_CANONICAL`: private deltas are not included in JSON exports; server effect proof, current build certification, action authorization, and canonical commits remain **false/zero**. Missing real current-build traffic and independent gameplay witnesses cannot be synthesized.

## Files / boundaries

- `src/anka_app/target_effect_research_offline.py`: two narrow evidence guards, existing DTO/API unchanged; P39 adversarial checks added to its automatic setup smoke.
- `tests/test_p39_target_context_integrity.py`: eight independent positive and negative fixture cases; including stale-match, stale-mismatch, legitimate current-turn pre-start witness, genuine MP movement, same-cell refresh, unrelated actor, post-cast movement and research-only output safety.
- `docs/P39_TARGET_CONTEXT_INTEGRITY.md`; `verification/P39_offline_acceptance_receipt.json`; version/status/embedded handoff metadata.

## Verification and limitations

Check the exact executable counts and SHA-256 values in `verification/P39_offline_acceptance_receipt.json`. Tests exercise synthetic research evidence and can reject misleading interpretations. No current-client `CRA→ENU` end-to-end live acceptance; `start` must remain deliberately blocked. The complete previous archive is the starting baseline; two operator BAT files only. The documented inherited all-module suite was incomplete on earlier P38.

**Progress indicators:** subjective implementation-roadmap coverage **88%** (no increase for classification-only work); complete live fight acceptance **0%**. Neither is a software-quality score.
