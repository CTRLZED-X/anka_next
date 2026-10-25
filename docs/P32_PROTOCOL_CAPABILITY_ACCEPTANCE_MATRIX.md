# P32 — Capability-by-capability protocol upgrade acceptance matrix

**Status:** Implemented as **research-only** evidence-quality reporting. This is NOT a current-client certification or automatic adapter activation. All physical gameplay remains disabled.

## Why this milestone matters

Previously `setup.bat` produced a file-integrity report (P28) and an exact-source semantic comparison (P29/P31), but no single capability-level report said whether evidence was complete for **both accounts**, whether each required case had a witness/selector, or whether every supplied case really matched. A capability appearing in a manifest meant only that someone *declared* it, not that the decoder had proven it.

P32 adds `anka_protocol.capability_matrix.assess_capabilities`, a pure function with **no imports from other runtime systems**. `anka_app.protocol_updates` joins the validated intake and comparator results and attaches `capability_assessment` to every staged pack inspected automatically by `setup.bat`.

## Per-capability acceptance logic

Each declared capability is reported with:

- whether it is required for eventual gameplay;
- case count, matched/mismatched/unresolved counts;
- cases with an existing witness file and with an exact packet selector;
- claimed roles (`leader`, `follower`, `other`) and roles supported by matched oracle comparisons;
- a status and stable blockers (`CAPABILITY_EVIDENCE_MISSING`, `SEMANTIC_FIELD_MISMATCH`, `EXACT_SOURCE_SELECTOR_MISSING`, `WITNESS_FILE_MISSING`, `LEADER_FOLLOWER_COVERAGE_INCOMPLETE`, etc.).

For the ten required capabilities, the **research coverage** grade requires matching selected/witnessed observations for **both declared leader and follower roles**. This is a conservative review criterion, not proof of identity: the case's account role is manually declared and is **not independently attested** by P32. A fully matched matrix is labeled `RESEARCH_COVERAGE_MATCHED_NOT_CERTIFIED`, never `LIVE_READY`.

The composition root also pins the **exact original archive digest** from intake when invoking comparison, preventing a file swapped between the two phases from silently receiving the first archive's capability labels. The matrix validates source/comparison alignment: case count, ordinal uniqueness, capability names, claimed match/mismatch counts, and global comparison status. Contradictory or missing comparison results are fail-closed. A missing adapter is **not** reported as a decoding mismatch; the unavailability code is preserved in `comparison_status` and affected cases remain unverified.

## Example sanitized output (illustration, not real game evidence)

```json
{
  "status": "RESEARCH_COVERAGE_INCOMPLETE",
  "required_blocked_capabilities": ["actor_ap", "actor_cell"],
  "capabilities": [
    {"capability": "actor_ap", "required": true,
     "status": "INCOMPLETE_RESEARCH_EVIDENCE",
     "case_count": 1, "matched_cases": 1,
     "roles_declared": ["leader"],
     "roles_with_matching_oracles_claimed": ["leader"],
     "blockers": ["LEADER_FOLLOWER_COVERAGE_INCOMPLETE"]}
  ],
  "research_only": true,
  "current_build_certified": false,
  "live_semantic_certified": false,
  "canonical_commits": 0,
  "adapter_activated": false,
  "physical_input_sent": false
}
```

Actual reports include every recognized capability rather than the abbreviated example, and do not include actor names, raw packet bytes, file paths, oracle values, or full flow identities.

## Verification and permanent test requirements

`tests/test_p32_protocol_capability_assessment.py` covers missing and single-role capabilities, fully supplied but **still non-certified** cases, absent witnesses and selectors, real historical matched/mismatched evidence packs, unsupported adapters, forged/missing/duplicated case indices, contradictory comparison counts, invalid intake metadata, privacy, and `setup` composition.

Existing P28–P31 tests must continue passing. The P32 report adds *no new operator launcher*: use only `setup.bat` (to audit staged packs) and `start.bat` (still blocks unsafe live gameplay). Developer tests live in Python under `tests/`.

## Outstanding acceptance blockers

- This matrix does **not** verify oracle independence, witness truth, account identity, or the provenance of the human-declared account role.
- No current-build version-specific semantic adapter has been certified or activated; the shipped registry remains empty.
- Protocol capture and Windows process/character matching must be proven against a running current client.
- Complex spell effects, movement, Ready, Join, results, uncertain outcomes, cross-account server ordering and live action confirmation remain incomplete or uncertified.
- Live Canonical admission, end-to-end CRA/ENU fight operation and physical execution require their own later acceptance gates.

**Policy:** Research evidence can justify investigation, never game-state authority by itself. Nothing in P32 relaxes those boundaries or changes the preserved game kernel.
