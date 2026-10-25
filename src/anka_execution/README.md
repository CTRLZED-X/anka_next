# anka_execution

Sole physical-input and action-settlement authority.

Definitive M11 components:

- `service.py` — latest-truth admission, double revalidation and ActionExecutor API;
- `arbiter.py` — one host-wide external-input lease;
- `definitive_ledger.py` — durable prepared/send/settlement ledger and restart fencing;
- `outcomes.py` — action-specific authoritative evidence correlation;
- `drivers/fake_input.py` — Q7/Q9 zero-OS-input driver;
- `drivers/windows_input.py` — explicit action-scope-gated Windows pointer driver, disabled unless separately accepted;
- P18/P19 fixture modules remain as historical regression evidence.

No other ANKA system may call physical input primitives.
