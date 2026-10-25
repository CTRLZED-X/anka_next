# P35 — Causal source-window reconciliation for spell and movement observations

**Scope: offline RESEARCH ONLY. No Canonical commits, current-build certification, physical input, or server-outcome verification.**

## Problem addressed
P34 correctly recorded spell-cast and actor-position research observations as **unapplied**. It did not connect a particular cast to explicitly identified before/after AP, MP, HP, cooldown, or position observations. Without exact-source linking, an engineer could incorrectly attribute a later resource difference to the nearest spell or silently reuse one resource snapshot to "confirm" multiple spells.

## Implemented boundary
- `src/anka_contracts/effect_reconciliation.py` owns immutable `ObservationWindow`, `ObservationComparison`, and `EffectReconciliationReport` contracts. A window identifies **three explicit zero-based research event indices**: before, cast, after, plus one resource/position metric. Output has no operator authority fields.
- `src/anka_app/effect_reconciliation_offline.py` uses the existing P34 full-trace provenance/turn/roster and P33 shadow-state rules before comparing any values. The composition owns no protocol adapter, state writer, input driver or reusable Game Kernel implementation.
- An observation window must have **strictly increasing source coordinates** (packet number, message index), the same actor, the correct fact types, a valid cast inside the observed turn, and a post-snapshot before any Turn End/Fight End event.
- Multiple casts within a before/after window make the comparison `AMBIGUOUS`, not evidence of spell success. A post snapshot reused to support different casts with the same metric is blocked. AP/MP and HP differences are measurements, **not verified expenditures, damage or server acceptance**.
- Snapshot types: AP, MP, RANGE, HP (value and max HP), CELL (position snapshots), COOLDOWN. Any changed cell has an explicit unknown-path/unknown-MP caveat. COOLDOWN differences never prove cast-limit compliance.
- `setup` automatically runs one short positive/negative contract smoke. There are no new operator BAT scripts and no dashboard. `start` remains intentionally blocked for live gameplay.

## Limits deliberately preserved
- The before and after values are synthetic or historical **research candidates**, not authoritative live state. No cross-account server event order or independent spell outcome is proven.
- Same-flow source position does not prove server causality. The source of an HP/AP/MP change may be an unrelated effect, including effects not represented by the protocol research catalog.
- This does **not** implement missing wire fields, post-cast server settlement, actual movement path, pushes/pulls, damage, healing, victory, current fight map walkability, or the real physical Windows execution driver.
- No algorithm may promote these reports into action authority. Diagnostics export only reason codes, relation labels, counts, and metric names; they omit actual values, account names, packet content, identifiers, and numeric deltas.

## Example
Synthetic trace: `Fight Start → AP=11 → CRA Turn Start → Cast Observed → AP=8 → CRA Turn End → Fight End`.

A `ObservationWindow(before=1, action=3, after=4, metric=AP)` reports **CHANGED**, a privately computed delta of -3, and the caveat `P35_NO_INDEPENDENT_SERVER_CAUSAL_PROOF`. It does **not** report CAST CONFIRMED, AP CONSUMPTION PROVEN, or any executable plan. A second cast inside the observation interval returns `AMBIGUOUS`.

## Acceptance
- New adversarial contract tests cover source identity, altered generation, wrong fight/actor, cast outside turn, before/after ordering, wrong fact kind, duplicate snapshot reuse, ambiguous intervening casts, cooldown/HP/cell handling, report privacy, and forbidden authority flags.
- P34 shadow projection continues to reject spell-cast projection, unchanged. P35 only compares independently identified research snapshots.
- Current-build Windows acceptance and full autonomous CRA/ENU fight acceptance remain pending.

**Roadmap development estimate: ~86% (scope coverage, not quality/reliability). Complete live CRA/ENU fight acceptance: 0%.**
