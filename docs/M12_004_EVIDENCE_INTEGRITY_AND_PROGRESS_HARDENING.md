# M12_004 — Evidence Integrity and Progress Hardening

## Scope

M12_004 is a falsification-driven hardening pass over the M12_003 pre-live architecture. It does not redesign subsystems merely because live acceptance is still blocked. Changes are limited to defects that were reproduced or to invariants that can be verified offline without pretending to know current Dofus behavior.

## Confirmed defects corrected

1. **Known Capture loss could be hidden behind Protocol semantic uncertification.** A receipt could explicitly report queue loss while startup exposed only the later semantic-adapter blocker. Startup now reports the upstream loss/uncertainty independently.
2. **Capture cleanup could replace the primary failure.** A polling/consumer exception followed by a shutdown exception surfaced the shutdown exception. The primary exception is now preserved and cleanup/evidence-marking failures are attached as diagnostic notes.
3. **Post-quiesce final draining had no independent progress bound.** A broken queue/source contract could hang startup indefinitely. The finite queue/drain contract now has a bounded exhaustion check and explicit failure.
4. **Release-bound setup evidence was read and passed into startup acceptance but ignored.** Stale/invalid Capture and Unity setup receipts now become additive blockers while current host probes remain authoritative.
5. **Malformed incident bundles could crash verification.** Untrusted ZIP/JSON/schema/file-receipt errors now produce bounded structured FAIL codes instead of escaping as verifier exceptions.
6. **Diagnostic export could race snapshot/final-state mutation.** Snapshot registration, final-state writing, and incident export now share observer serialization so an incident is a coherent bounded view.
7. **Protocol finalization bypassed Protocol's mutation-owner lock.** `finish()` is now serialized with packet/poll consumption.
8. **Protocol rollback failure was not contained.** If decoder/admission processing failed and restoring the decoder checkpoint also failed, the transaction had no persistent unsafe state. The connection-generation transaction is now poisoned and rejects all further decoding; checkpoint failure also poisons before decoding begins.
9. **Verifier checkpoints did not cover all release-significant inputs.** `PROJECT_INFO.txt`, the Windows capture dependency manifest, and `RELEASE_MANIFEST.json` were absent from the resumable verifier fingerprint, so a stale checkpoint could reuse tests across changes those tests consume. They are now fingerprinted inputs.
10. **Offline package sealing did not reject undeclared package files and Q-gate source identity omitted release identity.** The final offline release verifier now detects files that exist in the package tree but are absent from the manifest, and `PROJECT_INFO.txt` participates in the implementation hash used by Q1–Q9 receipts.
11. **Protocol observation finalization did not seal the lifecycle.** `ProtocolInspector.finish()` is now idempotent and caches the final receipt; later `consume()`/`consume_poll()` calls are rejected instead of mutating an already-finalized observation.
12. **Generic driver-loss aggregation could never prove all-clean visibility.** The accumulator no longer begins with sticky UNKNOWN. UNKNOWN or positive drop evidence still dominates; all-clean is possible only when every observed poll explicitly says so. This does not certify the current Scapy backend.
13. **The offline package verifier trusted manifest shape more than the runtime seal.** Malformed rows, duplicate paths, unsafe paths, or a corrupted aggregate content digest could crash verification or escape a dedicated check. The offline verifier now validates these fields fail-closed and recomputes the aggregate release digest.
14. **Current operator documentation must not mutate hash-pinned historical bridge provenance.** The native bridge README contains obsolete historical installer wording but is part of the P44 integrity inventory. M12_004 preserves that byte-for-byte artifact and moves the current operator warning to release-level documentation instead of weakening provenance checks.

## Architecture decision retained

The existing system boundaries remain justified by current evidence: Protocol-specific logic is isolated behind contracts/canonical semantics; `anka_app` composes concrete systems; Execution is the sole physical-input authority; physical input remains disabled; current-client adapter activation remains evidence-gated. No evidence from this pass justified collapsing or rewriting those boundaries.

## Current Scapy/Npcap evidence limitation

The normal Windows backend can report ANKA's bounded in-process queue drops, but M12_004 still does not treat that as proof that the kernel/Npcap/libpcap path lost no packets. Low-level pcap statistics may be available on a target Windows host, but integrating an internal/driver-specific mechanism without target-host validation would create a false guarantee. Q10 must determine what loss telemetry is actually reliable on the supported host stack.

## Deliberately unresolved live-only risks

- Whether stopping the target Windows capture backend always completes promptly under driver failure cannot be proved in this non-Windows environment. Returning before callback/thread quiescence would weaken evidence integrity, so M12_004 does not add a speculative timeout that could seal evidence while producers still run.
- Current Dofus wire semantics, exact current-build adapter coverage, Unity Bridge observations, real CRA/ENU synchronization, and physical outcomes remain external-evidence questions.
- Q10/Q11 should expose these independent gaps in one bounded run; Q12/Q13 remain forbidden until their prerequisite evidence passes.

## Verification philosophy

Every corrected defect has a dedicated regression. The release is accepted offline only after the source tree, focused regressions, architecture/contracts, isolated broad verifier, Q0–Q9 receipts, M12 receipt, and deterministic release manifest are regenerated on the same frozen implementation. Final counts belong in the sealed verification receipts, not in assumptions written before the freeze.
