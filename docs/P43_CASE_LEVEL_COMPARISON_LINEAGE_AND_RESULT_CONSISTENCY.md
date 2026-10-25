# P43 — Case-level protocol comparison integrity (offline / research only)

**Release:** 21 October 2026. **Starting source:** complete P42 archive. **One operator configuration:** `config/user.json`. **Only root BATs:** `setup.bat`, `start.bat`.

## Confirmed gap and reproduction

P42 bound a capability comparison to its exact evidence ZIP, declared client build, and adapter. But `_comparison_consistent()` joined result rows primarily by **case index + capability**, so same-capability cases belonging to different declared roles could be misassociated. A stale or altered row could inherit the other row's `MATCHED_RESEARCH_ONLY` state without violating the archive-level binding. Counts of diagnostic reasons or unexplained mismatch fields were also insufficiently checked.

I added nine P43 tests *first*: the unmodified P42 implementation failed seven of them (two passed). The failures included no case binding, accepting modified/missing case binding, treating unknown result status as ordinary unresolved, and inconsistent finding counts. This is a source- and test-demonstrated weakness of offline research reports, **not** proof of incorrect live Dofus behavior.

## Changes (five source/test files)

1. `anka_protocol.evidence_intake.evidence_case_binding(...)`: computes a domain-separated, Base32 SHA-256 digest over the **archive hash, declared build, adapter, case index and four declared case metadata fields**. This is a consistency checksum, not a cryptographic signature, independent identity proof, or authority to activate gameplay.
2. `anka_app.protocol_evidence_compare.compare_pack()`: emits the opaque `case_binding` on each parsed case result. No raw oracle values, source names, player IDs, packet bodies or adapter-build text are added to the comparison report.
3. `anka_protocol.capability_matrix.assess_capabilities()`: fails closed if the row's binding differs, its status is not an allowed comparison status, a field mismatch has no valid field explanation, a matched/unresolved row incorrectly carries mismatched fields, or aggregate `finding_counts` disagrees with rows. A rejected comparison credits **zero** matched research cases.
4. Existing P32 contract fixtures now generate the same case binding and explicit `finding_counts` and mismatch-field metadata. This exercises the new real interface instead of bypassing the new checks.
5. Nine new tests validate individual, multi-role, privacy, malformed result and valid independent-case paths.

## Why this helps with fortnightly protocol updates

A protocol upgrade may contain multiple CRA and ENU observations of the same field type. The evidence engine now has a case-specific join key, so the count of matching observations cannot accidentally change merely because comparison rows were misplaced within a same-build, same-adapter archive report. This is needed **before** trustworthy capability coverage could be used as input to a future reviewed certification process. It still cannot prove role independence or game-server action causality.

## Verification, performed on extracted P43 source

| Gate | Observed result |
|---|---|
| Pre-fix P43 reproducer on unmodified P42 | 7 failures / 2 existing positive passes |
| New P43 tests after correction | **9 passed** |
| Selected P28–P43 and architecture tests | **353 passed + 17 subtests** |
| Entire source-bound, module-isolated Python unittest inventory | **61/61 modules, 1,138 tests passed** |
| Architecture and asset checks | **13 source packages / 248 Python modules**, 165/165 assets, PASS |
| CLI `check`, `setup` | exit 0, PASS |
| CLI `start` | expected exit **40** `LIVE_RUNTIME_NOT_IMPLEMENTED` |
| Diagnostic incident ZIP validation | PASS |
| Live Windows/client acceptance | **NOT RUN**, remains 0% |

The 61-module suite ran with the shipped resumable module verifier, one subprocess per test module, and an input fingerprint tied to source, tests, assets and environment. Generated runtime checkpoints/logs are excluded from the ZIP. This is *offline* validation, not proof of the Dofus client, live decoder, or physical input.

## Intentional constraints and next high-value dependency

- This **does not certify** a current-client protocol version, account-class identity, or any server-confirmed spell effect. `start.bat` remains blocked, and no new BAT launcher or dashboard is added.
- A digest is **not authentication**; the real capture, source selector, independent witness, actor/fight context, and adapter recipe must be reviewed against current-build evidence before production Canonical admission.
- Next practical milestone: use authentic current-build PCAPNG + independently witnessed CRA/ENU resource, cast, movement, turn and fight outcomes for a version-pinned decoder and enforce complete causal proof. Without that evidence, keep the adapter research-only and work on remaining high-priority integration contracts rather than falsely authorizing gameplay.

**Estimated roadmap coverage:** 88% (unchanged subjective estimate). **Complete real CRA+ENU fight accepted:** 0%.
