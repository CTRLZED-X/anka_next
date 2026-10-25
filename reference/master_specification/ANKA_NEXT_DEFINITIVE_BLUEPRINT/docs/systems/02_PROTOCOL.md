# System 02 — Protocol (`anka_protocol`)

## Purpose

Protocol is the anti-corruption layer between volatile Dofus wire dialects and stable ANKA semantic contracts. It is designed for frequent build changes.

## Owned responsibilities

- exact client-build/adapter release selection;
- game-message framing and wire field decoding;
- version-specific dictionary/catalog/obfuscated-name mapping;
- stream-local decoder context/checkpoint/rollback;
- transform wire observations into `CandidateCanonicalBatch`;
- field-level provenance/trust classification;
- unknown/unclassified message inventory;
- capability/scenario certification and upgrade evidence;
- offline replay/differential qualification.

## Adapter package shape

```text
anka_protocol/
  sdk/
  registry/
  certification/
  upgrade/
  adapters/
    dofus_<build>/
      manifest.json / manifest.py
      adapter.py
      wire_catalog.*
      mappings.*
      evidence_manifest.json
      scenario_contract.json
      fixtures/
```

Historical adapters stay immutable except for explicitly versioned corrective releases.

## Public outputs

```text
CandidateCanonicalBatch:
  adapter_release_id
  observed_client_build
  connection_generation
  source WireEnvelope refs
  candidate semantic events
  field provenance/trust
  decode health
  candidate decoder checkpoint
```

No downstream system sees raw opcodes/obfuscated names as API concepts.

## Decoder context transaction rule

Decoder context may be mutable, but a batch rejected by Canonical MUST NOT advance trusted runtime decoding state. Support:

- `checkpoint_runtime_context()`;
- `restore_runtime_context()`;
- safe hydration from compatible durable state when justified.

Context is pinned to adapter + client build + connection generation.

## Unknowns

Unknown traffic is classified by potential impact. Exact evidence-certified opaque payloads may transform to zero Canonical events. A changed fingerprint remains unknown.

Never infer “packet absent” as a certified negative semantic without complete current-build evidence supporting the absence.

## Dependencies

Imports `anka_contracts`; no Capture implementation, LiveState, AI, Execution, Workflow or Client private modules.

## Tests

- exact-build manifest and code/evidence hashes;
- deterministic bytes+context -> same candidates;
- current and historical adapter fixtures;
- malformed/truncated/duplicate/reordered payloads;
- changed one-byte opaque fingerprints;
- decoder crash/context rollback;
- candidate adapter does not become active by merely existing;
- downstream canonical/state semantic golden comparisons;
- previous adapter regression after adding new adapter;
- capability-specific action requirements.

See [Protocol Evolution](../05_PROTOCOL_EVOLUTION.md).

