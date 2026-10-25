# P53 — Historical character → TCP flow → Windows process research identity

Date: 21 October 2026

## Purpose

P52 can establish only an anonymous process/socket topology. P53 closes the next **offline historical** boundary by recovering one explicit R5.198 world-identity semantic and composing it with the existing P51/P52 host-flow evidence.

The output remains research-only. It is **not** a current-client identity provider, does not create `CharacterEvidence`, does not commit Canonical state and cannot authorize mouse/keyboard input.

## Historical source inspection finding

The recovered R5.198 Dofus 3.7.10.10 world handler contains character-name matching in both `jnj` and `jns` paths. However, the version-local handler registry explicitly declares the `LOCAL_ACTOR` capability for `jnj`, while its `jns` binding declares only `MONSTER_GROUPS`.

P53 preserves that inconsistency rather than silently choosing the implementation over the registry:

- `jnj`: accepted as a **historical identity research witness** when the configured name matches exactly (case-insensitive) or the documented `Name-[Guild]` form.
- `jns`: always reported as `CAPABILITY_UNDECLARED` for local-actor identity and never emits an identity observation.

The exact R5.198 `world.py` source is stored inertly as `reference/protocol/historical_3_7_10_10/archived_source/world_identity.source.txt`. Its source hash and a small discrepancy manifest are verified during normal `check` / `setup`.

## New contracts and decoder

`anka_contracts.historical_identity` defines:

- `HistoricalIdentityScope`: exact historical build, flow digest, transport generation and configured expected character name.
- `HistoricalIdentityObservation`: configured name, historical actor id, cell id, map id and exact `EvidenceRef` source coordinate.
- `HistoricalIdentityResult`: bounded research outcome with zero authority fields.

`anka_protocol.adapters.historical_identity` performs the narrow `jnj` mapping. It rejects wrong builds, wrong direction, wrong flow/generation, malformed protobuf, missing/duplicated map or entity fields, ambiguous duplicate character matches and invalid actor/map values.

It never creates a current `CharacterEvidence` object and never claims a breed.

## Process/flow/character composition

`anka_app.ingress_readiness.historical_character_process_topology` combines:

1. the existing P51 two-snapshot Windows TCP-owner consistency check;
2. the P52 anonymous process/socket topology;
3. one historical `jnj` identity witness whose evidence flow digest must exactly match the private capture flow token.

The function emits only aggregate counts. Character names, PIDs, HWNDs, IP addresses, ports and flow tokens are not returned.

It rejects or downgrades:

- duplicate socket selectors;
- a character claimed by more than one simultaneous flow;
- two configured characters claimed by one process;
- forged/mismatched flow-digest witnesses;
- unexpected character names;
- missing character witnesses;
- unstable or ambiguous Windows flow ownership.

Even the clean two-account synthetic case returns `HISTORICAL_CANDIDATES_ONLY` with:

- `account_binding_verified = false`
- `current_build_certified = false`
- `independent_current_character_witnesses = 0`
- `canonical_commits = 0`
- `physical_input_sent = false`
- `actionable = false`

## Normal preflight

`check` and `setup` now verify:

- the P53 historical identity source/manifest hashes;
- two synthetic historical `jnj` name witnesses;
- two independent stable process/socket candidates;
- the `jns` registry inconsistency guard;
- a contradictory owner case that must not become a clean binding.

No Windows API, network capture, Canonical write or physical input is executed by this smoke test.

## Verification

For the exact tested source fingerprint `96e4669811fc140b0192459f37ce54f966214b12c160b6c9a53d639e301ebece`:

- new P53 tests: **31 passed**;
- focused P45/P47/P51/P52/client/P53/protocol group: **196 passed**;
- full module-isolated inventory: **80 / 80 modules, 1,387 tests passed**;
- `check`: PASS;
- `setup`: PASS;
- architecture boundaries: PASS, 13 packages / 271 Python modules;
- preserved reference assets: 165 / 165 verified;
- `start`: intentionally BLOCKED, exit code 40 / `LIVE_RUNTIME_NOT_IMPLEMENTED`;
- latest generated incident ZIP: integrity PASS.

A large single-process pytest attempt was interrupted by the execution environment and is not counted. The successful release gate is the source-bound module-isolated verifier above.

## What P53 does **not** prove

P53 does not prove that a modern client uses the same `jnj` schema, that the passive capture is complete, that an observed historical actor is currently logged in, that the character is CRA/Enutrof, or that a window/process is safe to control.

The next meaningful gate is current-client evidence that independently links a stable Windows generation and TCP flow to a current character identity, followed by exact-build protocol semantic certification. Until then, the existing production readiness block remains correct.
