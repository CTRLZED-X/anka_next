"""Pinned R5.198 handler inventory, strictly passive and never imported as code."""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
import json

EXPECTED_INVENTORY_SHA256='cd603f9308d261e7aa4e95a27623f19b2f3de6732255b15018c73fa2b4230bc3'
EXPECTED_GROUPS=frozenset({'world_identity','fight_state','resources_effects','combat_actions','fight_lifecycle'})
RESEARCH_NAMES=frozenset({'jvi','jvj','jup','jxd'})

class HistoricalLineageRejected(ValueError):
    pass


def audit_historical_lineage(root:Path)->dict:
    root=Path(root)
    directory=root/'reference/protocol/historical_3_7_10_10'
    inventory=directory/'handler_inventory.json'
    if directory.is_symlink() or inventory.is_symlink():
        raise HistoricalLineageRejected('P45_LINEAGE_SYMLINK_FORBIDDEN')
    try:
        blob=inventory.read_bytes()
        if len(blob)>65536 or sha256(blob).hexdigest()!=EXPECTED_INVENTORY_SHA256:
            raise HistoricalLineageRejected('P45_INVENTORY_HASH_MISMATCH')
        doc=json.loads(blob)
        if (doc.get('schema_version')!=1 or doc.get('source_role')!='R5_198_HISTORICAL_REFERENCE_ONLY' or
            doc.get('protocol_build')!='Dofus 3.7.10.10' or doc.get('current_client_certified') is not False or
            doc.get('live_adapter_activated') is not False):
            raise HistoricalLineageRejected('P45_LINEAGE_SCOPE_INVALID')
        source=doc['source_assets']
        if set(source)!={'registry','fight','resources','actions','lifecycle','adapter','wire_catalog'}:
            raise HistoricalLineageRejected('P45_SOURCE_INVENTORY_INVALID')
        for entry in source.values():
            rel=Path(entry['stored_path'])
            if rel.is_absolute() or '..' in rel.parts or rel.suffix!='.txt' or not rel.as_posix().startswith('reference/protocol/historical_3_7_10_10/archived_source/'):
                raise HistoricalLineageRejected('P45_SOURCE_PATH_UNSAFE')
            path=root/rel
            if any(part.is_symlink() for part in (root, *(root/Path(*rel.parts[:k]) for k in range(1,len(rel.parts)+1)))):
                raise HistoricalLineageRejected('P45_SOURCE_PATH_UNSAFE')
            if path.is_symlink() or not path.is_file() or path.stat().st_size>100000:
                raise HistoricalLineageRejected('P45_SOURCE_UNAVAILABLE')
            content=path.read_bytes()
            if len(content)!=entry['size'] or sha256(content).hexdigest()!=entry['sha256']:
                raise HistoricalLineageRejected('P45_SOURCE_HASH_MISMATCH')
        bindings=doc['bindings']; groups=doc['groups']
        if (set(groups)!=EXPECTED_GROUPS or len(bindings)!=39 or
            set(doc['research_decoder_names'])!=RESEARCH_NAMES or
            any(set(wires)!={name for name, b in bindings.items() if b['group']==group} for group,wires in groups.items()) or
            any(b['group'] not in groups or not b['observation_only'] for b in bindings.values()) or
            not RESEARCH_NAMES.issubset(bindings)):
            raise HistoricalLineageRejected('P45_HANDLER_INVENTORY_INVALID')
        return {'status':'HISTORICAL_SOURCE_HASHES_VERIFIED_RESEARCH_ONLY',
                'historical_build':'Dofus 3.7.10.10','source_files':len(source),
                'registered_handler_names':len(bindings),'handler_groups':len(groups),
                'research_lifecycle_handlers':len(RESEARCH_NAMES),
                'current_client_certified':False,'canonical_events_committed':0,
                'physical_input_permitted':False}
    except (OSError,KeyError,TypeError,ValueError) as exc:
        if isinstance(exc,HistoricalLineageRejected):
            raise
        raise HistoricalLineageRejected('P45_LINEAGE_DATA_INVALID') from exc
