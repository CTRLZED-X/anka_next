# P59 — PCAPNG-backed corroboration of untrusted admission evidence

**Date:** 22 October 2026  
**Baseline:** full ANKA_NEXT P58 archive  
**Authority:** historical research only; Canonical/live-state writes and physical input prohibited

## The gap closed

P58 compares internally consistent caller-provided message bodies, message SHA-256 values, capture SHA-256 strings, protocol/flow/generation labels, actor identities and `CanonicalDraft` proposals. It cannot prove that those bodies were ever present in the claimed capture. A complete internally consistent but fabricated rehearsal therefore gets `STRUCTURALLY_CONSISTENT_UNTRUSTED` (correctly blocked from authority). P59 adds an **independent file-bytes check** to catch fabricated or misattributed wire records earlier.

`anka_app.capture_bound_admission_offline.review_capture_bound_admission` accepts a P58 `AdmissionRehearsal`, an existing saved `.pcapng` path, the project root, and selected TCP server ports. It uses the established Capture PCAPNG parser, P6 `ProtocolInspector` with the hash-pinned P6 *historical* catalog, and P58 structural review—no new packet parser, format guesser, or semantic decoder.

```text
Actual saved PCAPNG bytes (<= 32 MiB)
  → existing P4 capture parser / SHA-256 / bounded replay
  → existing P6 TCP framing / Ankama Any extraction / historical catalog
  → exact selected flow / TCP generation / packet ordinal / message index / name
  → compare all selected server messages with P58 claimed exact body bytes
  → FILE_WIRE_MATCH_UNTRUSTED or QUARANTINED (never certified)
```

The saved file is bounded, independently read twice, and compared by exact digest/size, preventing a different file revision from being used between inspection and replay. All selected-flow recognized server messages must be accounted for: claimed records absent from the file, unexpected messages in the file, relabeled ordinals, changed bytes, or mixed transport generations become explicit blockers. Unknown envelopes/incomplete/quarantined stream states remain visible. The report exports only counts and allowlisted reason codes, not network IP/port pairs, character names, actor identifiers, wire bytes, local file paths or flow selectors.

### Important limitations

**This does not establish authentic server origin.** An investigator can forge the PCAPNG *and* the matching rehearsal. A matching file hash proves only correspondence to the chosen file snapshot; no independent Npcap driver-loss attestation, provenance timestamp certificate, Windows process/socket/window identity, character/breed attestation, exact current-client protocol qualification, semantic correctness, or game outcome is established. The historical catalog covers the archived Dofus 3.7.10.10 build only; unrecognized modern build labels remain `QUARANTINED`.

Even a positive `FILE_WIRE_MATCH_UNTRUSTED` has immutable `current_client_certified=False`, `driver_loss_proven=False`, `account_binding_verified=False`, `authoritative=False`, `actionable=False`, `canonical_commits=0`, `physical_input_sent=False`. The synthetic P56 writer rejects the report type. This path cannot transform `CanonicalDraft` into an admitted state event. It does not silently treat missing wire messages as absent gameplay effects.

## Files and regression

- `src/anka_app/capture_bound_admission_offline.py`: bounded file/wire cross-check and immutable privacy-filtered result contract.
- `src/anka_app/capture_bound_admission_smoke.py`: small hermetic reference-file-vs-forged-byte test.
- `src/anka_app/cli.py`: existing `check` and `setup` invoke the small smoke automatically; **no additional BAT scripts or operator commands**.
- `tests/test_p59_capture_bound_admission.py`: 13 adversarial tests; real synthetic PCAPNG parsing and framed protobuf wire reconstruction, source ordinal, content drift, changed file, missing/extra wire, unknown frame, wrong build, journal refusal, redacted output.

**Verification:** focused P48/P49/P58/P59 group 71 tests + 6 subtests PASS. Full source-bound module-isolated regression 86/86 modules, 1,504 test methods PASS (fingerprint in `verification/P59_offline_acceptance_receipt.json`). `check`/`setup` PASS, native/architecture guard PASS, asset hashes 165/165 PASS, `start` remains exit 40 / `LIVE_RUNTIME_NOT_IMPLEMENTED`, generated incident ZIP integrity PASS. No real Windows current-client acceptance or full live mission was performed.

## Next meaningful dependency

One independent **current-client** evidence package must provide provenance and loss accounting from the real capture process, current adapter semantics independently correlated with gameplay, and verified process/socket/window/character/breed identity. P59 can then detect fabricated *body-to-file* associations, but it is not a substitute for those external truths. Do not enable authoritative Canonical admission until those independent gates and real Windows recovery tests exist.

Subjective development roadmap estimate remains **92%**; verified complete CRA/ENU live mission acceptance remains **0%**.
