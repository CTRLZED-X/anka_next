# M12_006 — Causal Diagnostic and Full-Chain Hardening

## Scope

M12_006 starts from the sealed M12_005 offline baseline. The purpose is not to add speculative architecture. It closes reproduced gaps in causal observability and in the zero-input world-to-fight execution chain so that a future live failure can be reconstructed from authoritative evidence without allowing diagnostics to become gameplay authority.

This remains an **offline / zero-physical-input** release. It does not certify Q10 Windows behavior, Q11 current-build Dofus semantics, Q12 physical action scopes, or Q13 a real mission.

## Reproduced defects and corrections

### 1. Bounded recent-event export could lose the first divergence

A last-N timeline can retain the visible terminal symptom while overwriting the earlier safety/action event that caused it.

**Correction:** diagnostics now act as a bounded flight recorder with two independent lanes: recent context plus priority evidence. Safety, settlement, committed-authority, missing/conflicting evidence, and critical operation edges are retained preferentially. Loss/overwrite/size omission is explicit and downgrades bundle completeness instead of being hidden.

### 2. Persistent diagnostic storage failure erased useful in-memory evidence

Run-directory or journal failure previously made the observer effectively unavailable even though bounded memory could still retain the causal history.

**Correction:** in-memory evidence health is independent from persistent journal health. Disk/path failure is recorded as degraded observability while the bounded memory recorder continues.

### 3. Diagnostic export could perturb the runtime

Incident export previously performed analysis/ZIP work while holding the recorder lock.

**Correction:** export atomically freezes bounded observer state, releases the live lock, then performs analysis and ZIP I/O on the immutable copy. A deliberately stalled ZIP writer cannot block another producer from recording a safety event.

### 4. Advanced forensic analysis could itself prevent incident creation

A failure inside artifact construction could re-enter the same failing path and leave no usable incident.

**Correction:** a deliberately simple emergency envelope is a second line of defense. It preserves the original application failure and bounded timeline while marking advanced analysis unavailable. It does not leak analyzer exception text or claim a root cause.

### 5. READY reconstruction could borrow evidence across accounts or fights

A shared party Ready barrier can mask a missing per-account server acknowledgement, and a completed earlier fight can hide an incomplete later fight if analysis is scoped too broadly.

**Correction:** READY analysis is party-aware and latest-fight-epoch aware. For every required account it separately proves request -> Execution admission -> input sent -> Protocol Ready observation -> Canonical Ready commit, with Protocol/Canonical batch correlation. Only then are the shared party barrier, first owner, and first Decision frame considered.

### 6. The production READY/placement path had circular turn authorization

The controller requested a combat turn permit before planning. Placement and Ready create the conditions needed for the first turn, so they cannot depend on a permit that requires Ready/turn-owner proof.

**Correction:** planning happens first and the plan selects an explicit authority scope. `TURN` remains strict. `PLACEMENT`, `READY`, `JOIN`, `WORLD`, and `FIGHT_ENTRY` use phase-appropriate proof-bearing permits. Execution revalidates the exact authority scope immediately before the external boundary; permits are not interchangeable.

### 7. JOIN authority was not bound tightly enough to the target fight

A same-epoch permit could be insufficiently specific for a join plan.

**Correction:** JOIN authority is bound to the exact target fight ID, fight epoch, and map and is rechecked at both planning authorization and Execution command admission.

### 8. Pre-turn actions were not protected by the Workflow pending-action fence

Placement/Ready side effects could become uncertain without blocking a phase transition.

**Correction:** the same unresolved-action reconciliation discipline now applies before the combat turn. Placement/Ready phase changes cannot erase an unresolved external side effect.

### 9. The Q9 lifecycle skipped world and fight-entry execution boundaries

Earlier zero-input integration jumped some world/fight-entry phases by applying Workflow evidence directly.

**Correction:** Q9 now executes the complete synthetic chain through Decision -> scoped authority -> Execution -> Canonical consequence -> settlement for world movement, encounter/fight entry, join, placement, and Ready before the first turn, then continues through combat, End Turn/handoff, fight end, and world re-entry. The driver remains fake-only with zero OS input.

### 10. Workflow and Execution events could disappear due correlation plumbing

Callers supplying the same `run_id` already owned by the recorder could cause duplicate-key failure and silently lose an event.

**Correction:** matching caller-supplied run/invocation IDs are consumed and validated. Foreign IDs are dropped instead of being mixed into a run.

