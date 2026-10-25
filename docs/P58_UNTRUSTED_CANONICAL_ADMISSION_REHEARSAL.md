# P58 — Untrusted Canonical Admission Rehearsal (offline only)

## The boundary

Prior to P58 the P54 historical research chain and P56/P57 synthetic transactional
journal were separate. P58 adds a review-only compatibility boundary without
inventing a trusted decoder, process/window attestor, or physical-input driver.

`anka_contracts.admission` defines bounded immutable *claims*:

- `AdmissionScope`: session/account generation/fight/build/adapter/flow and
  transport/process/window generations, plus a caller-supplied capture SHA-256.
- `UntrustedPacketClaim`: exact per-message evidence key, bytes, claimed source
  capture SHA-256, direction, and a recomputed message body SHA-256.
- `UntrustedCharacterClaim`: actor ID, name digest, and linked source message.
- `AdmissionRehearsal`: one identity claim, its packets, and typed CanonicalDraft
  candidates, all with explicit untrusted provenance.

`anka_canonical.admission_review.review_admission_rehearsal` rejects mixed
build/adapter/flow/generation, mixed capture digests, missing/duplicated packets,
wrong direction, reordered packet sources, missing character evidence, semantic
sources not present in the packet table, duplicate/conflicting source facts,
and semantic records not later than the character witness. Enemy actor
observations on the same flow are allowed when the local actor is also present.
One valid source message can yield different distinct kinds of *candidate* facts.

The positive result is named `STRUCTURALLY_CONSISTENT_UNTRUSTED`, and it is **not
an approval to commit**. Every result, including a positive one, retains these
mandatory blockers:

1. Trusted capture origin and driver-loss attestation are unavailable.
2. Current-client independent build/semantic verification is unavailable.
3. Independently verified Windows process/window/character association is unavailable.
4. Character breed and account role are not verified.
5. An authoritative Canonical writer is not implemented.

Source-body SHA-256 checks detect inconsistency in *caller-provided* bytes,
not spoofed network data. A capture digest typed into JSON is not a verified
file hash. The P53/P54 historical identity evidence still has no live authority.
The review is not evidence of a current-client parser, and does **not** generate
`OfflineStateEvent` or `OfflineBatchEnvelope`; the P56 journal rejects the review
and rehearsal object types. No live state mutation or physical input is possible.

## Verification and limitations

Permanent `tests/test_p58_untrusted_admission_boundary.py` includes 29 test
methods for malformed/mixed/reordered sources, inconsistent capture versions,
duplicate facts, foreign actors, historical versions, privacy, and explicit
refusal by the synthetic durable writer. Preflight `check`/`setup` includes a
small consistency+quarantine+journal-denial smoke. The tests check structural
behavior **only**; none certifies a present-day Dofus client.

Further work requires independent, real Windows+client evidence with trusted
capture timestamps/loss telemetry, build-specific decoder validation against
independent semantic truth, strong process/window/socket/character identity,
coverage of Ready/first turn/handoff/fight outcomes, and live safety review.
Only after that should a different, explicitly reviewed authoritative writer
and identity-attestation contract be developed. P58 must never be rebranded as
that writer merely because a self-asserted claim produces consistent metadata.
