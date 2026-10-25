"""Composition-root intake of staged protocol-change evidence.

Only setup performs this bounded read-only audit. Never extract archive
content, execute downloaded adapter code, or activate a new protocol version.
"""
from __future__ import annotations

from pathlib import Path
from anka_protocol.evidence_intake import inspect_evidence_pack, IntakeRejected
from anka_protocol.capability_matrix import assess_capabilities

MAX_STAGED_PACKS = 3


def audit_staged_updates(root: Path, *, observer=None) -> dict:
    folder = Path(root) / 'protocol_updates'
    if not folder.exists():
        return {'status': 'NO_PACK_STAGED', 'packs': [], 'live_semantic_certified': False,
                'adapter_activated': False, 'physical_input_sent': False}
    if not folder.is_dir() or folder.is_symlink():
        raise IntakeRejected('P28_STAGING_DIRECTORY_INVALID')
    entries = list(folder.iterdir())
    if len(entries) > MAX_STAGED_PACKS:
        raise IntakeRejected('P28_TOO_MANY_STAGED_PACKS')
    reports = []
    for item in sorted(entries, key=lambda p:p.name):
        if item.is_symlink() or not item.is_file() or item.suffix.lower() != '.zip':
            raise IntakeRejected('P28_STAGING_ENTRY_INVALID')
        intake = inspect_evidence_pack(item)
        report = intake.to_dict()
        # P29 compares pinned, exact-source evidence only with a locally vetted
        # adapter. Even perfect agreement is RESEARCH ONLY, never activation.
        from anka_app.protocol_evidence_compare import compare_pack
        report['semantic_comparison'] = compare_pack(item, root=root, expected_archive_sha256=intake.archive_sha256)
        report['capability_assessment'] = assess_capabilities(intake, report['semantic_comparison'])
        reports.append(report)
        if observer is not None:
            observer.record('protocol.evidence_pack_audited', boundary='protocol.evidence_intake',
                payload={'status':report['status'],'archive_sha256':report['archive_sha256'],
                         'build':report['protocol_build'],
                         'capabilities':report['covered_capabilities'],
                         'missing':report['missing_capabilities'],
                         'comparison_status': report['semantic_comparison']['status'],
                         'comparison_mismatches': report['semantic_comparison']['mismatched_cases'],
                         'capability_assessment_status':report['capability_assessment']['status'],
                         'required_blocked_capabilities':report['capability_assessment']['required_blocked_capabilities'],
                         'adapter_activated':False,'live_semantic_certified':False})
    if len({r['protocol_build'] for r in reports}) != len(reports):
        raise IntakeRejected('P28_DUPLICATE_STAGED_BUILD')
    return {'status':'RESEARCH_PACKS_AUDITED_NOT_ACTIVATED' if reports else 'NO_PACK_STAGED',
            'packs':reports,'live_semantic_certified':False,
            'adapter_activated':False,'physical_input_sent':False}