### 11. Workflow relied on synthetic external diagnostic publication

Integration tests could manufacture Workflow-looking events rather than proving the real Workflow authority emitted them.

**Correction:** `MissionWorkflow` now publishes its own committed phase changes, pending/cleared action fences, recovery starts, blocked state, and rejected signals. The entire diagnostic payload construction is best-effort so an observer/payload bug cannot change a committed transition.

### 12. Planner authorization failures were diagnostically silent

A valid Decision plan denied before Execution returned `WAIT`, making it hard to distinguish “planner chose nothing” from “authority refused a real plan.”

**Correction:** `workflow.action_authorization_blocked` records exact scope, kind, action key, goal, and failure reason. Dispatch results also preserve uncertainty/terminal information.

### 13. Canonical commit lacked a post-commit Live-State view in incidents

A committed batch could be proven while the resulting immutable actor state was absent from the incident timeline.

**Correction:** after successful Canonical commit, a passive publisher records bounded Live-State snapshot identity plus actor HP/AP/MP/cell/Ready proof summaries. Observer failure cannot alter Canonical commit truth.

### 14. Per-action postmortem reconstruction was incomplete

The bundle had timelines but no bounded action-centric view answering whether an action was requested, authorized, sent, or settled.

**Correction:** `analysis/action_lifecycles.json` reconstructs each action's request/admission/send/settlement state, physical-input states, failure codes, authorization blockers, and nearby Protocol/Canonical/Live-State context. Nearby semantic events are explicitly **context only, never causal proof**.

### 15. Incident analysis references were not fully self-verifying

A structurally valid bundle could theoretically contain an analysis artifact referring to an event absent from the shipped timeline.

**Correction:** the verifier checks diagnosis, READY analysis, generic boundary graph, action lifecycle rows, authorization blockers, and nearby context references against the exact included event IDs. It also rejects a lifecycle artifact that promotes nearby semantic context to causal proof.

### 16. Execution failure branches lacked explicit postmortem events

Several safe rejections/faults were behaviorally correct but weakly observable: durable prepare rejection, input lease contention, final guard drift, post-send exception, ledger loss after driver entry, ignored outcome evidence, terminal unresolved outcome, and arbiter safety faults.

**Correction:** these branches now emit bounded, correlation-bearing Execution events while preserving durable ledger authority and fail-closed behavior.

### 17. Fatal incidents lacked safe stack location evidence

Only exception type/boundary was retained, which can force a future investigator to rediscover the failing call path.

**Correction:** fatal command events may include sanitized project-relative traceback frames containing only file/function/line. No locals, source-line text, arbitrary traceback strings, or absolute user-home paths are exported.

### 18. Incident ZIP validation needed additional hostile-input checks

**Correction:** verification rejects case-insensitive ZIP-name collisions, malformed/cross-run timeline identity, duplicate producer sequences, missing analysis evidence references, invalid completeness claims under evidence loss, unsafe paths, bad hashes, oversize bundles, and raw-protocol policy violations.

### 19. Diagnostic journals could block runtime producers

The recorder accepted a queue-capacity setting but persistence was synchronous under the recorder lock. A slow Windows disk could therefore perturb Capture/Protocol/Execution timing.

**Correction:** bounded asynchronous general and priority journal queues now decouple disk I/O from in-memory recording. Writer startup/write/flush failures degrade observability and preserve bounded memory evidence; shutdown waits are bounded.

### 20. Diagnostic correlation stopped at the Execution boundary

Workflow created an action trace, but Execution events did not carry it.

**Correction:** `ActionCommand` carries an optional validated trace ID and Execution republishes it on action events. Action lifecycle reports also link the exact Decision `plan_result` by plan ID.

### 21. Logical fake delivery could be confused with OS physical input

Synthetic `execution.input_sent` did not distinguish fake-driver delivery from actual host input.

**Correction:** diagnostic `physical_input_state` now describes actual OS-input risk independently from logical delivery. Q9 fake-only actions report `NOT_SENT`; Windows physical delivery uses `SEND_STARTED` / `SENT` / `MAY_HAVE_SENT` as applicable.

### 22. Free-form GPT guidance needed a machine-verifiable index

A prose-only read-first page can drift or be reformatted.

**Correction:** every schema-2 bundle includes `analysis/gpt_summary.json` with finding status, first divergence, observed boundary, suspected owner/confidence, evidence refs, physical-input state, coverage gaps, snapshots, settlement/recovery/history summaries, and next verification. The verifier cross-checks critical fields against the included evidence.

