# M12_005 — Release Truth and Observer Isolation Hardening

## Scope

This pass began from the sealed M12_004 release and deliberately searched for failure classes not proven merely by the existing green gates. It does not redesign working systems or claim new live-game knowledge.

## Reproduced defects

### 1. Diagnostic sink failure could control Protocol progress

A fault-injected observer whose `record()` raises `OSError` caused `ProtocolInspector` quarantine handling to raise the observer exception after the Protocol state had already been mutated. The same risk existed during final Protocol receipt emission. This violates the design rule that Observability is best-effort evidence rather than gameplay/Protocol authority.

**Correction:** ordinary observer exceptions are contained at Protocol quarantine and Protocol finalization. Protocol state/receipts remain authoritative. `BaseException` is not swallowed.

### 2. Diagnostic sink failure could replace Capture/ingress success

The bounded Capture sample and passive ingress probe emitted completion diagnostics without containing a faulty injected sink. A diagnostic implementation fault could therefore convert otherwise valid read-only evidence into a startup failure.

**Correction:** completion-record failures are contained. Capture/ingress results remain unchanged and physical authority remains disabled.

### 3. Current release documentation had stale truth

The M12_004 root handoff files still contained copied M12_003-era claims such as 349 modules and `LIVE_RUNTIME_NOT_IMPLEMENTED` as the current top-level startup blocker. Historical P-series receipts may legitimately preserve old behavior, but current handoff documents must not contradict current source/receipts.

**Correction:** root current-state documents were rewritten to distinguish current truth from historical evidence. Release tests reject known stale phrases.

### 4. Resumable verifier fingerprint omitted current handoff documents

Once release-truth tests depend on current root documentation, a checkpoint could otherwise reuse an old PASS after a documentation change.

**Correction:** `README.md`, `IMPLEMENTATION_STATUS.md`, and `00_READ_FIRST_NEXT_CHAT.md` participate in the verifier input fingerprint.

### 5. Architecture input-authority guard omitted direct window-control APIs

The guard already rejected common mouse/keyboard primitives but did not cover several Win32 APIs that can directly alter/control another window.

**Correction:** `SetForegroundWindow`, `SetActiveWindow`, `SetFocus`, `PostMessageW`, and `SendMessageW` are execution-only and mutation-tested.

### 6. Execution settlement had a real race between driver return and authoritative outcome settlement

`DefinitiveExecutionLedger.mark_sent()` previously read action state and transitioned it in separate transactions. An authoritative outcome could settle the action between those operations, leaving durable truth correct while `ExecutionService.submit()` reported an artificial uncertainty/illegal transition. The same split existed across late `NOT_SENT`, uncertainty and terminalization paths.

**Correction:** state inspection and transition/passthrough are one `BEGIN IMMEDIATE` transaction. Once the external driver boundary is entered, outward `ActionOutcome` is derived from durable ledger truth. If the durable ledger itself becomes unavailable after driver entry, Execution disarms and returns non-retryable `UNCERTAIN`; it never manufactures `REJECTED_NOT_SENT`.

### 7. Protocol transactions did not fully prove release/checkpoint/rollback provenance

Fault injection showed that a malformed future adapter could claim a stale or foreign candidate checkpoint, and rollback success was trusted without proving that adapter state actually returned to the saved checkpoint.

**Correction:** Protocol binds runtime descriptor, observed build, connection/generation, candidate checkpoint and post-decode checkpoint exactly. Restore is followed by a fresh checkpoint proof. Failed or unverifiable rollback poisons that connection generation. Rejected/uncertain post-decode admission also poisons the stream generation so the decoder cannot silently skip rejected bytes and continue with a stream hole.

### 8. Ordinary TCP fragmentation was incompatible with the old transaction rule

A valid historical length-prefixed message split across two `WireEnvelope`s reproduced a fundamental failure: the first partial envelope produced no semantic candidate, Canonical rejected it, Protocol rolled back the framing buffer, and the second half could never complete the message.

**Correction:** `FRAMING_IN_PROGRESS` is an explicit zero-semantic state. It may advance only the exact decoder checkpoint and grants no game-state fact. A later envelope can complete the frame. A complete unknown message remains fail-closed. Fragmented semantic output also retains all causal envelope references, while pending provenance is bounded to bytes still buffered.

### 9. Historical Protocol release identity was being changed by legitimate fixes

The 3.7.10.10 historical adapter was already published as hash-bound `r1`. Updating `r1` in place to incorporate fragmentation/wire fixes would defeat the versioned-adapter requirement.

**Correction:** the exact old `r1` source bytes are archived under `reference/m5/releases/adapter-dofus-3.7.10.10-historical-m5-r1/` and reconstruct the original code hash. The corrected executable historical replay adapter is `r2` with a distinct hash and remains `REPLAY_CERTIFIED` only; neither release has live/action authority.

### 10. Protocol framing had an unbounded frame-fanout path

A legal-size input buffer can contain a very large number of tiny length-prefixed frames. Returning all frames from one feed could cause pathological CPU/memory fan-out before semantic admission.

