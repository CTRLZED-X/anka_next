from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable

from anka_game_kernel.knowledge.effect_source_audit import (
    EffectSourceAuditReport,
    audit_effect_instance_source,
)


_REPORT_SCHEMA = "r5b-effect-source-discovery/v1"

STATIC_SPELL_SOURCE_FILENAMES = (
    "Breeds.json",
    "CompanionSpells.json",
    "Effects.json",
    "SpellLevels.json",
    "SpellStates.json",
    "SpellVariants.json",
    "Spells.json",
)


@dataclass(frozen=True, slots=True)
class EffectSourceCandidate:
    source_path: str
    source_hash: str | None
    record_count: int | None
    evidence_score: int
    candidate_effect_instance_graph: bool
    has_effect_container: bool
    has_effect_identity: bool
    has_value_arguments: bool
    has_duration_or_delay: bool
    has_target_encoding: bool
    has_zone_encoding: bool
    has_trigger_encoding: bool
    has_critical_branch: bool
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "source_path": self.source_path,
            "source_hash": self.source_hash,
            "record_count": self.record_count,
            "evidence_score": self.evidence_score,
            "candidate_effect_instance_graph": self.candidate_effect_instance_graph,
            "has_effect_container": self.has_effect_container,
            "has_effect_identity": self.has_effect_identity,
            "has_value_arguments": self.has_value_arguments,
            "has_duration_or_delay": self.has_duration_or_delay,
            "has_target_encoding": self.has_target_encoding,
            "has_zone_encoding": self.has_zone_encoding,
            "has_trigger_encoding": self.has_trigger_encoding,
            "has_critical_branch": self.has_critical_branch,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class EffectSourceDiscoveryReport:
    schema: str
    source_label: str
    game_version: str | None
    roots: tuple[str, ...]
    total_json_files: int
    audited_files: int
    rejected_files: int
    candidate_graph_files: int
    expected_filenames: tuple[str, ...]
    missing_expected_filenames: tuple[str, ...]
    invalid_expected_filenames: tuple[str, ...]
    acquisition_complete: bool
    candidates: tuple[EffectSourceCandidate, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "source_label": self.source_label,
            "game_version": self.game_version,
            "roots": list(self.roots),
            "total_json_files": self.total_json_files,
            "audited_files": self.audited_files,
            "rejected_files": self.rejected_files,
            "candidate_graph_files": self.candidate_graph_files,
            "expected_filenames": list(self.expected_filenames),
            "missing_expected_filenames": list(self.missing_expected_filenames),
            "invalid_expected_filenames": list(self.invalid_expected_filenames),
            "acquisition_complete": self.acquisition_complete,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def _evidence_score(report: EffectSourceAuditReport) -> int:
    return (
        (100 if report.candidate_effect_instance_graph else 0)
        + (16 if report.has_effect_container else 0)
        + (16 if report.has_effect_identity else 0)
        + (8 if report.has_value_arguments else 0)
        + (4 if report.has_duration_or_delay else 0)
        + (4 if report.has_target_encoding else 0)
        + (4 if report.has_zone_encoding else 0)
        + (2 if report.has_trigger_encoding else 0)
        + (2 if report.has_critical_branch else 0)
    )


def _candidate_from_audit(source_path: str, report: EffectSourceAuditReport) -> EffectSourceCandidate:
    return EffectSourceCandidate(
        source_path=source_path,
        source_hash=report.source_hash,
        record_count=report.record_count,
        evidence_score=_evidence_score(report),
        candidate_effect_instance_graph=report.candidate_effect_instance_graph,
        has_effect_container=report.has_effect_container,
        has_effect_identity=report.has_effect_identity,
        has_value_arguments=report.has_value_arguments,
        has_duration_or_delay=report.has_duration_or_delay,
        has_target_encoding=report.has_target_encoding,
        has_zone_encoding=report.has_zone_encoding,
        has_trigger_encoding=report.has_trigger_encoding,
        has_critical_branch=report.has_critical_branch,
    )


def _rejected_candidate(source_path: str, error: Exception) -> EffectSourceCandidate:
    return EffectSourceCandidate(
        source_path=source_path,
        source_hash=None,
        record_count=None,
        evidence_score=0,
        candidate_effect_instance_graph=False,
        has_effect_container=False,
        has_effect_identity=False,
        has_value_arguments=False,
        has_duration_or_delay=False,
        has_target_encoding=False,
        has_zone_encoding=False,
        has_trigger_encoding=False,
        has_critical_branch=False,
        error=f"{type(error).__name__}: {error}",
    )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _display_path(file_path: Path, directory_roots: tuple[Path, ...]) -> str:
    owners = [root for root in directory_roots if _is_relative_to(file_path, root)]
    if not owners:
        return file_path.name
    owner = min(owners, key=lambda path: (len(path.parts), path.as_posix()))
    return file_path.relative_to(owner.parent).as_posix()


def _root_label(root: Path, directory_roots: tuple[Path, ...]) -> str:
    if root.is_file():
        return root.name
    parents = [other for other in directory_roots if other != root and _is_relative_to(root, other)]
    if not parents:
        return root.name
    owner = min(parents, key=lambda path: (len(path.parts), path.as_posix()))
    return root.relative_to(owner.parent).as_posix()


def discover_effect_instance_sources(
    roots: Iterable[str | Path],
    *,
    source_label: str,
    game_version: str | None = None,
    expected_filenames: Iterable[str] = (),
) -> EffectSourceDiscoveryReport:
    if not source_label.strip():
        raise ValueError("source_label must be non-empty")

    resolved_roots = tuple(sorted({Path(root).resolve() for root in roots}, key=lambda path: path.as_posix()))
    if not resolved_roots:
        raise ValueError("at least one discovery root is required")
    for root in resolved_roots:
        if not root.exists():
            raise FileNotFoundError(f"discovery root does not exist: {root}")

    directory_roots = tuple(root for root in resolved_roots if root.is_dir())
    discovered: set[Path] = set()
    for root in resolved_roots:
        if root.is_dir():
            discovered.update(path.resolve() for path in root.rglob("*.json") if path.is_file())
        elif root.is_file() and root.suffix.lower() == ".json":
            discovered.add(root)

    candidates: list[EffectSourceCandidate] = []
    valid_discovered_names: set[str] = set()
    for path in sorted(discovered, key=lambda item: item.as_posix()):
        display_path = _display_path(path, directory_roots)
        try:
            audit = audit_effect_instance_source(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            candidates.append(_rejected_candidate(display_path, exc))
        else:
            valid_discovered_names.add(path.name.casefold())
            candidates.append(_candidate_from_audit(display_path, audit))

    candidates.sort(key=lambda candidate: (-candidate.evidence_score, candidate.source_path))
    candidate_tuple = tuple(candidates)
    audited_files = sum(candidate.error is None for candidate in candidate_tuple)
    rejected_files = len(candidate_tuple) - audited_files
    candidate_graph_files = sum(candidate.candidate_effect_instance_graph for candidate in candidate_tuple)
    root_labels = tuple(sorted(_root_label(root, directory_roots) for root in resolved_roots))
    normalized_expected = tuple(sorted({str(name) for name in expected_filenames}))
    discovered_names = {path.name.casefold() for path in discovered}
    missing_expected = tuple(
        name for name in normalized_expected if name.casefold() not in discovered_names
    )
    invalid_expected = tuple(
        name
        for name in normalized_expected
        if name.casefold() in discovered_names and name.casefold() not in valid_discovered_names
    )

    return EffectSourceDiscoveryReport(
        schema=_REPORT_SCHEMA,
        source_label=source_label,
        game_version=game_version,
        roots=root_labels,
        total_json_files=len(candidate_tuple),
        audited_files=audited_files,
        rejected_files=rejected_files,
        candidate_graph_files=candidate_graph_files,
        expected_filenames=normalized_expected,
        missing_expected_filenames=missing_expected,
        invalid_expected_filenames=invalid_expected,
        acquisition_complete=not missing_expected and not invalid_expected,
        candidates=candidate_tuple,
    )


def render_effect_source_discovery_markdown(report: EffectSourceDiscoveryReport) -> str:
    lines = [
        "# Spell Effect-Instance Source Discovery",
        "",
        f"- Schema: `{report.schema}`",
        f"- Source label: `{report.source_label}`",
        f"- Game/client version: `{report.game_version or 'unspecified'}`",
        f"- JSON files discovered: **{report.total_json_files}**",
        f"- Successfully audited: **{report.audited_files}**",
        f"- Rejected: **{report.rejected_files}**",
        f"- Candidate effect-instance graphs: **{report.candidate_graph_files}**",
        f"- Acquisition complete: **{'YES' if report.acquisition_complete else 'NO'}**",
        "",
        "## Roots",
        "",
    ]
    lines.extend(f"- `{root}`" for root in report.roots)
    if report.expected_filenames:
        lines.extend(["", "## Expected acquisition files", ""])
        missing = set(report.missing_expected_filenames)
        invalid = set(report.invalid_expected_filenames)
        def _status(name: str) -> str:
            if name in missing:
                return " "
            if name in invalid:
                return "!"
            return "x"
        lines.extend(
            f"- [{_status(name)}] `{name}`"
            for name in report.expected_filenames
        )
        if report.missing_expected_filenames:
            lines.append("- Missing required exports: " + ", ".join(f"`{name}`" for name in report.missing_expected_filenames))
        if report.invalid_expected_filenames:
            lines.append("- Invalid/unreadable required exports: " + ", ".join(f"`{name}`" for name in report.invalid_expected_filenames))
    lines.extend(
        [
            "",
            "## Ranked sources",
            "",
            "| Rank | Source | Score | Candidate graph | Records | SHA-256 | Error |",
            "| ---: | --- | ---: | --- | ---: | --- | --- |",
        ]
    )
    for index, candidate in enumerate(report.candidates, start=1):
        candidate_text = "YES" if candidate.candidate_effect_instance_graph else "NO"
        records = "" if candidate.record_count is None else str(candidate.record_count)
        source_hash = "" if candidate.source_hash is None else candidate.source_hash
        error = "" if candidate.error is None else candidate.error.replace("|", "\\|")
        lines.append(
            f"| {index} | `{candidate.source_path}` | {candidate.evidence_score} | {candidate_text} | {records} | `{source_hash}` | {error} |"
        )
    lines.extend(
        [
            "",
            "> Ranking is structural evidence only. This report does not decode raw effect semantics.",
            "",
        ]
    )
    return "\n".join(lines)
