# System 11 — Observability (`anka_observability`)

## Purpose

Observability reconstructs **what happened and where expected progress first diverged**. It provides local evidence for operators, tests and GPT-assisted debugging without becoming a gameplay authority.

## Responsibilities

- structured typed event ingestion;
- run/trace/action correlation;
- bounded flight recorder;
- passive health/lag/drop metrics;
- startup/setup/run incident triggers;
- evidence-gap detection;
- first-divergence and plausible-cause analysis;
- deterministic incident bundle assembly;
- sanitization/privacy/retention;
- offline bundle validation and replay assistance.

## Bootstrap split

`anka_app/bootstrap` contains a stdlib/Batch-compatible minimal recorder for failures before normal packages load. Once Observability initializes, it adopts the invocation/run context.

## Diagnostic event contract

Events SHOULD contain where applicable:

```text
schema_version, event_id, event_name, severity
wall_time, monotonic_time, producer_sequence
invocation_id, run_id, account/client generation
fight_epoch, turn_epoch, canonical_cursor
trace_id/span_id/parent_event_id
action_id/attempt_id
owner_system, boundary, failure_code
physical_input_state
payload (bounded/typed)
evidence_refs
```

## Incident result

A diagnostic finding contains supporting evidence, contradicting evidence, missing evidence, confidence and owner/boundary. It is not permitted to convert a heuristic match into a verified root cause.

## GPT-friendly bundle

Default share bundle includes:

```text
GPT_READ_FIRST.md
manifest.json
run_manifest.json
diagnosis.json
timeline.jsonl
evidence_gaps.json
relevant_errors.jsonl
state/action/canonical references
version/config/adapter/rulepack metadata
checksums
```

Raw PCAP/screenshots/memory dumps are excluded unless deliberately requested.

## Performance/isolation

- bounded queue;
- priority evidence channel;
- low-priority event loss produces explicit counters;
- exporter runs outside critical input/commit path;
- observer failure cannot authorize/deny clicks;
- authoritative Canonical/action ledgers remain owned by their systems.

## Tests

- failure before Python import;
- dependency/setup failure;
- startup ownership/identity failure;
- protocol unknown after settled action;
- Ready/turn stall;
- focus/pre-input rejection;
- `SENT_UNCONFIRMED` action;
- disk full/permissions/queue overflow;
- exporter crash/partial ZIP;
- privacy/redaction/path traversal;
- multiple plausible root causes -> honest uncertainty;
- bundle checksum/schema verifier.

