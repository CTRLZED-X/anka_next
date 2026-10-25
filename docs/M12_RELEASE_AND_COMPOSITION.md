# M12 — Composition, observability and offline release hardening

`anka_app.composition.AnkaCompositionRoot` is the definitive construction facade. Historical P-series app modules remain regression/research fixtures; they are not alternate production authorities. The live builder is deliberately blocked until current Windows/client gates Q10–Q12 are accepted. The source presence of a Windows driver cannot arm it.

Normal operator surface is `setup.bat`, `config/user.json`, and `start.bat`. `config/user.json` and `config/user.example.json` contain player/mission intent only. The only top-level BAT launchers are `setup.bat` and `start.bat`; `tools/windows/_entry.bat` is an internal bootstrap helper.

`RELEASE_MANIFEST.json` is generated from all shipped files (excluding runtime/local caches), records exact SHA-256 and size for each file, binds available Q0–Q9 receipts, and explicitly records Q10–Q13 as unaccepted where evidence is missing. `tools/build_release.py` creates a deterministic ZIP. `tools/verify_release_offline.py` verifies the exact extracted payload, gate receipts, architecture, operator surface, and fail-closed configuration without OS input.

M12/Q9 remains an offline acceptance tier. Current Windows setup/start, current Dofus protocol observation, action scopes, and full live mission acceptance remain later evidence gates and may not be inferred from this release package.
