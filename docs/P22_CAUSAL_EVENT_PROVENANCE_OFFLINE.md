# P22 — Causal journal-to-coordination source evidence (offline)

## Engineering problem and root cause

P20 compared one atomically audited *set of final per-account snapshots* to
an independently constructed party timeline. That proved consistency of some
values, but did not prove that `TURN_STARTED`, `TURN_ENDED`, or fight-start
claims were supported by exactly the journal events the app actually replayed.
A fabricated or stale coordination observation could therefore pass a final
snapshot comparison. Previous CRA/ENU handoff failures make this a high-priority
boundary to test before building an authoritative runtime.

## New safety boundary

- New immutable `anka_contracts.causal_evidence.PartySourceLink` records the
  originating journal **session and event ID** for each party observation.
- The composition-layer auditor in `anka_app.source_link_audit` receives a
  **single-transaction** `SQLiteFixtureJournal.audited_evidence` result. It
  verifies every turn start/end and both participants' fight-start events.
- Each link must match original event type, fight ID, source account, account
  generation, actor and session. Journal source event reuse, unknown IDs,
  dropped events and extra links are rejected with precise P22 failure codes.
- The audit executes **after** P17 state-machine and state-scope checks and
  **before** any Decision research or fake-only Execution.
- Reports cannot be modified to claim authority, actionability or global
  event ordering. No projection, physical execution or protocol adapter was
  enabled or modified.

## Explicit remaining uncertainty

The journal is populated by synthetic fixtures, not server-confirmed real
protocol events. Even if both account-local event chains are correct, a single
SQLite read transaction **does not prove the relative time ordering of events
observed on different clients**. Cross-account server order requires a shared
certified fight/turn epoch or another independent ordering source.

The P22 audit does **not** certify live behavior, network evidence quality,
current-client decoding, or mouse input. It only prevents a proven category of
synthetic coordination-to-journal misattribution before downstream consumers.

## Permanent adversarial regression coverage

Three full-stack simulated incidents were added: `source-missing`,
`source-reused`, and `source-orphan`. An independent set of provenance tests
also checks incorrect actor, generation, fight ID, event kind, fight-start
coverage, unsupported links, and authority flag forgery. All failures stop
before the fake driver. The pre-existing P20/P21 examples and tests remain.

## Operating surface

The only Windows root launchers remain `setup.bat` and `start.bat`. Setup
continues to run the short two-case synthetic smoke, and developers can run
the complete historical fault matrix as automated tests. No new BAT, UI,
dashboard, or operator parameter has been introduced.

## Acceptance criteria and next milestones

P22 passes only if (a) the complete inherited suite remains green, (b) new
source-link mutation cases fail correctly, (c) all baseline assets remain
intact, (d) only two Windows launchers remain and (e) current-client input
remains blocked. A follow-on milestone needs real current-build semantic
fixtures with independently verified provenance and matching fight/turn
identifiers; it must not "promote" these synthetic links.
