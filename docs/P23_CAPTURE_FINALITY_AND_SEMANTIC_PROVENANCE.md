# P23 — Capture finality before historical Canonical research staging

## Root cause found in P22

`anka_app.semantic_offline.inspect_semantic_pcapng` formerly called `CanonicalStagingGate.inspect` for each newly decoded TCP frame **before** `ProtocolInspector.finish()` had checked the remaining stream for gaps, resets, unfinished frames and other anomalies. A valid early frame followed by a broken stream could therefore leave staged **research-only** candidates even though the evidence was incomplete. It could also allow an adapter implementation to attach a candidate to a different packet/flow ordinal without a source-level check.

This did not enable live gameplay or mutate the durable state ledger, but it could mislead subsequent debugging and would have been a dangerous model to reuse for future authoritative admission.

## Actual code changes

Only the **application composition** `src/anka_app/semantic_offline.py` was modified; the historical game kernel, Capture, Protocol, Canonical, coordination and execution internals were not rewritten.

1. **Phase 1, provisional decode:** bounded in-memory semantic results (maximum 4096 messages/2048 facts). All provisional facts retain immutable `EvidenceRef` and are checked against the exact original `WireMessage` (build, adapter, name, transport generation, packet number, message ordinal and SHA-256 digest of the flow identifier). Raw payloads or flow names are not put into diagnostic reports.
2. **Phase 2, transport finality:** after the entire capture is consumed, require both Capture's TCP audit and Protocol's final stream audit to be clean **before** any historical research staging. One late transport failure holds back all provisional facts in this evidence batch. Driver-level completeness, account identity, and live authority remain **unproven**, even on the positive case.
3. **Phase 3, semantic consistency:** the complete candidate set goes through the existing Canonical research qualifier to catch conflicting/reused evidence coordinates before any staging. A drifted mapped schema, a mismatched build, a mismatched source coordinate or a batch overflow is rejected with a stable first-failure reason; a newly observed **unknown background wire name** does not trigger an unnecessary global semantic-drift failure.
4. **Phase 4, safe output:** still zero committed Canonical events, zero authoritative state updates, zero physical input. Added `pending_candidates`, `withheld_candidates`, `source_provenance_mismatches`, `transport_continuity_observed`, `first_failure_boundary`, and `batch_capacity_exceeded` to the existing *developer-side* read-only semantic audit result.

**Conservative limitation:** evidence failures quarantine the entire offline capture batch. This is a correct diagnostic choice for this small historical research path; a future real-time implementation will need finer per-flow/per-generation isolation, capability-specific readiness and server-supported sequencing before any live authority can be considered. Do not generalize the batch-wide research quarantine into a global mission-disarm rule (historical R5.198 regressions already demonstrate why that can cause stalls).

## Permanent regression scenarios

`tests/test_p23_semantic_transport_finality.py` tests: a valid early jtk AP/MP followed by a TCP gap, RST, partial-frame tail, missing SYN, or bad reconnect; later mapped-wire schema drift; benign unknown messages; wrong build; same-looking messages with distinct ordinals; decoder exceptions; bounded-batch overflow; a decoder reusing coordinates; forged packet number, message index, adapter or flow digest; and private-data avoidance.

## Acceptance / remaining risks

- The 714 collected Python tests **pass in eight bounded isolated groups**, including P23's 18 new tests and P22's 696 inherited tests. The whole-suite single-process runner has an intermittent stall; it is not certified as stable. See `verification/P23_offline_acceptance_receipt.json` for group-level evidence.
- Windows batch launchers are not executable on the Linux test host; only `setup.bat` and `start.bat` are shipped.
- No current-client raw PCAP/identity evidence is included. Current protocol semantic decoding, authoritative Canonical admission, account/capture correlation, real FightAI, physical input and complete CRA/ENU live missions remain **unimplemented or unverified**.
- Historical research outputs are not proof of accuracy of AP/MP mechanics on the current Dofus build. A wire-only future update must have independently measured per-capability compatibility and server-confirmed outcomes.

## Next highest-value engineering step

Certify an actual currently observed client/adapter using **real external evidence**, independently authored expected facts and current-build replay. Without such evidence, the next offline development focus should be narrowing the verification-runner intermittent stall and building runtime evidence capture on a Windows host, not adding more synthetic strategy scores or operator commands.
