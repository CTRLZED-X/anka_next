# P40 — Cross-account protocol evidence independence (offline)

## Confirmed pre-fix defect

The P28 read-only intake accepted two different manifest `cases` that referred to the **same selected packet** and **same independent oracle observation**, simply by changing `account_role` from `leader` to `follower`. The P29 comparator counted the duplicated assertion twice, and P32 reported `roles_with_matching_oracles_claimed=[leader,follower]` and `RESEARCH_MATCHED_NOT_CERTIFIED` for `actor_ap`. The report still did *not* permit live actions, but falsely inflated multi-account *research* coverage.

**Independent reproduction before fix:** duplicating the historical fixture case into another role produced both matched role names with only one selected network message and one oracle assertion. This is source reuse, not two witnesses. The test was reproduced against the P39 source before any edits.

## Implementation

`src/anka_protocol/evidence_intake.py` now verifies two necessary evidence-independence properties before reporting research coverage:

1. A single independent `(oracle file SHA-256, observation ID)` may appear in **one** case only. Reuse is rejected with `P28_ORACLE_OBSERVATION_REUSED`, including same-role duplicates and file aliases containing the same bytes.
2. One exact `(capture SHA-256, packet ordinal, message ordinal, TCP generation, flow digest, wire name, direction)` source observation cannot be credited to **different account roles**. Reuse is rejected with `P28_CROSS_ROLE_SOURCE_REUSE`, even if a cloned assertion is assigned a different oracle ID or an identical capture is renamed.

Different source messages can support different roles without this new failure. A *single message* may continue supporting multiple **capabilities within the same role** when each has its own independent oracle assertion. All existing size limits, ZIP SHA checks, duplicate JSON detection, data minimization and research-only status remain intact. The recorded source keys remain internal and do not appear in GPT bundles.

This is **necessary but not sufficient** for proving CRA/ENU account identities. Different captured messages, different oracle IDs or different flows do not themselves establish genuine character/window ownership, independent witness truth, client-build certification, server-side effects or an actionable event. Those live qualification gates remain explicitly blocked.

## Source and tests

- Modified: `src/anka_protocol/evidence_intake.py` (bounded manifest intake, no ZIP extraction or untrusted code loading).
- Added: `tests/test_p40_evidence_source_independence.py` (10 adversarial tests including relabeled roles, oracle/capture filename aliases, separate oracles sharing a message, legitimate distinct selectors, staged `setup` intake and historical normal regression).
- Updated: project status, README, embedded root guidance, package version, this document and `verification/P40_offline_acceptance_receipt.json`.
- Preserved all prior P39 source, the deterministic kernel, static assets, calibration, and exactly two root BATs (`setup.bat`, `start.bat`).

## Verification — honest boundaries

- New P40 tests: **11 passed**.
- P28–P40 selected protocol/reconstruction/architecture regressions: **305 tests and 12 subtests passed**.
- `python -m anka_app.cli check`: exit **0**.
- `python -m anka_app.cli setup`: exit **0**.
- `python -m anka_app.cli start`: exit **40**, `LIVE_RUNTIME_NOT_IMPLEMENTED` as required. Incident ZIP integrity verifier reports **PASS**.
- Full one-process inherited pytest run: **INCOMPLETE** because the execution window expired. No full pass is claimed; selected test suite is deliberately scoped.
- Live current-client CRA/ENU fight acceptance: **0%**. No certified modern protocol adapter or physical input authority was introduced.

**Estimated implementation-roadmap coverage remains 88%**, a subjective scope estimate, not a measured quality/reliability score. Genuine current-client capture and independent observation evidence is the most valuable next input; future code must certify account-to-flow/actor identity before granting any runtime authority.