### 23. A manifest-consistent ZIP could omit essential forensic artifacts

Integrity of present files did not prove completeness of the definitive bundle format.

**Correction:** schema-2 verification now requires the complete forensic artifact set. Removing `GPT_READ_FIRST.md`, the machine summary, core timelines, diagnosis, action/READY/boundary analysis, gaps/history/recovery/proven-facts reports, or flight-recorder metadata causes verification failure even if the ZIP manifest is recomputed.

### 24. Untraced exports could falsely label the export boundary as the first divergence

**Correction:** when no explicit causal trace establishes a break, `GPT_READ_FIRST.md` and the machine summary say `NOT_ESTABLISHED` and separately identify the observed/export boundary. Historical similarity remains `SIMILARITY_ONLY` and never reuses root-cause authority.

### 25. Diagnostic sanitization could silently remove evidence while the bundle still looked complete

Bounded sanitization intentionally truncates oversized strings/collections, but that information loss itself is diagnostically relevant.

**Correction:** the recorder counts sanitization truncations, the recovered-journal path redetects them, bundle completeness is downgraded to `PARTIAL`, and the verifier rejects a bundle containing truncation markers whose flight-recorder metadata claims none occurred.

### 26. Secondary timeline indexes could omit shipped critical evidence

The priority/error streams are convenience indexes for GPT and operators. A checksummed ZIP could previously omit a safety/error row from one of those views while retaining it in the primary timeline.

**Correction:** the verifier now requires every priority-classified primary event to appear in the priority view and requires the error view to equal the complete set of shipped `ERROR`/`CRITICAL`/`SAFETY` events. Secondary views must also preserve primary ordering.

### 27. Bundle-level completeness could disagree with run-level evidence truth

The outer ZIP manifest originally derived completeness only from subsystem sections, while the run manifest also knew about recorder overwrites, queue drops and other evidence loss.

**Correction:** the outer manifest takes the same completeness truth as `run_manifest.json`; the verifier cross-checks completeness and dropped-event totals so a rehashed bundle cannot tell two different stories.

### 28. A hard process kill could leave journals but no incident ZIP

An externally terminated process can end before the normal exception/export path runs. The next session previously detected the unclean run but did not convert its durable observer evidence into a shareable incident.

**Correction:** the next `start` performs bounded best-effort recovery of previous unclean runs after acquiring start authority. It validates exact run/invocation identity, deduplicates the general/priority journals, rejects conflicting sequence evidence, excludes symlinked run folders, and exports a normal verifier-clean `UNCLEAN_PROCESS_EXIT` incident. The recovered bundle is always `PARTIAL` with `source_tail_uncertain=true`; it never infers whether a missing crash-tail action succeeded. Recovery is idempotent and scan-bounded, and already-clean/recovered recent runs cannot starve an older unclean run.

### 29. Malformed external diagnostic events could poison a later incident

Foreign producers could supply a syntactically valid DTO whose event ID namespace or timestamp would only be rejected when the final ZIP was verified.

**Correction:** recorder run/invocation namespaces are validated at creation, external event IDs/parent IDs/timestamps are checked before admission, and backward monotonic time is rejected. Malformed diagnostic evidence becomes an explicit observer degradation instead of invalidating the whole postmortem.

### 30. Rehashed timelines could be causally reordered

Checksums prove byte identity only relative to a manifest; an attacker/corruption could rewrite both the timeline and manifest while preserving all event IDs.

**Correction:** schema-2 verification now requires strictly increasing producer order, non-regressing monotonic time, and secondary-view ordering consistent with the primary timeline. Causal order is therefore part of the verified diagnostic contract rather than an analyzer assumption.

## Diagnostic trust model

1. Canonical durable receipts/state and Execution durable ledger remain authority sources.
2. Diagnostic events are evidence *about* those systems; they never grant permits or mutate gameplay state.
3. `AUTHORITY_COMMITTED` means the producer reports an already-committed authority fact. It does not turn Observability into that authority.
4. Protocol/Canonical/Live-State events near an action are context unless an explicit correlation contract proves causality.
5. Any recorder loss or unavailable persistence is represented as partial evidence.
6. A diagnostic subsystem failure must not change Capture, Protocol, Canonical, Workflow, Coordination, Decision, or Execution authority.

## Expected live-debug workflow

For a future live failure, inspect in this order:

