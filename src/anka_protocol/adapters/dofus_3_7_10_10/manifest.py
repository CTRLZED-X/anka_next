"""Hash-bound historical M5 adapter release descriptor."""
from anka_contracts.protocol import AdapterReleaseDescriptor
from .adapter import Historical371010Adapter,BUILD,RELEASE_ID

CODE_SHA256='57c5a59bb5e19dca1e57352ac98ed3d3e7c4d59eed144aef820e3b7a7e4c11b8'
EVIDENCE_MANIFEST_SHA256='5ab5e7485b646834f5d63b489891b8ee4a7a49a03a9147753c2c74c5da28f5f4'

def descriptor()->AdapterReleaseDescriptor:
    return AdapterReleaseDescriptor(
        RELEASE_ID,BUILD,CODE_SHA256,EVIDENCE_MANIFEST_SHA256,1,0,'REPLAY_CERTIFIED',
        capabilities=('ACTOR_AP','ACTOR_MP','ACTOR_RANGE','ACTOR_HP','ACTOR_COOLDOWN'),
        certified_scenarios=('HISTORICAL_SYNTHETIC_RESOURCE_REPLAY','HISTORICAL_SYNTHETIC_COOLDOWN_REPLAY'),
        action_scopes=(),
    )

def factory(**kwargs):
    return Historical371010Adapter(descriptor=descriptor(),**kwargs)
