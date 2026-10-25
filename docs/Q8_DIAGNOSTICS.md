# Q8 — Definitive Diagnostics and First-Divergence Forensics

## Status

Q8 is an **offline diagnostics verification gate**. It does not authorize live
observation or physical input.

## Purpose

The old failure cycle often started from a user-visible symptom (for example,
"both accounts look Ready") and worked backward with incomplete evidence. Q8
changes the diagnostic question to: **which expected causal boundary is the
first one not supported by evidence?**

Observability remains passive. It may lose or fail to export diagnostics without
creating, revoking, or repairing Canonical truth, Coordination permits, Workflow
progress, or Execution authority.

## Implemented behavior

- Explicit `OperationTraceSpec` / `BoundaryExpectation` contracts describe the
  expected causal chain for an operation.
- `FirstDivergenceAnalyzer` walks only recorded diagnostic evidence and reports
  the earliest missing edge.
- A finding carries the first divergent boundary, suspected owner, confidence,
  supporting evidence IDs, missing evidence, candidate failure codes and one
  targeted next verification.
- Multiple plausible causes remain multiple; no root cause is invented.
- Evidence completeness is derived per system/section and supports
  `PRESENT`, `PRESENT_STALE`, `PARTIAL`, `MISSING`, `NOT_APPLICABLE` and
  `EXPORT_FAILED`.
- Incident bundles now include a definitive GPT-friendly hierarchy while keeping
  the original four P1 paths for backward compatibility.
- The bundle states the latest **recorded** physical-input state, or `UNKNOWN`;
  it never infers a click from UI appearance.
- Export failure attempts one bounded local fallback and marks Observability
  `EXPORT_FAILED`; the original failure is preserved.
- Raw packet captures, environment dumps and credentials remain excluded by
  default. ZIP traversal, undeclared files, size abuse and checksum corruption
  are rejected by the verifier.

## Required causal example: Ready

```text
READY_REQUESTED
 -> EXECUTION_ADMITTED
 -> READY_INPUT_SENT/MAY_HAVE_SENT
 -> SERVER_READY_OBSERVED
 -> PARTY_READY_BARRIER_SATISFIED
 -> TURN_OWNER_PROVED
 -> DECISION_FRAME_CREATED
```

If the first three edges exist but `SERVER_READY_OBSERVED` does not, Q8 reports
`protocol.ready_observation` as the first divergence. It does **not** report the
later symptom "Ready stuck" as the root boundary.

## Deliberate fault coverage

The Q8 regression set includes:

- Ready input recorded but authoritative server Ready evidence absent;
- Canonical admission followed by commit-ack uncertainty;
- `MAY_HAVE_SENT` followed by missing authoritative action outcome;
- multiple plausible failures without evidence for a unique root cause;
- bounded observer storage loss;
- primary incident-export failure with marked fallback;
- nested credential/path/email redaction;
- checksum corruption and ZIP traversal;
- pre-dependency bootstrap failure bundle.

## Acceptance boundary

Q8 proves that **offline diagnostic evidence is causally organized and honest
about gaps**. It does not prove that every current-client boundary emits the
necessary events in a real Windows run. That is exercised progressively by Q9
and later Q10–Q13 acceptance.
