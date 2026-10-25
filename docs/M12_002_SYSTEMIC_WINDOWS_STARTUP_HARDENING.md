# M12_002 — Systemic Windows startup and single-run diagnostics hardening

## Scope

This release hardens the Q10/Q11 preparation path after the first real Windows `setup.bat` evidence from M12_001. It does **not** enable physical input and does not claim current-client semantic certification.

## Root causes addressed

1. **Setup mixed installation success with live readiness.** M12_001 ran host/live observations during setup, so a successful installation produced a large result dominated by expected live blockers when Dofus was closed. M12_002 makes setup installation/offline-verification only and prints an explicit `ANKA SETUP COMPLETED SUCCESSFULLY` banner.
2. **Technical capture configuration leaked to the operator.** Capture interface/server-port prerequisites were treated as user configuration. M12_002 installs the pinned Scapy dependency during setup and derives bounded candidate capture scope from exact Dofus process generations and Windows TCP ownership.
3. **Capture/identity circular dependency.** Observe-only capture no longer waits for character identity that Protocol/bridge evidence may be needed to establish. Exact executable/process generations constrain the passive sample; the result remains non-actionable until identity is independently proven.
4. **Default-interface ambiguity.** Automatic capture resolves every local game-flow address to one Scapy interface. Multiple/no matching interfaces block instead of silently using an arbitrary default.
5. **IPv6 textual mismatch risk.** Flow endpoints are canonicalized before exact-flow admission so equivalent IPv6 spellings do not create false mismatches.
6. **Npcap probe false negatives.** Required Npcap DLL presence with an unconfirmed service is distinguished from a broken installation; a bounded passive backend attempt may provide stronger evidence. Missing required components still fail closed.
7. **Release tamper/staleness gap.** Setup/start now verify the complete sealed release manifest, while intentionally allowing `config/user.json` to change. Unexpected executable/importable files in protected roots are rejected. Setup prerequisite records are bound to the exact release-manifest hash.
8. **Multi-account bridge masking.** Unity bridge discovery now requires unique exact `(PID, process creation time)` coverage for every observed Dofus generation. Partial coverage, duplicate bridge claims, and projection-not-ready are distinct evidence gaps.
9. **Current build identity missing from one-run evidence.** Client inventory privately reads the executable ProductVersion and exports only the version string. Cross-account version mismatch/partial evidence is explicit; a consistent version is passed to read-only Protocol observation but never certifies semantics.
10. **Generic startup failure diagnosis.** `start.bat` now builds one bounded observe-only evidence package with release, host, capture, bridge, build, protocol and all independently known blockers. The earliest causal blocker controls the stop code, while later blockers remain in the incident snapshot.
11. **Bridge setup ambiguity.** Unknown Dofus process state no longer masquerades as `Dofus running`; build/restore failures preserve only bounded compiler/NuGet diagnostic codes rather than raw command output/paths.

## Preserved safety boundaries

- Physical input remains disabled and uncomposed.
- Title/player name remains a discovery hint, never account identity proof.
- TCP ownership remains a provisional process hint.
- Executable ProductVersion is a build hint, not Protocol certification.
- Historical adapters do not auto-activate for a matching version.
- Raw packet evidence remains explicit opt-in.
- Capture scope drift or process-generation drift invalidates the bounded Protocol observation.
- Client/bridge evidence cannot grant Execution authority.

## Next Windows run

1. Extract the versioned ZIP into a clean directory.
2. Run `setup.bat`. Success must end with the explicit setup-completed banner.
3. Open exactly the configured Dofus clients.
4. Run `start.bat` once. It remains observe-only and may intentionally block; send the generated runtime/incident evidence if any blockers remain.

The purpose of that single `start` run is to expose Q10/Q11 host/current-build evidence in one package rather than consume one live-test cycle per prerequisite.
