# P10 — Repeatable protocol adapter qualification (historical, synthetic)

**Scope:** offline contract qualification, independent of live packets, current-client certification, Canonical authority and physical execution.

## Why P10 exists

The project expects an external protocol that can change roughly every two weeks. Simply compiling or importing a replacement adapter is insufficient: the adapter might decode the same wire shape to a different AP, ignore a new branch, infer missing character context, or accidentally authorize invalid state. Historically, these classes of drift caused repeated live-test/debug cycles.

P10 implements a small **executable adapter-consumer contract** using version-local fixtures, exact expected semantic facts, negative cases, explicit build identity and traceable SHA-256s. Only the version-specific adapter should change for wire-only updates. Shared Canonical and game mechanics contracts do not depend on wire names.

## What changed

| File | Purpose |
|---|---|
| `src/anka_protocol/qualification.py` | Bounded strict fixture loader, independent golden comparison, typed run report |
| `qualification/historical_3_7_10_10_synthetic.json` | 14 independently specified **synthetic** wire/expectation cases |
| `src/anka_app/protocol_qualification.py` | Composition root wiring historical adapter to qualification fixture |
| `protocol_qualify.bat` | Windows entry point (`protocol-qualify`) |
| `tests/test_p10_protocol_qualification.py` | Mutation, corruption, mismatch, isolation and staging tests |

There are no new dependencies. The reused Kernel is unchanged.

## Run it

```bat
protocol_qualify.bat
protocol_qualify.bat "Dofus 3.7.11.11"
verify.bat
```

On a supported Python installation, equivalent commands:

```text
python -m anka_app.cli protocol-qualify
python -m anka_app.cli protocol-qualify "Dofus 3.7.11.11"
```

With the **historical** target build, expect `SYNTHETIC_CONTRACT_PASS_LIVE_BLOCKED`. With an unrecognized newer build, expect `QUALIFICATION_FAILED_LIVE_BLOCKED` plus `REQUESTED_BUILD_UNSUPPORTED`. The latter is a report, not a new-build certification and cannot enable live execution.

Each report includes case ID, scenario, pass/fail, failure codes, candidate count, exact build, adapter hash, fixture hash and remaining gates. It never includes packet bodies or private endpoints. Observability records `protocol.synthetic_qualification_completed` with reason context. In both cases, Canonical commits and physical inputs are always **zero**.

## Scope of the golden suite

Positive scenarios:

- AP and MP in the same characteristic message; exact resource values, not just parse success
- Historical AP bookkeeping field must **not** be double-counted
- Cooldown snapshot with exact spell and remaining turns
- HP only if verified synthetic actor context is explicitly supplied
- Repeated wire messages retain separate message coordinates

Negative scenarios:

- HP without identity context
- Truncated or malformed wire body
- Client-to-server direction for a server-only observation
- Unknown message name
- Different protocol build
- Changed characteristic composition branch
- Duplicate cooldown rows
- HP exceeding max HP

These scenarios intentionally validate *the research adapter's known historical behavior*. They **do not** establish that this behavior matches any actual client build today.

## Two-week protocol change workflow (target)

1. Retain the previous adapter and fixture manifest unchanged; record the exact old build, new build, and SHA-256s.
2. Independently collect an authorized, bounded new-client evidence set including message order, account and process generation, full relevant state, and event outcomes. Sanitize externally shared evidence.
3. Implement a **new named adapter** for the new exact build, never by relabeling the old adapter. Build-mismatch failure must be explicit.
4. Write version-local golden expectations using independently checked evidence, including negative drift examples. Do not generate the expected values by asking the new decoder what it produced.
5. Pass structural tests, adapter negative tests, source-to-Canonical consumer replay, state reconciliation, multi-account boundary tests and crash/reconnect/fault injection.
6. Verify account, process and window identity separately, then complete Windows host acceptance and a controlled observation run. Preserve unsupported scenarios and don't silently assume zero loss.
7. Activate the new adapter **only at a safe session boundary** after all required capability-specific gates. Keep the old adapter/rollback recipe; never cross-apply old-build game state to a new-build session.
8. Turn every real drift/failure into a permanent regression fixture; record causes and capabilities affected.

### The qualification levels are separate

| Gate | Meaning | P10 result |
|---|---|---|
| Q0 | Fixture schema, exact build, bounded input | PASS for packaged historical fixture |
| Q1 | Synthetic adapter-consumer behavior | PASS for 14 historical synthetic cases |
| Q2 | Current-build independent capture, identity, schema semantics | **NOT TESTED / NO EVIDENCE** |
| Q3 | Full Canonical+Live State consumer replay and fault isolation | **NOT CERTIFIED** |
| Q4 | Windows/actual-client controlled acceptance | **NOT TESTED** |
| Q5 | Enabled fight automation and safe recovery | **BLOCKED BY DESIGN** |

These are explicit **evidence thresholds**, not just flags in JSON. A `.json` file claiming `certified=true` cannot grant authority.

## Failure diagnostics and falsification

The regression suite deliberately alters golden AP, message direction, version labels, schema, mandatory scenario set, and the decoder implementation. These mutations must cause a failed qualification. Crashing adapters must be reported as failures, never ignored. Historical candidates must still be refused by the authoritative Canonical admission path even when test context claims identity and transport are good.

The synthetic fixture is useful for testing *code contracts*, not for proving real-world accuracy. For a real upgrade, a separately reviewed independent evidence corpus and Windows tests are non-negotiable.

## Outstanding limitations

- Only the R5.198 **historical 3.7.10.10** semantic slice exists: `jtk`, `jti`, `kqo`; this is far from complete gameplay decoding.
- No current-build raw captures or independently validated current-build oracle is packaged.
- No live account identity or Npcap Windows acceptance; capture completeness remains unproven.
- No current-build authoritative event admission, turn/movement/spell reconstruction or live action confirmation.
- Runtime still explicitly refuses `start` to protect safety boundaries.

**P10 is complete only for its offline, synthetic adapter qualification scope.**