**Correction:** framing now has a generous per-feed frame-count bound and quarantines `FRAME_COUNT_LIMIT` rather than allocating an unbounded result. Deterministic malformed/random framing fuzzing was added to the verification campaign.

### 11. Canonical snapshots could pass storage integrity with false semantic identity

A snapshot row could be coherently rewritten together with its SQLite row hash while leaving the snapshot's own semantic digest stale. The runtime reader verified storage bytes but did not independently recompute semantic identity.

**Correction:** every snapshot read now recomputes the deterministic StateProjector semantic digest and snapshot ID. Storage-hash consistency alone is insufficient.

### 12. Q12 action-scope evidence was not re-bound at the final Windows driver boundary

The Windows action enablement carried an acceptance-receipt SHA-256, but construction did not compare it with the current Q12 receipt. The physical driver also relied too heavily on upstream Execution validation for lease/client/target proof binding.

**Correction:** driver construction binds the current release manifest, config, Q12 receipt, run ID and run generation. `send()` independently revalidates lease/action/account, client identity/build/proofs, loadout proof for casts and semantic target fingerprint before any Windows input primitive is used.

### 13. Coordination could issue a permit from incomplete turn-epoch evidence

The coordinator filtered zero turn epochs before comparing the epoch set. Required observations with epochs `{0, 1}` could therefore appear as the coherent singleton `{1}` when both accounts named the same owner.

**Correction:** every required member must prove the same **positive** turn epoch and the same owner before `TURN_ACTIVE` or a turn permit is possible.

### 14. Repeated recovery timeouts could strand Workflow in `RECOVERING`

A watchdog timeout while already recovering overwrote the original `resume_phase` with `RECOVERING`. A later `RECOVERY_SUCCEEDED` could then resume into `RECOVERING` and clear the only original resume target.

**Correction:** repeated recovery attempts consume the bounded recovery budget while preserving the original phase being recovered.

### 15. Workflow restart did not bind persisted state to its compiled mission plan

`MissionWorkflow.resume(plan, snapshot)` accepted a snapshot created under a different route/config/watchdog/recovery plan.

**Correction:** every workflow snapshot is bound to the exact compiled `missionplan-*` identity, and resume fails closed on a mismatch.

### 16. Restart policy for partially buffered Protocol state was clarified rather than over-engineered

Canonical durably binds the decoder checkpoint hash but does not persist arbitrary adapter-private framing bytes. Persisting those bytes would require a new cross-store atomicity design.

**Decision:** do not add speculative private-state hydration. A fresh process attaching mid-stream is already marked with transport discontinuity and rejected. Recovery waits for a provably fresh TCP connection generation. This preserves correctness without creating a second protocol-state authority.

### 17. Release packaging excluded only `.q*` verifier checkpoints

A fresh full isolated-verifier run created `verification/.m12_005_full_checkpoint.json`. The release builder excluded the historical `.q*` gate checkpoints but treated this differently named hidden verifier work-state as shippable content. The offline release verifier correctly rejected the undeclared file after receipt regeneration.

**Correction:** all hidden files under `verification/` are mutable verifier work-state and are excluded from release content regardless of their checkpoint naming convention. Visible sealed receipts remain included. A packaging regression now asserts that hidden verifier state cannot enter the manifest.

### 18. Local coverage data and symlinked files could contaminate a release

The release file walker would include a root `.coverage` database created by local test tooling, so rebuilding the same source after a coverage run could change the release contents. It also followed file symlinks, which could package bytes from outside the project root under an apparently local archive name.

**Correction:** common build/test cache directories and root `.coverage*` work-state are excluded. File symlinks are rejected rather than followed. Release contents therefore depend on project artifacts, not incidental local test state or out-of-tree links.

### 19. Two provenance files collided on the target Windows filesystem

The tree contained both `provenance/REUSE_MANIFEST.json` (the definitive M0 reuse ledger) and `provenance/reuse_manifest.json` (the older P66 copied-asset checksum list). They are distinct on Linux but collide on the case-insensitive Windows filesystems the project targets, so ZIP extraction could overwrite one with the other.

**Correction:** the older copied-asset list is now named `provenance/P66_COPIED_ASSET_MANIFEST.json`, and the current preflight points to that explicit historical-purpose name. The release builder also rejects any future case-fold path collision before generating a manifest or ZIP. Frozen P66 reference archives/manifests remain untouched.

### 20. Current handoff gate totals could drift after adding regressions

Fresh M12_005 gates increased several test totals, while the current status table still displayed M12_004-era counts. That made the prose stale even though the receipts were correct.

**Correction:** current Q4-Q7 totals were updated and a release-truth regression now reads the sealed receipt JSON and checks the current status-table line. Historical M12_003/M12_004 sections may retain their historical totals.

## Acceptance boundary

These are offline engineering improvements. They do not certify Windows/Npcap behavior, current Dofus semantics, character identity, calibration/loadout, physical action scopes, or a real CRA+ENU mission. Q10-Q13 remain mandatory.
