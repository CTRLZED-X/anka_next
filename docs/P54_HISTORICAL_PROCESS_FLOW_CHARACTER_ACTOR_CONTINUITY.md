# P54 — Historical process → flow → character → fight actor continuity

Date: 21 October 2026

## Purpose

P53 established a research-only historical chain from a stable Windows process/socket candidate to a Dofus 3.7.10.10 `jnj` character-name witness. P54 closes the next offline boundary by checking that the historical actor ID attached to that character witness is consistent with later P45/P46 fight observations on the **same exact flow, transport generation and historical build**.

This remains a falsification/research capability. It does not certify the current client, CRA/ENU breed or role, spell success, victory, Canonical state, or permission to send input.

## New actor-continuity audit

`anka_protocol.historical_actor_continuity.audit_historical_actor_continuity` joins one `HistoricalIdentityObservation` to one ordered tuple of P45/P46 fight observations.

A clean research continuity result requires:

- exact Dofus 3.7.10.10 historical build;
- exact flow digest match;
- exact transport-generation match;
- one fight identity for all fight observations;
- strictly increasing `(packet_number, message_index)` provenance after the `jnj` identity source;
- at least one meaningful reference to the historical local actor (turn-owner, Ready, cast, or displacement observation).

Foreign actor observations on the same server flow are normal and are counted rather than treated as conflicts. A cast record remains only a wire observation; displacement does not prove cast causation, and `jwp` remains only a fight-result boundary rather than victory evidence.

The audit fails closed for wrong types, mixed builds, mixed flows, changed generations, mixed fight identities, duplicate/reordered source positions, oversized traces and non-historical identity witnesses.

## Full two-account historical composition

`anka_app.ingress_readiness.historical_process_character_actor_topology` composes the existing P51/P53 evidence with P54 actor continuity:

1. stable before/after Windows process/window snapshots;
2. stable before/after TCP endpoint ownership;
3. private selected flow token;
4. exact historical `jnj` character/actor witness for that flow;
5. same-flow P45/P46 fight actor observations.

Each flow is audited independently. P54 **does not** claim a global ordering between CRA and ENU sockets.

The returned report is aggregate/privacy-safe. It does not export character names, PIDs, HWNDs, IP addresses, ports, flow tokens, actor IDs, packet coordinates or fight IDs.

A clean two-candidate synthetic chain reports `HISTORICAL_ACTOR_CANDIDATES_ONLY`, while still forcing:

- `cross_flow_ordering_verified = false`
- `independent_current_character_witnesses = 0`
- `account_binding_verified = false`
- `current_build_certified = false`
- `canonical_commits = 0`
- `actionable = false`
- `physical_input_sent = false`

Swapped actor evidence becomes partial, cross-flow fight evidence blocks, missing fight traces remain partial, and a dirty P53 topology blocks before actor continuity can be promoted.

## Normal preflight

`check` and `setup` now execute a decoder-level P54 smoke that:

- decodes a historical `jnj` character witness;
- decodes P45 turn-owner/end records and a P46 cast record;
- verifies same-flow actor continuity;
- verifies a different actor cannot be misreported as the local historical actor;
- builds two independent process/flow/character/actor candidates and verifies that cross-flow ordering is still unproven.

No Win32 control, network transmission, Canonical state mutation or physical input is performed.

## Verification

For source fingerprint `78539d36aecf73262672ab7940eb27572b1f9364847ed48c18575f1f65686d50`:

- new P54 tests: **24 passed**;
- focused P51–P54/client/protocol regression selection: **221 passed**;
- P45–P54 historical decoder/continuity selection: **112 passed**;
- complete isolated regression inventory: **81 / 81 modules, 1,411 tests passed**;
- `check`: PASS;
- `setup`: PASS;
- architecture boundaries: PASS, 13 packages / 273 Python modules;
- preserved reference assets: 165 / 165 verified;
- `start`: intentionally BLOCKED, exit 40 / `LIVE_RUNTIME_NOT_IMPLEMENTED`;
- generated incident ZIP: integrity PASS.

A single-process whole-suite attempt exceeded the execution limit and is not counted. The release gate is the complete source-bound module-isolated inventory above.

## Remaining gate

P54 strengthens the historical identity chain but does not reduce the central current-client uncertainty. The next meaningful evidence must come from the current client and independently establish character identity/breed plus exact-build protocol semantics on the same stable process/socket generation. Only after that evidence exists should a current identity admission contract or authoritative Canonical state path be considered.
