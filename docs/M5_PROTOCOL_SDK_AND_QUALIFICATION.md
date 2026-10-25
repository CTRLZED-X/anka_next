# M5 — Protocol SDK, Historical Adapter, and Upgrade Qualification

## Status

Historical adapter foundation: `REPLAY_CERTIFIED`. Current client build: `BLOCKED_MISSING_EVIDENCE`. Physical action authority: none.

## What M5 adds

- version-independent `anka_protocol.sdk` boundary;
- explicit adapter registry and lifecycle; adapter presence never means activation;
- exact-build selection only—no nearest/prefix fallback;
- stepwise lifecycle `STAGED → STRUCTURALLY_VALID → REPLAY_CERTIFIED → OBSERVATION_CERTIFIED → ACTION_SCOPED_CERTIFIED → ACTIVE`;
- promotion fences requiring disarmed input, no unresolved `MAY_HAVE_SENT`, and a fresh connection generation;
- `CandidateCanonicalBatch` and decoder-checkpoint contracts;
- transactional Protocol→Canonical handshake: rejection, uncertainty, exception, or invalid admission restores the pre-batch decoder context;
- exact opaque fingerprints: direction + wire name + length + SHA-256; a one-byte change becomes unknown again;
- consumer-driven semantic impact diff;
- current-build intake that can stage investigation but can never self-certify or self-activate;
- hash-bound historical 3.7.10.10 releases wrapping already ported historical semantics; immutable `r1` is archived and corrective `r2` is the executable replay release.

## Safety invariants

1. Protocol does not import Capture concrete implementation, Canonical implementation, Live State, Decision, Execution, Coordination, Workflow, Client, or App.
2. No raw/obfuscated wire identifier is required by downstream stable semantic contracts.
3. One unknown/unproven message fences all semantic candidates from the same envelope; no partial truth is committed around uncertainty.
4. Decoder context is pinned to adapter release, exact observed build, connection identity, and connection generation.
5. A Canonical reject/uncertain result cannot leave speculative decoder context advanced.
6. Historical replay evidence never certifies the current client build.
7. A staged/replay-certified adapter cannot activate merely by being registered or copied into the package.

## Historical release

`adapter-dofus-3.7.10.10-historical-m5-r1` remains preserved byte-for-byte under `reference/m5/releases/` and its original provenance remains in `reference/m5/historical_3_7_10_10_release.json`. The corrected executable replay release is `adapter-dofus-3.7.10.10-historical-m5-r2`, recorded in `reference/m5/historical_3_7_10_10_release_r2.json`. `r2` remains `REPLAY_CERTIFIED` only and has no action scopes.

## Remaining evidence

Fresh current-build fingerprint, current capture/identity evidence, world/fight/placement/Ready/first-turn/handoff/fight-end observations, semantic comparison, mutation/fault qualification, observe-only acceptance, and bounded action evidence are still required before live activation.
