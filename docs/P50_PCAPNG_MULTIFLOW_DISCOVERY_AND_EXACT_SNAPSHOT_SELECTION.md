# P50 — Bounded multi-flow discovery and exact-source research selection

**Scope:** offline, historical, research-only. P50 never certifies a current Dofus client, maps a flow to CRA/ENU, writes Canonical state, changes the deterministic Kernel, or sends physical input. `start.bat` must remain fail-closed.

## Motivation and corrected boundary

P49 could process a real saved PCAPNG only after an investigator supplied `LegacyFightScope.flow_digest`. That digest was not discoverable through a cohesive project API; a multi-client capture could contain several otherwise plausible TCP flows. A caller could inadvertently select the wrong one or reuse a flow selector against a changed capture.

P50 adds an explicit read-only selection workflow:

1. `inspect_pcapng_flow_inventory(path, ports=(...))` uses existing P4 capture bounds and parser, verifies a second byte-for-byte snapshot using the receipt's SHA-256, and groups the selected TCP segments by flow.
2. The result contains no raw endpoints, payloads or file paths: each `FlowCandidate` uses a SHA-256 flow digest, capture-wide packet bounds, direction-specific counts, observed SYN/FIN/RST flags, and independent TCP continuity findings. At most 64 candidates may be returned. A lack of selected packets and excess candidate flows are explicit blockers.
3. The investigator supplies a `LegacyFightScope` with a selected digest, historical protocol build, fight ID, and generation **as hypotheses**, not verified game facts.
4. `replay_inventoried_pcapng_flow` refuses any digest outside the inventory, recomputes the flow list instead of trusting mutable/caller-provided records, pins the **exact** source SHA and packet counts, and then calls P49's bounded historical replay.
5. Both inventory and selected replay remain non-authoritative. `InventoriedFlowResearch` always has `status=BLOCKED_EVIDENCE` and `actionable=False`. Its nested P49 report may contain useful historical lifecycle observations but never grants game authority.

## Failure modes verified

- Different flows in one PCAPNG remain separate, with capture-wide packet indices preserved.
- Selection against a different PCAPNG revision is blocked (`P50_INVENTORY_SOURCE_CHANGED`).
- Fabricated/misassigned flow digests or packet bounds are blocked (`P50_INVENTORY_FLOWS_UNVERIFIED`).
- Invalid/missing selectors, malformed captures, no selected TCP packets, and excess candidates fail closed.
- Missing SYN is reported as uncertain transport, never silently assumed complete.
- Multiple server/client directions are counted separately; no direction becomes an account ID.
- Wrong historical build does not decode into authority; the nested P49 research report preserves the details.

## Deliberate limitations

A PCAPNG cannot independently attest capture-driver loss, all missing packets, TCP-to-Windows-PID/HWND ownership, game character identity, or the semantic correctness of current obfuscated protocol fields. Flow digests are **selectors** and should not be interpreted as independent identity attestations. Observed TCP continuity is insufficient for source completeness.

P50 supports a future independent Windows process/socket/window identity witness. That witness must be separately developed, evidence-qualified, and audited; no account labels are fabricated from IP addresses or actor IDs here.

## Verification

- Added `tests/test_p50_flow_inventory.py` (15 tests) and `tests/test_p50_flow_setup_smoke.py` (1 test).
- Source-bound full test run via P37 module-isolated verifier: 75/75 modules, 1,306 tests **PASS**, checkpoint fingerprint recorded in `verification/P50_offline_acceptance_receipt.json`.
- `check`: exit 0; `setup`: exit 0; `start`: intentionally exits 40 (`LIVE_RUNTIME_NOT_IMPLEMENTED`).
- No separate operator BAT scripts. Automatic flow-inventory synthetic smoke now runs during `check` and `setup`.

## Next technical priority

Establish independent current-client socket↔PID↔HWND↔character evidence and current-protocol semantic witnesses. Only then can any Canonical state admission or controlled execution be evaluated; P50 is not such an admission milestone.
