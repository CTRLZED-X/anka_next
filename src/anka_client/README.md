# Client System — P3 read-only inventory seed

`api.py` exposes a read-only inspection facade; `discovery.py` owns deterministic
matching; `win32_inventory.py` owns `EnumWindows`/process/geometry information.
Their contract DTOs live in `anka_contracts.client`. No file may move, focus,
restore, click, or type in the client.

The name in `config/user.json` is used only as a window-title *hint*. The process
image must match the trusted Dofus allowlist; the exact HWND/PID/process-creation
generation is fingerprinted. A `CharacterEvidenceProvider` capable of returning
independently verified identity and breed from current-build live protocol/bridge
sources does **not** exist in this release. Consequently all real discoveries
stay `PENDING` or `BLOCKED`, never certified for physical input.

`IDENTITY_MATCHED` in injected offline tests proves the matching policy, not
live game authorization. Physical input additionally requires later viewport,
DPI, calibration, spell-slot, protocol and action-authority gates. Inventory
errors conservatively prevent identity binding. `clients.bat` is diagnostic only.

Windows client inspection is not tested on Windows in this build; ctypes
implementation remains subject to real host smoke tests.