1. `GPT_READ_FIRST.md` and `run_manifest.json` for control state, physical-input state, completeness, and recorder health.
2. `analysis/diagnosis.json` for the first evidence-supported divergence, not merely the visible symptom.
3. `analysis/party_ready.json` for per-account READY reconstruction when relevant.
4. `analysis/action_lifecycles.json` for request/admission/send/settlement and authorization blockers.
5. `analysis/boundary_graph.json` and `logs/relevant_timeline.jsonl` for chronological causal context.
6. `snapshots/` for release, host, capture, bridge, and startup state when present.
7. `analysis/evidence_gaps.json` and `analysis/evidence_request.json` before asking for another live test.

A new live test should be requested only for evidence that cannot be obtained from the bundle, source, deterministic replay, or existing recorded evidence.

## Acceptance boundary

M12_006 aims at the maximum practical **offline/zero-input** confidence available in this environment. It deliberately does not claim that live Dofus behavior is known. Q10-Q13 remain mandatory and must use the exact sealed release that passed the final verification campaign.

### 31. Crash recovery could emit an incident that failed its own verifier

A damaged durable journal could contain events with backward monotonic time or malformed recovery-only ordering. The recovery path previously exported those rows and wrote its idempotence marker before proving that the reconstructed ZIP was internally valid.

**Correction:** recovery now validates timestamp/event identity and monotonic/producer ordering before reconstruction, quarantines invalid rows as explicit evidence loss, self-verifies the generated incident, deletes a failed reconstruction, and writes the recovery marker only after verification PASS. Symlinked journal files are rejected rather than followed.

### 32. Evidence loss could overstate a missing edge as a proven first divergence

A bounded recorder can explicitly know that evidence was overwritten, dropped, unavailable on disk, or lost in a crash tail. In that situation an absent expected event cannot prove that the event never occurred or that no earlier divergence existed.

**Correction:** GPT-facing findings now distinguish `DIVERGENCE_IDENTIFIED` from `DIVERGENCE_CANDIDATE`. Any known recorder loss scopes a candidate to `INCLUDED_EVIDENCE_ONLY`, sets `absence_is_conclusive=false`, and carries the crash-tail uncertainty flag when applicable. Complete-recorder traces can still identify a divergence. The underlying evidence-linked diagnosis remains available, but the summary cannot silently promote absence under loss into certainty.

### 33. Long-run action indexing could omit the early dangerous action

The action lifecycle artifact was bounded to the newest 32 actions. An early `MAY_HAVE_SENT`, terminal-unresolved, failed, or sent-without-settlement action could therefore survive the flight recorder but disappear from the GPT action index after many later successful actions.

**Correction:** lifecycle selection is now `RISK_FIRST_THEN_RECENT`. High-risk/unresolved actions are retained before ordinary recent actions. If even the risk set exceeds the bound, both the earliest and latest risky actions are preserved and omissions are counted explicitly.

### 34. Unsettled actions lost the semantic evidence that arrived after send

For an action without a correlated settlement, the semantic-context window ended at the last action-tagged event. Later Protocol/Canonical/Live-State observations could therefore be omitted even though they are exactly the context needed to understand an unresolved send.

**Correction:** unsettled actions keep bounded semantic context until the next same-account action begins, or until incident end when no next action exists. The artifact records how that window ended and continues to label semantic context as non-causal unless an explicit correlation contract proves otherwise.

### 35. READY retries in the same fight could borrow an older attempt's acknowledgement

Fight-epoch scoping prevents cross-fight borrowing, but multiple READY attempts can still occur inside one fight. Starting reconstruction from the earliest request allowed an old attempt's Protocol/Canonical acknowledgement to hide a newer incomplete retry.

**Correction:** each account is reconstructed from its latest READY request within the newest target fight epoch. Execution remains bound to that exact action ID and Canonical Ready remains bound to the Protocol batch span. Older same-fight attempts cannot satisfy the current retry.

## 36. GPT-summary certainty is verifier-bound to recorder truth

M12_006 closes a final self-consistency gap between the machine-readable GPT summary and the authoritative flight-recorder metadata. A checksummed incident is rejected if `analysis/gpt_summary.json` hides crash-tail uncertainty, claims conclusive absence after any known recorder loss, or advertises a complete-recorder divergence scope when only included evidence is trustworthy. Emergency `ADVANCED_ANALYSIS_UNAVAILABLE` bundles remain intentionally exempt from advanced-analysis fields while retaining their simpler verifier contract.

