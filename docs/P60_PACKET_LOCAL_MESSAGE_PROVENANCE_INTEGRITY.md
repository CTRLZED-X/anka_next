# P60 — Packet-local wire-message provenance for interleaved multi-account captures

**Date:** 22 October 2026  
**Scope:** offline Capture → Protocol → P58/P59 research admission; no current-client certification or live input.  
**Reference build:** historical Dofus 3.7.10.10, not a verified current build.

## Reproduced root cause

In P59, `anka_protocol.api.ProtocolInspector.consume()` placed `self.messages` (the cumulative total of all messages across every observed TCP connection) in `WireMessage.message_index`. `self.messages` is correct as a summary counter but **incorrect as a source selector**. The rest of the evidence system treats an observation as a tuple containing `(flow, transport_generation, packet_number, message_index, wire_name)`.

A synthetic PCAPNG containing alternating A/B connections produced these selectors before P60:

| Captured packet number | Flow | Message | Old global message_index | Correct packet-local message_index |
| --- | --- | --- | --- | --- |
| 3 | A | `jnj` | 0 | 0 |
| 4 | B | `jnj` | 1 | 0 |
| 5 | A | `jvj` | 2 | 0 |
| 6 | B | `jvj` | 3 | 0 |

As a result, a valid independently prepared P59 claim for flow A's packet 5 / index 0 failed when unrelated flow B messages preceded it. Conversely, a provenance ordinal could change merely because unrelated TCP traffic changed, even though the actual packet bytes and packet position did not.

## P60 change

`ProtocolInspector.consume()` now numbers extracted named messages **starting at zero within the capture packet whose TCP segment completes their frame**. Multiple named messages extracted in the same packet receive ordinals `0, 1, ...`. This continues to support TCP frame fragmentation: the completing segment's capture packet owns the observation. `self.messages` remains a global running **count**, so diagnostics/limits retain their existing meaning.

The wire/protocol contract remains strictly **observation-only**. No decoded message can become an admitted Canonical event, a game-action permission, or a certified CRA/ENU identity through this change.

## Integration and regression checks

- P60 test fixture includes two distinct socket flows interleaved in one PCAPNG.
- Each independent flow's character (`jnj`) and turn (`jvj`) claims correspond to the same saved capture's source bytes at their exact packet positions.
- Same-packet multiple messages retain different ordinal selectors.
- An unrelated preceding packet cannot change another flow's packet-local index.
- The complete pre-existing P59 suite still passes for same-packet two-message evidence.
- `check` / `setup` automatically run the `packet_provenance_smoke()` exercising the real PCAPNG parser, protocol inspector and P59 capture-bound research review; expected outcome is `PASS_MULTI_FLOW_PACKET_LOCAL_PROVENANCE` with two independent candidate flows and four matched wire messages.

## Migration compatibility

**Any pre-P60 generated research selectors relying on global message indexes must be regenerated from their original capture.** They should not be relabeled by offset or accepted without replay. An exact source mismatch must fail closed. The source file remains unmodified, but evidence selectors from prior P59 runs are not guaranteed to match the corrected protocol interpretation.

No current-client evidence was supplied or generated. A synthetic fixture and a historical known-key catalog do not establish packet origin, Npcap loss visibility, account ownership, client build compatibility, character/breed identity, spell causality, fight outcome, or live readiness.

## Verification

- New P60 test module: **4 PASS** (the unmodified P59 decoder reproduced **3 failing P60 tests** before the correction).
- Focused protocol/wire/P48/P49/P50/P58/P59/P60 regression: **127 PASS + 8 subtests**.
- Full source-bound module-isolated regression: **87/87 test modules, 1,508 test methods PASS**, fingerprint `ef0c6e939ea981b6787986ae65afe3e734bdc7ef61640707ab0e9bbb27b16f90`.
- `check` / `setup`: PASS; architecture: 13 packages, 279 Python source modules, zero boundary violations; reused reference assets 165/165.
- `start`: intentionally BLOCKED / exit **40** / `LIVE_RUNTIME_NOT_IMPLEMENTED`; startup incident ZIP integrity PASS.
- Root operator entrypoints: **only `setup.bat` and `start.bat`**.

Historical subjective roadmap coverage: **92% (unchanged)**. End-to-end current-client CRA/ENU live acceptance: **0%**.

## Next steps

Current-client captures and independently witnessed Windows process / TCP socket / window / character / breed identity are required. The modern build's actual protocol schema and event semantics must be independently qualified before implementing an authoritative Canonical writer or enabling physical execution. Do not treat P60's improved indexing as proof of any of those requirements.
