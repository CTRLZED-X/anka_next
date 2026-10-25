# System 06 — Decision (`anka_decision`)

## Purpose

Decision turns a frozen, verified gameplay frame into a **semantic proposal**. It decides *what ANKA would like to do*, not whether the action may still be physically sent at this instant.

## Subdomains

- fight/combat planning;
- world route/group selection;
- placement strategy;
- class policies (CRA, ENU initially);
- candidate generation;
- Kernel legality queries;
- threat/score evaluation;
- policy budgets/timeouts;
- abstention/wait reasons;
- semantic ActionKey quarantine.

## Input frame

`DecisionFrame` includes:

- run/client/account/fight/turn identities;
- immutable state snapshot/cursor/fingerprint;
- actor and target facts with proof states;
- available KernelQueries/rulepack ID;
- selected class/policy profile;
- workflow goal/constraints;
- previously quarantined ActionKeys;
- time/compute budget.

## Output

```text
PlannerResult =
  PLAN(ActionPlan)
  WAIT(required_evidence, reason)
  NO_ACTION(reason)
  FAULT(code, evidence)
```

`ActionPlan` contains semantic actions only: `CAST(spell semantic ID, target cell/actor)`, `MOVE(path/cell)`, `END_TURN`, `READY`, etc. It does not contain raw packet names or unverified screen coordinates.

## Anti-loop rule

A semantic `ActionKey` is produced from one stable canonical representation. If Execution/Admission rejects an action as NOT_SENT and the relevant semantic frame has not changed, that ActionKey is quarantined for the turn/frame. Planner must choose another candidate, WAIT for new proof, or request safe turn conclusion. Historical R5.142 makes this mandatory.

## Determinism

Given the same frame, rulepack, policy version and deterministic seed/config, Decision SHOULD produce reproducible output. If deliberate nondeterminism/exploration is added later, its seed/random state is recorded.

## Dependencies

Contracts + injected `KernelQueries`; no Windows, raw Protocol, Execution internals or Workflow concrete classes.

## Tests

- CRA/ENU representative decisions;
- no legal candidate;
- unknown AP/MP/range/cooldown;
- repeated rejected ActionKey;
- decision codec round trip;
- malformed action contract;
- time-budget expiry -> typed result;
- dummy planner substitution proving Workflow/Execution do not depend on FightAI internals;
- same-frame determinism/golden cases.

