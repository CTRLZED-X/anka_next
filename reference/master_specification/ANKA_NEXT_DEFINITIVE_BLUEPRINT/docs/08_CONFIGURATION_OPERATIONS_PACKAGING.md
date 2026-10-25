# 08 — Configuration, Operations & Packaging

## 1. Operator surface

Normal operator interaction is intentionally minimal:

- `setup.bat`
- `config/user.json`
- `start.bat`

No dashboard. No Script Studio. No extra BAT launchers.

---

## 2. `setup.bat`

Purpose: make the exact extracted release runnable and verifiable on the target Windows machine.

Responsibilities:

1. start bootstrap diagnostic envelope immediately;
2. verify supported Windows/Python architecture;
3. create/repair isolated Python environment as designed;
4. install **locked** dependencies from approved sources/cache;
5. verify file/resource hashes and package data;
6. install/build optional native Unity bridge prerequisites as required;
7. validate internal assets/manifests/config schema;
8. run bounded offline foundation self-checks;
9. write setup receipt and terminal result.

It MUST NOT silently start autonomous gameplay.

### Failure examples

Distinguish Python missing, dependency DNS, wheel/hash mismatch, permissions, disk space, native bridge build/install, corrupt asset, unsupported OS/Python, config schema corruption.

---

## 3. `start.bat`

Responsibilities:

1. create bootstrap/run invocation;
2. verify installed release/source/assets hashes;
3. load strict user JSON + internal defaults;
4. detect/reconcile previous unclean run/action ambiguity;
5. discover Dofus clients;
6. attest configured players/classes/windows/flows;
7. identify client build and compatible Protocol adapter;
8. validate calibration/projection/bridge as required;
9. verify Canonical store integrity;
10. initialize systems and runtime diagnostics;
11. remain disarmed until readiness requirements are met;
12. start workflow/headless terminal;
13. perform safe shutdown on Ctrl+C/failure.

---

## 4. User JSON

Recommended schema concepts:

```json
{
  "schema_version": 1,
  "players": [
    {"name": "Curseni", "role": "leader"},
    {"name": "Sosoking", "role": "follower"}
  ],
  "mission": {
    "route_id": "sufokia_direction_cycle",
    "min_monsters": 6,
    "max_monsters": 8,
    "target_wins": 5,
    "max_attempts": 10
  }
}
```

Optional future operator fields may be added only if they represent real operator intent, not internal technical details.

Do not ask the user to manually maintain protocol opcodes, spell pixel coordinates, capture filters, queue sizes, debug levels, Kernel rules or calibration internals in this file.

---

## 5. Internal release assets

```text
assets/
  game_data/
    manifest.json
    static/
    maps/
    kernel_rules/
  class_profiles/
    cra.json
    enu.json
  calibration/
    1280x649_reference.json
    manifest.json
  protocol/
    adapter certification manifests / bounded fixtures
```

Each asset has schema/version/hash/provenance. Technical assets can evolve independently from operator config.

---

## 6. Automatic account/class/window detection

Algorithmic outline:

1. enumerate candidate Dofus processes/windows;
2. create `ClientInstanceId` from PID + creation generation + executable identity;
3. gather live character/account/class evidence from supported authoritative source(s);
4. correlate capture connection/flow to process/client;
5. correlate configured player name to observed identity;
6. attach bridge/projection/calibration generation;
7. validate selected class profile/loadout requirements;
8. publish binding proof;
9. revalidate before physical send.

Title string may be a discovery hint but is never sole authority.

---

## 7. Calibration

R5.198's 1280×649 22-slot/phase/join coordinates are imported as a historical calibrated baseline.

Target behavior:

- load immutable profile matched by validated client geometry;
- verify size/DPI/viewport/bridge map generation;
- validate point bounds;
- distinguish semantic `PHASE_BUTTON` from current phase (Ready vs End Turn is state-dependent);
- recheck before input;
- invalidate on display/client changes.

If no compatible profile exists, input is blocked and the app exposes a controlled calibration workflow through internal CLI/application functionality—not a dashboard or extra BAT file.

---

## 8. Spell loadout/class profiles

Class profiles specify semantic preferred spells/grades/policy settings, not hard-coded assumptions that a slot always contains a particular spell.

A cast requires enough current proof to map semantic spell -> current usable slot/interaction. If a certified fallback profile is allowed for a specific compatible build/config, that compatibility must be explicit.

---

## 9. Dependency management

- Pin Python version range and lock exact dependency versions/hashes for a release.
- Avoid unnecessary changes during unrelated bug fixes.
- UI-only dependencies from old project should be removed if not required by internal technical endpoints.
- Native bridge dependencies/version are part of release manifest.
- Setup verifies installed package/source coherence.
- Reproducible clean extraction is a release gate.

---

## 10. Packaging

A release ZIP contains:

```text
src/
assets/
native/
config/user.example.json
config/schema/
tests/ or verification subset as policy allows
tools/ developer Python utilities
docs/ concise operator/technical docs
setup.bat
start.bat
pyproject/lock manifests
RELEASE_MANIFEST.json
```

Runtime outputs are **not** baked into the release ZIP.

### Release manifest

Record:

- release ID/source hash;
- Python/dependencies;
- Kernel rulepack/game-data hashes;
- Protocol adapter releases;
- calibration/class profile versions;
- config schema;
- contract schemas;
- verification receipts;
- known unsupported/live-pending items.

---

## 11. Terminal behavior

Keep normal output concise. Example:

```text
ANKA release: ...
Config: VALID
Players: CRA=Curseni [VERIFIED], ENU=Sosoking [VERIFIED]
Protocol: build ... / adapter ... [ACTION_SCOPE_ACCEPTED]
Calibration: ... [READY]
State: HEALTHY
Control: DISARMED -> ARMED
Mission: WORLD / wins 2 of 5
```

Detailed evidence belongs in structured runtime files.

---

## 12. Startup must not kill unknown processes

The old R5.197 control-plane issue teaches a general rule: process takeover/cleanup requires positive ownership/generation evidence. ANKA_NEXT has no browser control plane, but the same rule applies to stale run locks/native helpers/capture/bridge processes.

Never `taskkill` an arbitrary PID merely because a port/path looks familiar.

---

## 13. Runtime directory

```text
runtime/
  bootstrap/<invocation>/
  runs/<run_id>/
    run_manifest.json
    canonical/
    action_ledger/
    diagnostics/
    incidents/
    temporary/
```

Separate authoritative durable stores from observational logs. Cleanup/retention must never delete unresolved action/canonical data needed for recovery without explicit safe archival policy.

