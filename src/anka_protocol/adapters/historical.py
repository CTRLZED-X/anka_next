"""R5.198 historical wire observation catalog. Explicitly never a live decoder."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json
from anka_contracts.protocol import WireMessage, ProtocolFinding


class CatalogRejected(ValueError):pass


@dataclass(frozen=True,slots=True)
class HistoricalCatalog:
    adapter_id: str
    protocol_build: str
    known_keys: frozenset[tuple[str,str]]
    evidence_source: str = 'R5.198_HISTORY_ONLY'
    semantic_certified: bool = False

    def classify(self,message:WireMessage)->ProtocolFinding:
        token=(message.name,message.direction)
        if token in self.known_keys:
            code='CATALOG_OBSERVED_ONLY'
        elif any(name==message.name for name,_ in self.known_keys):
            code='DIRECTION_MISMATCH'
        else:
            code='UNKNOWN_WIRE'
        return ProtocolFinding(code,message.name,message.direction,message.packet_number,
             reason='Wire observation does not prove current-build semantics')


def load_reference(root:Path)->HistoricalCatalog:
    folder=Path(root)/'reference/protocol'
    try:
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf8'))
        if manifest.get('schema_version')!=1 or manifest.get('source_role')!='HISTORICAL_REFERENCE_ONLY' or manifest.get('certifies_current_build') is not False:
            raise CatalogRejected('REFERENCE_MANIFEST_UNSAFE')
        for filename,meta in manifest['files'].items():
            if filename not in {'dofus_3_7_10_10_wire_catalog.json','dofus_3_7_10_10_scenarios.json'}:
                raise CatalogRejected('REFERENCE_MANIFEST_UNEXPECTED_FILE')
            p=folder/filename
            raw=p.read_bytes()
            if sha256(raw).hexdigest()!=meta['sha256'] or len(raw)!=meta['size']:
                raise CatalogRejected('REFERENCE_HASH_MISMATCH')
        raw=json.loads((folder/'dofus_3_7_10_10_wire_catalog.json').read_text(encoding='utf8'))
        keys=set()
        for capture in raw['captures'].values():
            for key in capture['types']:
                name,direction=key.split('|')
                if direction not in ('client_to_server','server_to_client') or not name.isascii():
                    raise CatalogRejected('REFERENCE_CATALOG_INVALID')
                keys.add((name,direction))
        if not keys:raise CatalogRejected('REFERENCE_CATALOG_EMPTY')
        return HistoricalCatalog('dofus_3_7_10_10_observation','Dofus 3.7.10.10',frozenset(keys))
    except (KeyError,TypeError,ValueError,OSError) as exc:
        if isinstance(exc,CatalogRejected):raise
        raise CatalogRejected('REFERENCE_CATALOG_INVALID') from exc
