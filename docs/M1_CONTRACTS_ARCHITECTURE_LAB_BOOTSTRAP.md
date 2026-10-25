# M1 — Contracts, Architecture Gates, Verification Lab & Bootstrap Diagnostics

## Scope

M1 creates the stable shared language and falsification tools required before migrating or expanding business systems. It is intentionally offline and zero-input. It does **not** promote any historical protocol adapter, calibration, window binding, or physical action to current-client authority.

## Implemented

- Definitive identity, independent-version, evidence, wire, Canonical-envelope, state-proof, mechanics, planning, action/attempt/outcome, coordination, workflow, client/projection, structured-error and verification-receipt contracts.
- Dependency-inversion ports for Wire, Canonical admission/read, State, Kernel, Decision, Execution, Coordination, Client projection, diagnostics and control commands.
- Architecture guard with reviewed package graph, Tarjan SCC detection, dynamic-import bypass checks, domain-to-app prohibition, explicit authority-owner inventory and obvious physical-input primitive checks.
- Verification Lab fakes for State, Kernel, Client and Execution, plus virtual monotonic time, deterministic fault injection and a counting input fake.
- A complete M1 zero-input contract walk that crosses State -> Kernel -> Client -> Execution while making zero physical-input calls.
- Existing pre-Python BAT bootstrap evidence and stdlib-only bootstrap incident exporter retained and contract-tested.
- Structured diagnostic envelopes and bounded, checksummed, sanitized fake incident bundles verified.
- Machine-readable Q1/Q2 receipt schema containing source/config/dependency/Kernel/data/calibration/fixture hashes, environment, test/gate counts, physical-input state and explicit limitations.

## Deliberate compatibility choices

Existing P1-P66 DTOs are retained where deleting them would cause unnecessary regression risk. Definitive M1 contracts are additive. Consumers migrate behind ports in their owning milestones; old and new mutable authorities are never run concurrently.

Decision's direct imports of the preserved Game Kernel remain an explicitly documented transitional edge allowed by the master specification. The `KernelQueries` port now exists so the concrete dependency can be removed during the appropriate Kernel/Decision cutover rather than via an unverified bulk rewrite.

## Q1 — Architecture acceptance

Q1 requires the real source graph to be violation-free, have no top-level SCC cycles, have no unreviewed dynamic-import sites, preserve explicit unique authority ownership, and pass mutation tests proving forbidden imports/cycles/dynamic bypasses/input-authority bypasses are detected.

## Q2 — Contract acceptance

Q2 requires contract invalid/negative cases, diagnostic round-trip, verification-receipt round-trip, deterministic fakes/fault hooks, zero-input fake-stack execution, bootstrap evidence paths and sanitized incident ZIP integrity to pass.

## Known limitations

- Actual `cmd.exe` missing-Python startup behavior is not executable on this non-Windows verification host; the branch is statically checked now and remains a Q10 Windows acceptance item.
- M1 does not assert current Dofus build identity, protocol semantics, window/account/class identity, current calibration or physical-input readiness.
- Current-build and live-action evidence remains `BLOCKED_MISSING_EVIDENCE`.

## Rollback / cutover

M1 adds definitions, ports, lab infrastructure and guards. It does not replace a live mutable authority. If an M1 contract proves incorrect during a later owner-system milestone, change it with an explicit compatibility impact and regenerate affected receipts; do not silently reinterpret an existing field.
