"""Definitive M1 typed identity primitives.

These wrappers prevent user-visible labels, PIDs, HWNDs or actor IDs from being
accidentally reused as cross-system identity.  Values are opaque tokens/generations;
the owning system decides how they are minted.
"""
from __future__ import annotations

import re

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,126}$")


class _OpaqueId(str):
    prefix = ""

    def __new__(cls, value: str):
        if type(value) is not str or not _TOKEN.fullmatch(value):
            raise ValueError(f"INVALID_{cls.__name__.upper()}")
        if cls.prefix and not value.startswith(cls.prefix):
            raise ValueError(f"INVALID_{cls.__name__.upper()}_PREFIX")
        return str.__new__(cls, value)


class InvocationId(_OpaqueId): prefix = "inv-"
class RunId(_OpaqueId): prefix = "run-"
class PartyId(_OpaqueId): prefix = "party-"
class AccountId(_OpaqueId): prefix = "acct-"
class ClientInstanceId(_OpaqueId): prefix = "client-"
class ConnectionId(_OpaqueId): prefix = "conn-"
class SnapshotId(_OpaqueId): prefix = "snap-"
class PlanId(_OpaqueId): prefix = "plan-"
class ActionId(_OpaqueId): prefix = "action-"
class AttemptId(_OpaqueId): prefix = "attempt-"
class AdapterReleaseId(_OpaqueId): prefix = "adapter-"
class IncidentId(_OpaqueId): prefix = "incident-"
class EvidenceId(_OpaqueId): prefix = "evidence-"


class ActionKey(str):
    """Canonical semantic fingerprint shared by Decision and Execution."""
    def __new__(cls, value: str):
        if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("INVALID_ACTION_KEY")
        return str.__new__(cls, value)


class _Epoch(int):
    def __new__(cls, value: int):
        if type(value) is not int or not 0 <= value < 2**63:
            raise ValueError(f"INVALID_{cls.__name__.upper()}")
        return int.__new__(cls, value)


class WindowGeneration(_Epoch): pass
class WorldEpoch(_Epoch): pass
class FightEpoch(_Epoch): pass
class TurnEpoch(_Epoch): pass
class CanonicalCursor(_Epoch): pass
class InputLeaseEpoch(_Epoch): pass
class CalibrationGeneration(_Epoch): pass
