from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any


_EFFECT_CONTAINER_NAMES = frozenset(
    {
        "effects",
        "effect",
        "normaleffects",
        "normaleffect",
        "criticaleffects",
        "criticaleffect",
    }
)
_EFFECT_IDENTITY_NAMES = frozenset(
    {
        "effectid",
        "baseeffectid",
        "effectuid",
    }
)
_VALUE_ARGUMENT_NAMES = frozenset(
    {
        "dicenum",
        "diceside",
        "value",
        "minimumvalue",
        "maximumvalue",
        "min",
        "max",
    }
)
_DURATION_DELAY_NAMES = frozenset({"duration", "delay"})
_TARGET_ENCODING_NAMES = frozenset({"targetmask", "targets", "target"})
_ZONE_ENCODING_NAMES = frozenset({"rawzone", "zonedescr", "zone"})
_TRIGGER_ENCODING_NAMES = frozenset({"triggers", "trigger"})
_CRITICAL_BRANCH_NAMES = frozenset({"criticaleffects", "criticaleffect"})


@dataclass(frozen=True, slots=True, order=True)
class SourceFieldEvidence:
    path: str
    value_types: tuple[str, ...]
    occurrences: int


@dataclass(frozen=True, slots=True)
class EffectSourceAuditReport:
    source_file: str
    source_hash: str
    top_level_kind: str
    record_count: int
    fields: tuple[SourceFieldEvidence, ...]
    has_effect_container: bool
    has_effect_identity: bool
    has_value_arguments: bool
    has_duration_or_delay: bool
    has_target_encoding: bool
    has_zone_encoding: bool
    has_trigger_encoding: bool
    has_critical_branch: bool
    candidate_effect_instance_graph: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "source_file": self.source_file,
            "source_hash": self.source_hash,
            "top_level_kind": self.top_level_kind,
            "record_count": self.record_count,
            "fields": [
                {
                    "path": field.path,
                    "value_types": list(field.value_types),
                    "occurrences": field.occurrences,
                }
                for field in self.fields
            ],
            "has_effect_container": self.has_effect_container,
            "has_effect_identity": self.has_effect_identity,
            "has_value_arguments": self.has_value_arguments,
            "has_duration_or_delay": self.has_duration_or_delay,
            "has_target_encoding": self.has_target_encoding,
            "has_zone_encoding": self.has_zone_encoding,
            "has_trigger_encoding": self.has_trigger_encoding,
            "has_critical_branch": self.has_critical_branch,
            "candidate_effect_instance_graph": self.candidate_effect_instance_graph,
        }


def _normalize_name(name: str) -> str:
    return "".join(character for character in name.lower() if character.isalnum())


def _value_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _records(payload: object) -> tuple[str, list[dict[str, Any]]]:
    if isinstance(payload, dict):
        records = list(payload.values())
        top_level_kind = "object"
    elif isinstance(payload, list):
        records = payload
        top_level_kind = "array"
    else:
        raise ValueError("effect source JSON must be an object or array of records")

    if any(not isinstance(record, dict) for record in records):
        raise ValueError("effect source records must be JSON objects")
    return top_level_kind, records


