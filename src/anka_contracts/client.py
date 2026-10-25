"""P3 public read-only client inventory contracts.

A title is a search hint, NEVER an attestation. The observed process generation
must match independent canonical/bridge identity evidence to bind an account.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class WindowObservation:
    hwnd: int
    pid: int
    process_created_100ns: int  # Windows FILETIME, not Unix seconds
    executable_name: str
    title: str
    client_width: int
    client_height: int
    dpi: int | None
    minimized: bool
    # Read-only observation only. ``None`` means the inventory cannot prove it.
    foreground: bool | None = None
    occluded: bool | None = None
    # Numeric ProductVersion observed from the executable file. This is a
    # build hint only; it never certifies Protocol semantics or account identity.
    build_version: str | None = None


@dataclass(frozen=True, slots=True)
class WindowScan:
    observed_monotonic_ns: int
    windows: tuple[WindowObservation, ...]
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CharacterEvidence:
    # Supplied by a separately validated protocol/bridge source, not a title.
    source: str                    # LIVE_PROTOCOL or UNITY_BRIDGE
    character_name: str
    breed: str                     # CRA or ENUTROF currently supported
    hwnd: int
    pid: int
    process_created_100ns: int
    observed_monotonic_ns: int


@dataclass(frozen=True, slots=True)
class AccountBinding:
    name: str
    state: str
    reason: str
    generation_id: str | None = None
    hwnd: int | None = None
    pid: int | None = None
    breed: str | None = None
    evidence_source: str | None = None
    # The new project has neither current-build cert nor live slot binding.
    input_certified: bool = False


class WindowInventory(Protocol):
    def scan(self) -> WindowScan: ...


class CharacterEvidenceProvider(Protocol):
    def snapshot(self) -> tuple[CharacterEvidence, ...]: ...

# --- Definitive M1 identity/projection contracts (additive) ---
from dataclasses import field as _field

@dataclass(frozen=True, slots=True)
class ClientIdentity:
    client_instance_id: str
    account_id: str
    pid: int
    process_created_100ns: int
    hwnd: int
    window_generation: int
    character_match_status: str
    class_id: int | None
    class_proof_status: str
    bridge_generation: int | None
    width: int
    height: int
    dpi: int | None

    def __post_init__(self):
        if not self.client_instance_id.startswith('client-') or not self.account_id.startswith('acct-'):
            raise ValueError('INVALID_CLIENT_IDENTITY')
        if any(type(v) is not int or v <= 0 for v in (self.pid,self.process_created_100ns,self.hwnd,self.window_generation,self.width,self.height)):
            raise ValueError('INVALID_CLIENT_GENERATION')
        if self.character_match_status not in ('PROVEN','AMBIGUOUS','MISSING','CONFLICTING'):
            raise ValueError('INVALID_CHARACTER_MATCH_STATUS')
        if self.class_proof_status not in ('PROVEN','UNKNOWN','STALE','CONFLICTING'):
            raise ValueError('INVALID_CLASS_PROOF_STATUS')
        if self.class_id is not None and (type(self.class_id) is not int or self.class_id <= 0):
            raise ValueError('INVALID_CLASS_ID')
        if self.bridge_generation is not None and (type(self.bridge_generation) is not int or self.bridge_generation < 0):
            raise ValueError('INVALID_BRIDGE_GENERATION')
        if self.dpi is not None and (type(self.dpi) is not int or self.dpi <= 0):
            raise ValueError('INVALID_DPI')

@dataclass(frozen=True, slots=True)
class ProjectionEvidence:
    client_instance_id: str
    window_generation: int
    bridge_generation: int | None
    calibration_generation: int
    target_kind: str
    target_identity: str
    pixel_x: int
    pixel_y: int
    observed_monotonic_ns: int
    valid: bool
    invalidators: tuple[str, ...] = ()
    # Projection coherence is not physical-input authority. Execution must still
    # hold an accepted action scope and revalidate the client immediately before send.
    input_certified: bool = False

    def __post_init__(self):
        if not self.client_instance_id.startswith('client-'):
            raise ValueError('INVALID_PROJECTION_CLIENT')
        for value in (self.window_generation,self.calibration_generation,self.observed_monotonic_ns):
            if type(value) is not int or value < 0: raise ValueError('INVALID_PROJECTION_GENERATION')
        if self.bridge_generation is not None and (type(self.bridge_generation) is not int or self.bridge_generation < 0):
            raise ValueError('INVALID_PROJECTION_BRIDGE')
        if type(self.pixel_x) is not int or type(self.pixel_y) is not int or not self.target_kind or not self.target_identity:
            raise ValueError('INVALID_PROJECTION_TARGET')
        if type(self.valid) is not bool: raise ValueError('INVALID_PROJECTION_VALIDITY')
        if type(self.input_certified) is not bool: raise ValueError('INVALID_PROJECTION_INPUT_CERTIFICATION')
        if self.input_certified: raise ValueError('CLIENT_PROJECTION_CANNOT_CERTIFY_INPUT')
        if self.valid and (self.pixel_x < 0 or self.pixel_y < 0 or self.invalidators): raise ValueError('VALID_PROJECTION_HAS_INVALID_COORDINATES_OR_REASONS')
        if not self.valid and not self.invalidators: raise ValueError('INVALID_PROJECTION_REQUIRES_REASON')


# --- Definitive M3 calibration/loadout/generation evidence ---

@dataclass(frozen=True, slots=True)
class CalibrationProfileEvidence:
    profile_id: str
    profile_sha256: str
    source_sha256: str
    generation: int
    width: int
    height: int
    expected_dpi: int | None
    spell_slots: tuple[tuple[int,int,int], ...]
    controls: tuple[tuple[str,int,int], ...]
    directions: tuple[tuple[str,int,int], ...]
    status: str
    current_client_certified: bool = False

    def __post_init__(self):
        import re as _re
        if not self.profile_id or not _re.fullmatch(r'[0-9a-f]{64}',self.profile_sha256) or not _re.fullmatch(r'[0-9a-f]{64}',self.source_sha256):
            raise ValueError('INVALID_CALIBRATION_IDENTITY')
        if type(self.generation) is not int or self.generation <= 0 or type(self.width) is not int or self.width <= 0 or type(self.height) is not int or self.height <= 0:
            raise ValueError('INVALID_CALIBRATION_GEOMETRY')
        if self.expected_dpi is not None and (type(self.expected_dpi) is not int or self.expected_dpi <= 0):
            raise ValueError('INVALID_CALIBRATION_DPI')
        if type(self.current_client_certified) is not bool:
            raise ValueError('INVALID_CALIBRATION_CERTIFICATION')
        slots=[x[0] for x in self.spell_slots]
        if len(slots)!=len(set(slots)) or any(type(i) is not int or not 1<=i<=22 for i in slots):
            raise ValueError('INVALID_CALIBRATION_SLOTS')
        for _,x,y in self.spell_slots:
            if not (0<=x<self.width and 0<=y<self.height): raise ValueError('CALIBRATION_POINT_OUT_OF_BOUNDS')
        for name,x,y in self.controls+self.directions:
            if not name or not (0<=x<self.width and 0<=y<self.height): raise ValueError('CALIBRATION_POINT_OUT_OF_BOUNDS')

@dataclass(frozen=True, slots=True)
class LoadoutEvidence:
    source: str
    character_name: str
    breed: str
    window_generation_id: str
    generation: int
    observed_monotonic_ns: int
    slot_spells: tuple[tuple[int,int], ...]
    proof_status: str

    def __post_init__(self):
        if self.source not in ('LIVE_PROTOCOL','UNITY_BRIDGE','TEST_FIXTURE') or not self.character_name.strip() or self.breed.strip().upper() not in ('CRA','ENUTROF'):
            raise ValueError('INVALID_LOADOUT_IDENTITY')
        if not self.window_generation_id.startswith('win-'):
            raise ValueError('INVALID_LOADOUT_WINDOW_GENERATION')
        if type(self.generation) is not int or self.generation <= 0 or type(self.observed_monotonic_ns) is not int or self.observed_monotonic_ns < 0:
            raise ValueError('INVALID_LOADOUT_GENERATION')
        if self.proof_status not in ('PROVEN','UNKNOWN','STALE','CONFLICTING'):
            raise ValueError('INVALID_LOADOUT_PROOF_STATUS')
        slots=[x[0] for x in self.slot_spells]; spells=[x[1] for x in self.slot_spells]
        if len(slots)!=len(set(slots)) or any(type(i) is not int or not 1<=i<=22 for i in slots):
            raise ValueError('INVALID_LOADOUT_SLOTS')
        if any(type(i) is not int or i<=0 for i in spells): raise ValueError('INVALID_LOADOUT_SPELL')

@dataclass(frozen=True, slots=True)
class ClientGenerationVector:
    window_generation_id: str
    width: int
    height: int
    dpi: int | None
    foreground: bool | None
    occluded: bool | None
    bridge_map_id: int | None
    bridge_map_generation: int | None
    bridge_coordinate_generation: int | None
    calibration_generation: int
    loadout_generation: int | None

    def __post_init__(self):
        if not self.window_generation_id.startswith('win-') or min(self.width,self.height,self.calibration_generation)<=0:
            raise ValueError('INVALID_CLIENT_GENERATION_VECTOR')
        if self.dpi is not None and (type(self.dpi) is not int or self.dpi<=0): raise ValueError('INVALID_CLIENT_VECTOR_DPI')
        for v in (self.bridge_map_id,self.bridge_map_generation,self.bridge_coordinate_generation,self.loadout_generation):
            if v is not None and (type(v) is not int or v<=0): raise ValueError('INVALID_CLIENT_VECTOR_GENERATION')

@dataclass(frozen=True, slots=True)
class ClientContextProof:
    character_name: str
    breed: str | None
    class_id: int | None
    vector: ClientGenerationVector
    prerequisites_status: str
    invalidators: tuple[str, ...]
    # Client can prove prerequisites; it can never grant physical-input authority.
    physical_input_permitted: bool = False

    def __post_init__(self):
        if not self.character_name.strip(): raise ValueError('INVALID_CLIENT_CONTEXT_CHARACTER')
        if self.prerequisites_status not in ('PROVEN','INCOMPLETE','BLOCKED'): raise ValueError('INVALID_CLIENT_CONTEXT_STATUS')
        if self.prerequisites_status=='PROVEN' and self.invalidators: raise ValueError('PROVEN_CLIENT_CONTEXT_HAS_INVALIDATORS')
        if self.prerequisites_status!='PROVEN' and not self.invalidators: raise ValueError('UNPROVEN_CLIENT_CONTEXT_REQUIRES_REASON')
        if self.physical_input_permitted: raise ValueError('CLIENT_SYSTEM_CANNOT_GRANT_PHYSICAL_INPUT')