Crash-recovered incidents are also regression-tested to expose `source_tail_uncertain=true`, `absence_is_conclusive=false`, `first_divergence_scope=INCLUDED_EVIDENCE_ONLY`, and an explicit crash-tail warning in `GPT_READ_FIRST.md`. This prevents GPT or an operator from interpreting missing post-crash evidence as proof that an action did not happen.

## 37. Verification subprocess capture cannot be held open by orphan descendants

The release verifier itself had an observability-style liveness flaw: pipe-based stdout/stderr capture could remain open when a verified pytest/unittest parent exited but a descendant inherited the pipe. This could make a successful test file appear hung far beyond its real completion. `run_bounded_tree()` now captures into seekable temporary files, makes `wait(timeout)` the sole wall-clock authority, kills the dedicated POSIX process group on timeout, and removes surviving group members after a successful parent exit. Regression tests cover both the successful-parent/orphan case and a genuinely running parent+descendant timeout.

This change strengthens release evidence rather than gameplay behavior: a test process tree can no longer extend or ambiguously stall the verifier merely by inheriting output handles.

## 38. Diagnostic persistence accidentally remained a command-control dependency

The recorder itself already retained bounded in-memory evidence when its run directory was unavailable, but the top-level CLI still aborted immediately on `observer.available == false`. That made a diagnostic disk/permission problem a control-authority decision and contradicted the observer-failure contract.

**Correction:** the CLI now reports `ANKA_OBSERVABILITY=PARTIAL`, records a passive `observability.storage_unavailable` event in memory, emits the bootstrap emergency marker best-effort, and continues the requested command. Canonical, Execution and Coordination remain the systems that may block for missing authoritative truth. Incident export can still fall back to the OS temp directory. A regression proves a command completes while persistent observer storage is unavailable.

## 39. Offline Capture inspection could still be changed by a broken diagnostic sink

The Windows live sampler and Protocol inspector already absorbed observer faults, but the offline PCAPNG Capture facade still called the observer directly on accepted/rejected evidence paths. An injected sink exception could therefore replace the real Capture result.

**Correction:** Capture diagnostic publication is now best-effort at the facade boundary too. A broken observer cannot alter a valid transport receipt or a Capture rejection classification.

## 40. A known first broken boundary could be confused with a uniquely known root cause

The forensic analyzer preserved multiple candidate failure codes, but the GPT-facing summary did not explicitly distinguish “we know where the chain first broke” from “we know exactly why it broke.”

**Correction:** incident summaries now carry `cause_status = UNDETERMINED | SINGLE_SUPPORTED | MULTIPLE_PLAUSIBLE` plus the bounded candidate-cause list. `finding_status` remains independently responsible for boundary certainty (`DIVERGENCE_IDENTIFIED` versus loss-degraded `DIVERGENCE_CANDIDATE`). The verifier cross-checks cause status/list agreement against `analysis/diagnosis.json`, and mutation tests reject a rehashed bundle that falsely upgrades multiple plausible causes into a single supported cause.

## Current frozen offline evidence

Implementation source SHA-256: `9f7d27d098bf70bbddac38cbfaaf441c278001c0ebe92d23e9b58039dd846c56`.

Fresh source-bound evidence before final package-manifest sealing: Q4 **713 tests + 144 subtests**, Q5 **405 + 13**, Q6 **209 + 329**, Q7 **143 + 75**, Q8 **112 + 7**, Q9 **22 + 9**, and M12 **202 + 21**, all PASS with zero physical OS input. The final whole-project isolated verifier is intentionally run only after `RELEASE_MANIFEST.json` is frozen so its result covers the exact package definition rather than a predecessor manifest.

## 41. M12 release-content attestation was self-referential

The M12 verifier previously embedded `release_content_sha256` from `build_manifest()` into `M12_offline_release_receipt.json`, while that same receipt is itself a shipped release file. Writing the receipt therefore changed the exact file set whose aggregate hash it had just reported. The final release manifest remained independently verifiable, but the M12 receipt's embedded package hash could never be a stable statement about a package containing itself.

**Correction:** M12 now attests a **self-excluding release-selection model**: it removes only `verification/M12_offline_release_receipt.json` before computing the model count/digest. The definitive post-receipt package hash is owned by `RELEASE_MANIFEST.json` and checked by `tools/verify_release_offline.py`. A regression proves that changing only the M12 receipt bytes cannot change the model M12 claims to verify. This removes the circular dependency while preserving the final manifest as the package authority.
