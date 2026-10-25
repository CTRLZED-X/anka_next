"""P53 source-integrity audit for historical world-identity recovery."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json

EXPECTED_MANIFEST_SHA256='ca61dfe638f13387c400e480284adb9a66ecb0e22873514f58f03a865397b5d3'
EXPECTED_SOURCE_SHA256='cfac4d7e451ea0b484d6d0d15c80742a81690aca7fdf58d93d283aba6104ad0a'


class HistoricalIdentityLineageRejected(ValueError):
    pass


def audit_historical_identity_lineage(root: Path) -> dict:
    root=Path(root)
    manifest=root/'reference/protocol/historical_3_7_10_10/identity_recovery_manifest.json'
    try:
        if manifest.is_symlink() or not manifest.is_file():
            raise HistoricalIdentityLineageRejected('P53_IDENTITY_MANIFEST_UNAVAILABLE')
        blob=manifest.read_bytes()
        if len(blob) > 16384 or sha256(blob).hexdigest() != EXPECTED_MANIFEST_SHA256:
            raise HistoricalIdentityLineageRejected('P53_IDENTITY_MANIFEST_HASH_MISMATCH')
        doc=json.loads(blob)
        required={
            'schema_version':1,
            'source_role':'R5_198_HISTORICAL_REFERENCE_ONLY',
            'protocol_build':'Dofus 3.7.10.10',
            'accepted_identity_wire':'jnj',
            'accepted_capability':'LOCAL_ACTOR',
            'accepted_registry_declared':True,
            'reference_only_wire':'jns',
            'reference_only_registry_declared':False,
            'current_client_certified':False,
            'canonical_authority':False,
            'physical_input_permitted':False,
        }
        if any(doc.get(k) != v for k,v in required.items()):
            raise HistoricalIdentityLineageRejected('P53_IDENTITY_MANIFEST_SCOPE_INVALID')
        rel=Path(doc['stored_path'])
        if (rel.is_absolute() or '..' in rel.parts or rel.as_posix() !=
                'reference/protocol/historical_3_7_10_10/archived_source/world_identity.source.txt'):
            raise HistoricalIdentityLineageRejected('P53_IDENTITY_SOURCE_PATH_INVALID')
        source=root/rel
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 100000:
            raise HistoricalIdentityLineageRejected('P53_IDENTITY_SOURCE_UNAVAILABLE')
        raw=source.read_bytes()
        if (len(raw) != doc['source_size'] or sha256(raw).hexdigest() != doc['source_sha256'] or
                doc['source_sha256'] != EXPECTED_SOURCE_SHA256):
            raise HistoricalIdentityLineageRejected('P53_IDENTITY_SOURCE_HASH_MISMATCH')
        reason=doc.get('reason')
        if not isinstance(reason,str) or 'jnj' not in reason or 'jns' not in reason:
            raise HistoricalIdentityLineageRejected('P53_IDENTITY_DISCREPANCY_NOT_RECORDED')
        return {
            'status':'HISTORICAL_IDENTITY_SOURCE_VERIFIED_RESEARCH_ONLY',
            'historical_build':'Dofus 3.7.10.10',
            'accepted_identity_wire':'jnj',
            'reference_only_wire':'jns',
            'registry_discrepancy_preserved':True,
            'current_client_certified':False,
            'canonical_commits':0,
            'physical_input_permitted':False,
        }
    except (OSError,KeyError,TypeError,ValueError,json.JSONDecodeError) as exc:
        if isinstance(exc,HistoricalIdentityLineageRejected):
            raise
        raise HistoricalIdentityLineageRejected('P53_IDENTITY_LINEAGE_DATA_INVALID') from exc