def _walk(value: object, path: str, inventory: dict[str, tuple[set[str], int]]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            types, count = inventory.setdefault(child_path, (set(), 0))
            types.add(_value_type(child))
            inventory[child_path] = (types, count + 1)
            _walk(child, child_path, inventory)
        return

    if isinstance(value, list):
        item_path = f"{path}[]"
        for child in value:
            types, count = inventory.setdefault(item_path, (set(), 0))
            types.add(_value_type(child))
            inventory[item_path] = (types, count + 1)
            _walk(child, item_path, inventory)


def audit_effect_instance_source(path: str | Path) -> EffectSourceAuditReport:
    source_path = Path(path)
    raw_bytes = source_path.read_bytes()
    source_hash = hashlib.sha256(raw_bytes).hexdigest()
    payload = json.loads(raw_bytes.decode("utf-8"))
    top_level_kind, records = _records(payload)

    inventory: dict[str, tuple[set[str], int]] = {}
    for record in records:
        _walk(record, "", inventory)

    fields = tuple(
        SourceFieldEvidence(
            path=field_path,
            value_types=tuple(sorted(value_types)),
            occurrences=occurrences,
        )
        for field_path, (value_types, occurrences) in sorted(inventory.items())
    )

    normalized_leaf_names = {
        _normalize_name(field.path.removesuffix("[]").rsplit(".", 1)[-1])
        for field in fields
    }
    has_effect_container = bool(normalized_leaf_names & _EFFECT_CONTAINER_NAMES)
    has_effect_identity = bool(normalized_leaf_names & _EFFECT_IDENTITY_NAMES)
    has_value_arguments = bool(normalized_leaf_names & _VALUE_ARGUMENT_NAMES)
    has_duration_or_delay = bool(normalized_leaf_names & _DURATION_DELAY_NAMES)
    has_target_encoding = bool(normalized_leaf_names & _TARGET_ENCODING_NAMES)
    has_zone_encoding = bool(normalized_leaf_names & _ZONE_ENCODING_NAMES)
    has_trigger_encoding = bool(normalized_leaf_names & _TRIGGER_ENCODING_NAMES)
    has_critical_branch = bool(normalized_leaf_names & _CRITICAL_BRANCH_NAMES)

    effect_container_prefixes = tuple(
        field.path.removesuffix("[]")
        for field in fields
        if _normalize_name(field.path.removesuffix("[]").rsplit(".", 1)[-1])
        in _EFFECT_CONTAINER_NAMES
    )
    identity_paths = tuple(
        field.path
        for field in fields
        if _normalize_name(field.path.removesuffix("[]").rsplit(".", 1)[-1])
        in _EFFECT_IDENTITY_NAMES
    )
    candidate_effect_instance_graph = any(
        identity_path.startswith(f"{prefix}[]") or identity_path.startswith(f"{prefix}.")
        for prefix in effect_container_prefixes
        for identity_path in identity_paths
    )

    return EffectSourceAuditReport(
        source_file=source_path.name,
        source_hash=source_hash,
        top_level_kind=top_level_kind,
        record_count=len(records),
        fields=fields,
        has_effect_container=has_effect_container,
        has_effect_identity=has_effect_identity,
        has_value_arguments=has_value_arguments,
        has_duration_or_delay=has_duration_or_delay,
        has_target_encoding=has_target_encoding,
        has_zone_encoding=has_zone_encoding,
        has_trigger_encoding=has_trigger_encoding,
        has_critical_branch=has_critical_branch,
        candidate_effect_instance_graph=candidate_effect_instance_graph,
    )


def render_effect_source_audit_markdown(report: EffectSourceAuditReport) -> str:
    yes_no = lambda value: "YES" if value else "NO"
    lines = [
        "# Spell Effect-Instance Source Audit",
        "",
        f"- Source file: `{report.source_file}`",
        f"- SHA-256: `{report.source_hash}`",
        f"- Top-level kind: `{report.top_level_kind}`",
        f"- Record count: **{report.record_count}**",
        f"- Candidate effect-instance graph: {yes_no(report.candidate_effect_instance_graph)}",
        "",
        "## Evidence flags",
        "",
        f"- Effect container: {yes_no(report.has_effect_container)}",
        f"- Effect identity: {yes_no(report.has_effect_identity)}",
        f"- Value arguments: {yes_no(report.has_value_arguments)}",
        f"- Duration/delay: {yes_no(report.has_duration_or_delay)}",
        f"- Target encoding: {yes_no(report.has_target_encoding)}",
        f"- Zone encoding: {yes_no(report.has_zone_encoding)}",
        f"- Trigger encoding: {yes_no(report.has_trigger_encoding)}",
        f"- Critical branch: {yes_no(report.has_critical_branch)}",
        "",
        "## Observed field paths",
        "",
        "| Path | Types | Occurrences |",
        "| --- | --- | ---: |",
    ]
    lines.extend(
        f"| `{field.path}` | `{', '.join(field.value_types)}` | {field.occurrences} |"
        for field in report.fields
    )
    lines.extend(
        [
            "",
            "> This report inventories source evidence only. It does not decode raw masks, zones, arguments, triggers, or effect semantics.",
            "",
        ]
    )
    return "\n".join(lines)
