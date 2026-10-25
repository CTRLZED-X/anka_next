"""Composition root: synthetic reducer + preserved kernel + read-only Decision.

No action driver is imported or instantiated. This module never reads a real
process or game memory. Historical static data is a learning/replay reference.
"""
from __future__ import annotations
from pathlib import Path
from anka_contracts.state import OfflineStateEvent
from anka_contracts.decision import CastProbe
from anka_live_state.reducer import apply_offline_event
from anka_decision.probe import inspect_cast_probe


def reference_kernel(root:Path):
    from anka_game_kernel import GameKernel, ExternalGameDataConfig,load_bundled_spell_mechanics_pack
    assets=root/'assets/game_data'
    return GameKernel.start(ExternalGameDataConfig(
        static_directory=assets/'Static',mapuse_directory=assets/'Mapuse',
        static_source_version='3.6.10.10',mapuse_source_version='3.6.10.10',
        pack_version='offline-historical-smoke',game_version='3.6.10.10'),
        spell_mechanics=load_bundled_spell_mechanics_pack())


def synthetic_decision_snapshot(*,ap=11,cooldown=0):
    source=None
    events=[('FIGHT_STARTED',{}),('ACTOR_SEEN',{'actor_id':777}),
           ('ACTOR_HP_SET',{'actor_id':777,'value':2800,'maximum':3200}),
           ('ACTOR_RESOURCE_SET',{'actor_id':777,'resource':'AP','value':ap}),
           ('ACTOR_RESOURCE_SET',{'actor_id':777,'resource':'MP','value':5}),
           ('ACTOR_POSITION_SET',{'actor_id':777,'value':215}),
           ('ACTOR_COOLDOWNS_SET',{'actor_id':777,'cooldowns':((32435,cooldown),)}),
           ('TURN_STARTED',{'actor_id':777})]
    for n,(kind,data) in enumerate(events,1):
        e=OfflineStateEvent('p12-%s'%n,'cra-session','cra',1,'test-fight',n,kind,**data)
        source=apply_offline_event(source,e)
    return source


def decision_demo(*,root:Path,observer=None)->dict:
    kernel=reference_kernel(root)
    probe=CastProbe('cra-session','cra',1,'test-fight',8,777,32435,3,220)
    snapshot=synthetic_decision_snapshot()
    reports={
        'complete_synthetic':inspect_cast_probe(snapshot,probe,kernel=kernel).to_dict(),
        'insufficient_ap':inspect_cast_probe(synthetic_decision_snapshot(ap=0),probe,kernel=kernel).to_dict(),
        'cooldown_active':inspect_cast_probe(synthetic_decision_snapshot(cooldown=2),probe,kernel=kernel).to_dict(),
    }
    if observer is not None:
        try:observer.record('decision.synthetic_probes_completed',boundary='decision.research_only',payload={
            'statuses':{k:v['status'] for k,v in reports.items()},'actionable':False,
            'physical_input_sent':False})
        except Exception:pass
    return {'operation':'decision-demo','status':'SYNTHETIC_PREVIEW_ONLY',
            'reports':reports,'historical_static_game_version':'3.6.10.10',
            'live_ready':False,'physical_input_sent':False}


def decision_audit(database:Path,probe:CastProbe,*,root:Path,observer=None)->dict:
    """Use P8 replay-verified state, never a free-floating database projection."""
    from anka_canonical.journal import SQLiteFixtureJournal
    with SQLiteFixtureJournal(Path(database),reducer=apply_offline_event,read_only=True) as journal:
        observed=journal.audited_snapshot(probe.session_id)
    kernel=reference_kernel(root)
    report=inspect_cast_probe(observed['snapshot'],probe,kernel=kernel)
    result={'operation':'decision-audit','status':report.status,
            'journal_integrity':observed['audit']['status'],
            'report':report.to_dict(),'live_ready':False,'physical_input_sent':False}
    if observer is not None:
        try:
            observer.record('decision.synthetic_journal_probed',boundary='decision.read_only_audit',
                payload={'status':report.status,'reasons':report.reasons,
                    'kernel_legality':report.kernel_legality,'actionable':False})
            if report.status.startswith('BLOCKED'):
                path=observer.export_incident('DECISION_PROBE_EVIDENCE_BLOCKED',
                    boundary='decision.read_only_audit',
                    detail='Synthetic journal passed integrity checking but decision preconditions were not met.')
                result['incident_bundle']=str(path)
        except Exception:
            result['incident_bundle']='UNAVAILABLE_DIAGNOSTICS_SINK_FAILURE'
    return result


def parse_decision_probe(parts:list[str])->CastProbe:
    if len(parts)!=9:raise ValueError('DECISION_AUDIT_REQUIRES_9_SCOPE_FIELDS')
    try:
        return CastProbe(parts[0],parts[1],int(parts[2]),parts[3],int(parts[4]),
                         int(parts[5]),int(parts[6]),int(parts[7]),int(parts[8]))
    except (ValueError,TypeError) as exc:
        raise ValueError('DECISION_AUDIT_SCOPE_INVALID') from exc
