"""Headless operations: offline + optional read-only Windows capture; no game input."""
from __future__ import annotations
from pathlib import Path
import sys
import json
import subprocess
import importlib.util
from hashlib import sha256
from typing import Any

from anka_app.configuration import load_user_config,ConfigurationError
from anka_app.bootstrap.early_record import emergency_marker
from anka_observability.api import LocalDiagnostics
from anka_observability.redaction import safe_exception_frames
from anka_observability.bundle import verify_incident
from anka_client.reference_assets import audit_calibration
from anka_client.api import inspect_local_clients, audit_reference_bridge_source
from anka_capture.api import inspect_pcapng, CaptureRejected
from anka_execution import ExecutionLedgerRejected, ExecutionLedgerIntegrityError, ExecutionTransitionRejected
from anka_protocol.evidence_intake import IntakeRejected

ROOT=Path(__file__).resolve().parents[2]
COMMANDS={'setup','check','start','stop','doctor','debug','verify','replay','clients','capture','capture-demo','capture-live','protocol-demo','protocol-audit','semantic-demo','semantic-audit','state-demo','state-audit','quality-demo','quality-audit','protocol-qualify','fight-demo','fight-audit','decision-demo','decision-audit','map-demo','tactical-demo','scoring-demo','sequence-demo','coordination-demo','execution-demo','execution-audit','execution-sim-demo'}


def _manifest_check()->dict:
    file=ROOT/'provenance/P66_COPIED_ASSET_MANIFEST.json'
    obj=json.loads(file.read_text(encoding='utf8'))
    failed=[]
    for item in obj['copied_assets']:
        path=ROOT/item['path']
        if not path.is_file() or sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            failed.append(item['path'])
    return {'asset_count':len(obj['copied_assets']),'integrity':'PASS' if not failed else 'FAIL','bad_assets':failed[:10]}


def _config_check(observer, config=None)->dict:
    config=config or load_user_config(ROOT/'config/user.json')
    out={'players':len(config.players),'leader':next(p.name for p in config.players if p.role=='leader'),
         'config_sha256':config.sha256,'route_id':config.mission.route_id,
         'min_monsters':config.mission.min_monsters,'max_monsters':config.mission.max_monsters,'capture_ports_configured':len(config.capture.server_ports)}
    observer.record('configuration.validated',boundary='configuration.validation',payload={'players':out['players'],'config_sha256':out['config_sha256'],'route_id':out['route_id']})
    return out


def _preflight(observer, *,check_kernel:bool=True)->dict:
    observer.record('bootstrap.preflight_started',boundary='bootstrap.preflight')
    if not (sys.version_info.major==3 and sys.version_info.minor==13):
        raise RuntimeError('UNSUPPORTED_PYTHON_VERSION')
    state={'python':f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}',
        'config':_config_check(observer),'assets':_manifest_check(), 'kernel':'NOT_CHECKED'}
    if state['assets']['integrity']!='PASS':raise RuntimeError('ASSET_INTEGRITY_FAILED')
    state['calibration']=audit_calibration(ROOT/'assets/calibration/shared_ui_1280x649.json',ROOT/'reference/calibration/shared_ui_calibration_1280x649.yaml')
    from anka_protocol.historical_lineage import audit_historical_lineage
    state['historical_protocol_lineage']=audit_historical_lineage(ROOT)
    observer.record('protocol.historical_lineage_checked',boundary='protocol.historical_reference',
                    payload={'status':state['historical_protocol_lineage']['status'],
                             'source_files':state['historical_protocol_lineage']['source_files'],
                             'live_certified':False,'physical_input_enabled':False})
    from anka_app.historical_stream_offline import historical_stream_smoke
    state['historical_stream_replay'] = historical_stream_smoke()
    from anka_app.historical_transport_offline import historical_transport_smoke
    state['historical_capture_to_replay'] = historical_transport_smoke(ROOT)
    from anka_app.historical_pcapng_offline import historical_pcapng_smoke
    state['historical_pcapng_research'] = historical_pcapng_smoke(ROOT)
    from anka_app.historical_pcapng_inventory_offline import historical_flow_inventory_smoke
    state['historical_pcapng_flow_inventory'] = historical_flow_inventory_smoke(ROOT)
    observer.record('protocol.historical_pcapng_flow_inventory_checked',
                    boundary='protocol.flow_reconnaissance_only',
                    payload={'status':state['historical_pcapng_flow_inventory']['status'],
                             'candidate_flows':state['historical_pcapng_flow_inventory']['candidate_flows'],
                             'account_binding_verified':False,
                             'canonical_commits':0,'physical_input_sent':False})
    observer.record('protocol.historical_pcapng_research_checked',
                    boundary='protocol.pcapng_research_only',
                    payload={'status':state['historical_pcapng_research']['status'],
                             'driver_proof':False, 'account_binding':False,
                             'canonical_commits':0, 'physical_input_sent':False})
    observer.record('protocol.historical_transport_replay_checked',
                    boundary='protocol.research_only_transport',
                    payload={'status':state['historical_capture_to_replay']['status'],
                             'loss_guarded':True, 'framing_guarded':True,
                             'live_certified':False,'canonical_commits':0,
                             'physical_input_sent':False})
    observer.record('protocol.historical_stream_replay_checked',
                    boundary='protocol.research_only_evidence',
                    payload={'status':state['historical_stream_replay']['status'],
                             'unknown_wire_detected':True, 'duplicate_wire_blocked':True,
                             'live_certified':False,'canonical_commits':0,'physical_input_sent':False})
    from anka_protocol.historical_identity_lineage import audit_historical_identity_lineage
    state['historical_identity_lineage'] = audit_historical_identity_lineage(ROOT)
    from anka_app.historical_identity_offline import historical_identity_topology_smoke
    state['historical_identity_topology'] = historical_identity_topology_smoke()
    observer.record('protocol.historical_identity_topology_checked',
                    boundary='protocol.historical_identity_research_only',
                    payload=state['historical_identity_topology'])
    from anka_app.historical_actor_continuity_offline import historical_actor_continuity_smoke
    state['historical_actor_continuity'] = historical_actor_continuity_smoke()
    observer.record('protocol.historical_actor_continuity_checked',
                    boundary='protocol.historical_actor_continuity_research_only',
                    payload=state['historical_actor_continuity'])
    from anka_app.capture_bound_admission_smoke import capture_bound_admission_smoke
    state['capture_bound_admission'] = capture_bound_admission_smoke(ROOT)
    observer.record('canonical.capture_bound_admission_checked',
                    boundary='canonical.pcapng_wire_research_only',
                    payload=state['capture_bound_admission'])
    from anka_app.packet_provenance_smoke import packet_provenance_smoke
    state['packet_local_provenance'] = packet_provenance_smoke(ROOT)
    observer.record('protocol.packet_local_provenance_checked',
                    boundary='protocol.research_only_packet_sources',
                    payload=state['packet_local_provenance'])
    from anka_app.ipv6_fragment_smoke import ipv6_fragment_smoke
    state['ipv6_fragment_completeness'] = ipv6_fragment_smoke()
    observer.record('capture.ipv6_fragment_completeness_checked',
                    boundary='capture.pcapng_research_only',
                    payload=state['ipv6_fragment_completeness'])
    from anka_app.capture_loss_smoke import capture_loss_metadata_smoke
    state['reported_capture_loss_integrity'] = capture_loss_metadata_smoke()
    observer.record('capture.reported_packet_loss_checked',
                    boundary='capture.pcapng_research_only',
                    payload=state['reported_capture_loss_integrity'])
    from anka_app.pcapng_section_smoke import pcapng_section_smoke
    state['pcapng_section_integrity'] = pcapng_section_smoke()
    observer.record('capture.pcapng_section_integrity_checked',
                    boundary='capture.pcapng_research_only',
                    payload=state['pcapng_section_integrity'])
    from anka_app.evidence_recording_smoke import evidence_recording_smoke
    state['consented_evidence_recording'] = evidence_recording_smoke()
    observer.record('capture.consent_recording_smoke_checked',
                    boundary='capture.passive_optional_local_research',
                    payload=state['consented_evidence_recording'])
    from anka_app.state_offline import transactional_journal_smoke,source_bound_receipt_smoke,schema_atomic_bootstrap_smoke
    from anka_app.admission_offline import admission_boundary_smoke
    state['untrusted_admission_boundary'] = admission_boundary_smoke()
    observer.record('canonical.admission_boundary_checked',
                    boundary='canonical.untrusted_rehearsal_quarantine',
                    payload=state['untrusted_admission_boundary'])
    state['atomic_schema_bootstrap'] = schema_atomic_bootstrap_smoke()
    observer.record('canonical.atomic_schema_bootstrap_checked',
                    boundary='canonical.synthetic_schema_integrity',
                    payload=state['atomic_schema_bootstrap'])
    state['transactional_fixture_journal'] = transactional_journal_smoke()
    observer.record('canonical.transactional_fixture_journal_checked',
                    boundary='canonical.synthetic_transaction_fence',
                    payload=state['transactional_fixture_journal'])
    state['source_bound_batch_receipt'] = source_bound_receipt_smoke()
    observer.record('canonical.source_bound_batch_receipt_checked',
                    boundary='canonical.synthetic_source_receipt',
                    payload=state['source_bound_batch_receipt'])
    from anka_app.ingress_readiness import host_flow_stability_smoke
    state['windows_flow_stability'] = host_flow_stability_smoke()
    from anka_app.ingress_readiness import host_topology_smoke
    state['windows_multi_account_topology'] = host_topology_smoke()
    observer.record('capture.windows_multi_account_topology_checked',
                    boundary='capture.research_process_association',
                    payload=state['windows_multi_account_topology'])
    observer.record('capture.windows_flow_stability_checked',
                    boundary='capture.read_only_owner_consistency',
                    payload=state['windows_flow_stability'])
    state['native_bridge_source']=audit_reference_bridge_source(ROOT)
    observer.record('client.bridge_reference_source_audited',boundary='client.bridge_source',
                    payload={'status':state['native_bridge_source']['status'],
                             'files':state['native_bridge_source']['file_count'],
                             'live_certified':False,'physical_input_enabled':False})
    if check_kernel:
        if importlib.util.find_spec('pydantic') is None:raise RuntimeError('KERNEL_DEPENDENCY_PYDANTIC_MISSING')
        import anka_game_kernel
        from anka_game_kernel.knowledge.spell_mechanics import load_bundled_spell_mechanics_pack
        pack=load_bundled_spell_mechanics_pack()
        state['kernel']={'version':anka_game_kernel.__version__, 'verified_spells_loaded':pack is not None}
    observer.record('bootstrap.preflight_passed',boundary='bootstrap.preflight',payload={'kernel':state['kernel']!='NOT_CHECKED','assets':state['assets']['asset_count']})
    return state


def _prior_runs(runtime:Path, current_id:str):
    out=[]
    for statefile in sorted((runtime/'runs').glob('*/run_state.json')):
        if statefile.parent.name==current_id:continue
        try:out.append((statefile.parent.name,json.loads(statefile.read_text(encoding='utf8'))))
        except (OSError,json.JSONDecodeError):out.append((statefile.parent.name,{'state':'CORRUPTED_RUN_STATE'}))
    return out


def _release_integrity_check(observer) -> dict:
    """Verify the installed immutable release while allowing user.json edits."""
    from anka_app.release_integrity import verify_release_integrity
    result=verify_release_integrity(ROOT)
    receipt=result.safe_receipt()
    observer.record('release.integrity_checked',boundary='startup.release_integrity',
                    owner_system='anka_app',severity='ERROR' if result.status!='PASS' else 'INFO',
                    failure_code='RELEASE_INTEGRITY_FAILED' if result.status!='PASS' else None,
                    payload=receipt)
    observer.register_snapshot('release_integrity',receipt)
    if result.status!='PASS': raise RuntimeError('RELEASE_INTEGRITY_FAILED')
    return receipt


def _revalidate_start_identity(observer, initial_config, initial_release:dict) -> dict:
    """Fence a bounded observation against config/release TOCTOU.

    The start path may spend seconds observing Windows/capture state. A config
    edit or release replacement during that window invalidates the composite
    evidence even though every individual observation might be well formed.
    """
    final_config=load_user_config(ROOT/'config/user.json')
    if final_config.sha256!=initial_config.sha256:
        raise RuntimeError('START_CONFIG_CHANGED_DURING_OBSERVATION')
    final_release=_release_integrity_check(observer)
    if final_release.get('manifest_sha256')!=initial_release.get('manifest_sha256'):
        raise RuntimeError('START_RELEASE_CHANGED_DURING_OBSERVATION')
    return {'config_sha256':final_config.sha256,
            'manifest_sha256':final_release.get('manifest_sha256')}


def _architecture_check(observer) -> dict:
    """Prevent accidental cross-system dependencies during normal setup/start."""
    from anka_app.architecture_guard import audit_source_boundaries
    audit = audit_source_boundaries(ROOT/'src')
    observer.record('architecture.boundaries_checked',
                    boundary='architecture.import_contract',
                    severity='ERROR' if audit.violations else 'INFO',
                    failure_code='ARCHITECTURE_BOUNDARY_VIOLATION' if audit.violations else None,
                    payload={'status': audit.status, 'packages': audit.packages,
                             'modules': audit.modules, 'violations': list(audit.violations[:10])})
    if audit.violations:
        raise RuntimeError('ARCHITECTURE_BOUNDARY_VIOLATION')
    return audit.to_dict()


def _readiness_check(observer) -> dict:
    """Explain missing live prerequisites without granting any input authority."""
    from anka_app.readiness import assess_live_readiness
    report = assess_live_readiness().to_dict()
    observer.record('readiness.live_capabilities_blocked',
                    boundary='readiness.production',
                    payload={'status': report['status'], 'blockers': report['blockers'],
                             'physical_input_enabled': False, 'live_ready': False})
    return report


def _capture_prereq_receipt(observer) -> dict:
    path=ROOT/'runtime'/'capture_prereq.json'
    manifest=ROOT/'RELEASE_MANIFEST.json'
    current_manifest_sha=sha256(manifest.read_bytes()).hexdigest() if manifest.is_file() else None
    if not path.is_file(): result={'status':'NOT_RUN_OR_NO_RECORD','capture_verified':False}
    else:
        try:
            if path.stat().st_size>16384: raise ValueError('CAPTURE_PREREQ_RECORD_OVERSIZED')
            obj=json.loads(path.read_text(encoding='utf8'))
            allowed=('schema_version','status','service_detected','dlls_detected','capture_verified','physical_input_enabled','release_manifest_sha256')
            result={k:obj[k] for k in allowed if k in obj}
            if not isinstance(result.get('status'),str): raise ValueError('INVALID')
            if current_manifest_sha is None or result.get('release_manifest_sha256')!=current_manifest_sha:
                result={'status':'STALE_SETUP_RECORD','capture_verified':False,'physical_input_enabled':False}
        except Exception: result={'status':'RECORD_INVALID','capture_verified':False}
    observer.record('capture.prerequisites_recorded',boundary='capture.host_prerequisites',owner_system='anka_capture',payload=result)
    observer.register_snapshot('capture_prerequisites',result)
    return result


def _bridge_setup_receipt(observer) -> dict:
    path=ROOT/'runtime'/'bridge_setup.json'
    manifest=ROOT/'RELEASE_MANIFEST.json'
    current_manifest_sha=sha256(manifest.read_bytes()).hexdigest() if manifest.is_file() else None
    if not path.is_file():
        result={'status':'NOT_RUN_OR_NO_RECORD','physical_input_enabled':False}
    else:
        try:
            if path.stat().st_size>32768: raise ValueError('BRIDGE_SETUP_RECORD_OVERSIZED')
            obj=json.loads(path.read_text(encoding='utf8'))
            if not isinstance(obj,dict) or not isinstance(obj.get('status'),str): raise ValueError('BRIDGE_SETUP_RECORD_INVALID')
            # Fixed allowlist: no local BepInEx/game paths may leak to normal diagnostics.
            allowed=('schema_version','status','bridge_contract_version','physical_input_enabled',
                     'external_download_performed','missing_files','exit_code','installed_sha256','built_sha256','release_manifest_sha256')
            result={k:obj[k] for k in allowed if k in obj}
            if current_manifest_sha is None or result.get('release_manifest_sha256')!=current_manifest_sha:
                result={'status':'STALE_SETUP_RECORD','physical_input_enabled':False}
        except Exception:
            result={'status':'RECORD_INVALID','physical_input_enabled':False}
    observer.record('client.bridge_setup_recorded',boundary='client.bridge_setup',owner_system='anka_client',
                    payload=result)
    observer.register_snapshot('bridge_setup',result)
    return result


def _start_static_preflight(observer, config=None) -> dict:
    """Fast immutable/config checks for every start; no slow synthetic replay."""
    if not (sys.version_info.major==3 and sys.version_info.minor==13):
        raise RuntimeError('UNSUPPORTED_PYTHON_VERSION')
    state={'python':f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}',
           'config':_config_check(observer, config),'assets':_manifest_check()}
    if state['assets']['integrity']!='PASS': raise RuntimeError('ASSET_INTEGRITY_FAILED')
    state['calibration']=audit_calibration(ROOT/'assets/calibration/shared_ui_1280x649.json',
                                           ROOT/'reference/calibration/shared_ui_calibration_1280x649.yaml')
    state['native_bridge_source']=audit_reference_bridge_source(ROOT)
    observer.record('start.static_preflight_passed',boundary='startup.static_preflight',
                    owner_system='anka_app',physical_input_state='NOT_SENT',payload={'assets':state['assets']['integrity'],
                    'config_sha256':state['config']['config_sha256'],'physical_input_enabled':False})
    observer.register_snapshot('startup_static',state)
    return state


def _host_check(observer, config=None) -> dict:
    """Read-only environment observations; never grant permission to click."""
    from anka_app.host_readiness import probe_host
    config = config or load_user_config(ROOT/'config/user.json')
    host = probe_host(config)
    observer.record('client.host_observation_completed', boundary='client.host_observation',
                    owner_system='anka_client',
                    payload={'status':host['status'], 'platform':host['platform'],
                             'candidate_windows':host['candidate_windows'],
                             'account_states':host['account_binding_states'],
                             'reasons':host['identity_issues'],
                             'geometry_issues':host['geometry_issues'],
                             'tcp_ownership':host['tcp_ownership'],
                             'tcp_candidate_processes':host['tcp_candidate_processes'],
                             'capture':host['capture'],'bridge':host.get('bridge',{}),'issues':host['issues'],
                             'live_certified':False,'physical_input_permitted':False})
    observer.register_snapshot('host_observation',host)
    return host


def _cross_system_smoke(observer, *, full: bool = False) -> dict:
    """Run the permanent *synthetic* historical failure matrix on setup/start.

    Independent expected outcomes are specified here, not inferred from the
    production fixture's own reason strings. A changed invariant fails setup.
    This check never promotes synthetic decisions or sends operating-system input.
    """
    from anka_app.integrated_offline import run_integrated_fixture
    expected = {
        'handoff': ('SYNTHETIC_REPLAY_PASS', None, 1, 'CONFIRMED'),
        'missing-end-confirmation': ('BLOCKED_SYNTHETIC', 'P17_OVERLAPPING_OR_EARLY_TURN', 0, None),
        'conflicting-owner': ('BLOCKED_SYNTHETIC', 'P20_CRA_TURN_STILL_ACTIVE', 0, None),
        'stale-enu-state': ('BLOCKED_SYNTHETIC', 'P20_ENU_TURN_NOT_RECONCILED', 0, None),
        'wrong-fight': ('BLOCKED_SYNTHETIC', 'P20_ENU_STATE_SCOPE_MISMATCH', 0, None),
        'focus-lost': ('BLOCKED_SYNTHETIC', 'P19_WINDOW_FOCUS_NOT_VERIFIED', 0, 'DISPATCH_UNCERTAIN'),
        'missing-outcome': ('BLOCKED_SYNTHETIC', 'P19_NO_INDEPENDENT_OUTCOME_EVIDENCE', 1, 'DISPATCH_UNCERTAIN'),
        'driver-raises-after': ('BLOCKED_SYNTHETIC', 'P19_FAKE_DRIVER_RAISED_AFTER_POSSIBLE_ATTEMPT', 1, 'DISPATCH_UNCERTAIN'),
        'duplicate-dispatch': ('SYNTHETIC_REPLAY_PASS', None, 1, 'CONFIRMED'),
        'source-missing': ('BLOCKED_SYNTHETIC', 'P22_TURN_SOURCE_MISSING_OR_DUPLICATED', 0, None),
        'source-reused': ('BLOCKED_SYNTHETIC', 'P22_SOURCE_REUSED', 0, None),
        'source-orphan': ('BLOCKED_SYNTHETIC', 'P22_SOURCE_NOT_IN_AUDITED_JOURNAL', 0, None),
    }
    # The complete nine-case matrix belongs in the developer verification suite.
    # Setup only runs a short critical smoke; start must not rerun the suite.
    cases = expected if full else {k: expected[k] for k in ('handoff', 'missing-end-confirmation')}
    outcomes = {}
    for scenario, (status, first_failure, attempts, ledger) in cases.items():
        result = run_integrated_fixture(ROOT, scenario=scenario)
        valid = (
            result.get('status') == status and
            result.get('first_failure') == first_failure and
            result.get('fake_attempts') == attempts and
            result.get('ledger_status') == ledger and
            result.get('physical_input_sent') is False and
            result.get('live_ready') is False and
            result.get('actionable') is False and
            result.get('authoritative') is False
        )
        if scenario in ('handoff', 'duplicate-dispatch'):
            valid = valid and result.get('decision', {}).get('status') == 'RESEARCH_ONLY'
        if scenario == 'duplicate-dispatch':
            valid = valid and 'execution.duplicate_rejected' in result.get('boundaries', ())
        if attempts == 0 and ledger is None:
            valid = valid and 'execution.fake_dispatch' not in result.get('boundaries', ())
        if not valid:
            observer.record('integration.p21_scenario_failed', severity='ERROR',
                            boundary='integration.synthetic_regression',
                            failure_code='P21_HISTORICAL_SCENARIO_REGRESSION',
                            payload={'scenario': scenario, 'observed_status': result.get('status'),
                                     'observed_failure': result.get('first_failure'),
                                     'fake_attempts': result.get('fake_attempts')})
            # Startup/setup smoke checks are bounded control points rather than
            # latency-sensitive gameplay paths.  Give an asynchronous diagnostic
            # recorder a short best-effort durability checkpoint before raising,
            # so caller cleanup cannot race a journal writer and erase the exact
            # regression evidence.  Observer failure must never replace the real
            # integration failure.
            flush=getattr(observer,'flush_journals',None)
            if callable(flush):
                try:flush(timeout_seconds=0.5)
                except Exception:pass
            raise RuntimeError('P20_INTEGRATION_SMOKE_FAILED')
        outcomes[scenario] = first_failure or 'PASS'
    observer.record('integration.p21_smoke_passed', boundary='integration.synthetic_only',
                    payload={'scenarios': len(outcomes), 'blocked_faults_verified': sum(1 for value in outcomes.values() if value != 'PASS'),
                             'first_failure_codes': outcomes, 'live_ready': False,
                             'physical_input_sent': False})
    flush=getattr(observer,'flush_journals',None)
    if callable(flush):
        try:flush(timeout_seconds=0.5)
        except Exception:pass
    return {'status': 'PASS_SYNTHETIC_ONLY', 'scenarios_checked': len(outcomes),
            'blocked_faults_verified': sum(1 for value in outcomes.values() if value != 'PASS'),
            'historical_incident_detected': outcomes['missing-end-confirmation'],
            'physical_input_sent': False}


def _shadow_projection_check(observer)->dict:
    """P33 contract smoke: no journal writer, no live source authority."""
    from anka_app.shadow_replay_offline import shadow_bridge_smoke
    from anka_app.reconstruction_gaps_offline import reconstruction_coverage_smoke
    result=shadow_bridge_smoke()
    coverage=reconstruction_coverage_smoke()
    from anka_app.effect_reconciliation_offline import effect_reconciliation_smoke
    effect_links=effect_reconciliation_smoke()
    from anka_app.target_effect_research_offline import target_effect_research_smoke
    target_effects=target_effect_research_smoke()
    observer.record('canonical.shadow_projection_checked',
                    boundary='canonical.synthetic_projection_compatibility',
                    payload={'status':result['status'],'rejected_failure':result['negative'],
                             'coverage_status':coverage['status'],
                             'spell_effect_gap_detected':coverage['effect_gap_detected'],
                             'effect_link_smoke':effect_links['status'],
                             'target_effect_research_smoke':target_effects['status'],
                             'canonical_commits':0,'physical_input_sent':False})
    return {**result,'reconstruction_coverage':coverage,'effect_reconciliation':effect_links,
            'target_effect_research':target_effects}


def _command(command:str,observer,extra:list[str])->dict:
    if command in ('setup','check'):
        release_integrity = _release_integrity_check(observer)
        preflight = _preflight(observer)
        boundaries = _architecture_check(observer)
        readiness = _readiness_check(observer)
        from anka_app.protocol_updates import audit_staged_updates
        protocol_updates = audit_staged_updates(ROOT, observer=observer) if command == 'setup' else {'status':'NOT_REQUESTED'}
        bridge_setup = _bridge_setup_receipt(observer) if command == 'setup' else {'status':'NOT_REQUESTED'}
        capture_prereq = _capture_prereq_receipt(observer) if command == 'setup' else {'status':'NOT_REQUESTED'}
        return {'operation':command,'status':'PASS','installation_status':'READY',
                'offline_foundation':'PASS','release_integrity':release_integrity,'preflight':preflight,
                'architecture':boundaries,'readiness':readiness,
                'host_observation':'NOT_RUN_DURING_SETUP_OR_CHECK',
                'protocol_updates':protocol_updates,'bridge_setup':bridge_setup,'capture_prerequisites':capture_prereq,
                'integration_smoke':_cross_system_smoke(observer) if command=='setup' else 'NOT_REQUESTED',
                'shadow_projection_smoke':_shadow_projection_check(observer) if command=='setup' else 'NOT_REQUESTED',
                'live_ready':False,'live_status':'NOT_CERTIFIED'}
    if command=='capture-demo':
        if extra: raise RuntimeError('CAPTURE_DEMO_TAKES_NO_ARGUMENTS')
        result=inspect_pcapng(ROOT/'examples/SYNTHETIC_CAPTURE_P4.pcapng',server_ports=(40400,),observer=observer)
        return {'operation':'capture-demo','status':'SYNTHETIC_CAPTURE_ONLY','receipt':result.to_dict(),
                'live_ready':False,'physical_input_sent':False}
    if command=='capture':
        if len(extra)!=1:
            raise RuntimeError('CAPTURE_REQUIRES_ONE_PCAPNG_PATH')
        cfg=load_user_config(ROOT/'config/user.json')
        if not cfg.capture.server_ports:
            raise RuntimeError('CAPTURE_PORTS_NOT_CONFIGURED')
        result=inspect_pcapng(Path(extra[0]),server_ports=cfg.capture.server_ports,observer=observer)
        return {'operation':'capture','receipt':result.to_dict(),
                'live_ready':False,'live_status':'NOT_CERTIFIED'}
    if command=='protocol-demo':
        if extra: raise RuntimeError('PROTOCOL_DEMO_TAKES_NO_ARGUMENTS')
        from anka_protocol.api import synthetic_wire_demo
        return synthetic_wire_demo(root=ROOT,observer=observer)
    if command=='protocol-audit':
        if len(extra)!=2:raise RuntimeError('PROTOCOL_AUDIT_REQUIRES_PATH_AND_EXACT_BUILD')
        from anka_app.protocol_offline import inspect_protocol_pcapng
        cfg=load_user_config(ROOT/'config/user.json')
        if not cfg.capture.server_ports:raise RuntimeError('CAPTURE_PORTS_NOT_CONFIGURED')
        return inspect_protocol_pcapng(Path(extra[0]),root=ROOT,ports=cfg.capture.server_ports,build=extra[1],observer=observer)
    if command=='semantic-demo':
        if extra:raise RuntimeError('SEMANTIC_DEMO_TAKES_NO_ARGUMENTS')
        from anka_app.semantic_offline import synthetic_semantic_demo
        return synthetic_semantic_demo(observer=observer)
    if command=='semantic-audit':
        if len(extra)!=2:raise RuntimeError('SEMANTIC_AUDIT_REQUIRES_PATH_AND_EXACT_BUILD')
        from anka_app.semantic_offline import inspect_semantic_pcapng
        cfg=load_user_config(ROOT/'config/user.json')
        if not cfg.capture.server_ports:raise RuntimeError('CAPTURE_PORTS_NOT_CONFIGURED')
        return inspect_semantic_pcapng(Path(extra[0]),root=ROOT,ports=cfg.capture.server_ports,build=extra[1],observer=observer)
    if command=='protocol-qualify':
        if len(extra)>1:raise RuntimeError('PROTOCOL_QUALIFY_ACCEPTS_OPTIONAL_BUILD')
        from anka_app.protocol_qualification import qualify_historical
        return qualify_historical(root=ROOT, requested_build=extra[0] if extra else 'Dofus 3.7.10.10',observer=observer)
    if command=='state-demo':
        if extra:raise RuntimeError('STATE_DEMO_TAKES_NO_ARGUMENTS')
        from anka_app.state_offline import synthetic_state_demo
        return synthetic_state_demo(observer=observer)
    if command=='state-audit':
        if len(extra)!=1:raise RuntimeError('STATE_AUDIT_REQUIRES_ONE_DATABASE_PATH')
        from anka_app.state_offline import audit_state_db
        return audit_state_db(Path(extra[0]),observer=observer)
    if command=='quality-demo':
        if extra:raise RuntimeError('QUALITY_DEMO_TAKES_NO_ARGUMENTS')
        from anka_app.quality_offline import quality_demo
        return quality_demo(observer=observer)
    if command=='quality-audit':
        if len(extra)!=3:raise RuntimeError('QUALITY_AUDIT_REQUIRES_DB_SESSION_ACTOR')
        from anka_app.quality_offline import quality_audit
        try:actor=int(extra[2])
        except ValueError:raise RuntimeError('QUALITY_AUDIT_ACTOR_INVALID')
        return quality_audit(Path(extra[0]),extra[1],actor,observer=observer)
    if command=='fight-demo':
        if extra:raise RuntimeError('FIGHT_DEMO_TAKES_NO_ARGUMENTS')
        from anka_app.fight_offline import fight_demo
        return fight_demo(observer=observer)
    if command=='fight-audit':
        if len(extra)<2:raise RuntimeError('FIGHT_AUDIT_REQUIRES_DB_AND_ACCOUNT_SCOPES')
        from anka_app.fight_offline import fight_audit,parse_expectations
        return fight_audit(Path(extra[0]),parse_expectations(extra[1:]),observer=observer)
    if command=='decision-audit':
        if len(extra)!=10:raise RuntimeError('DECISION_AUDIT_REQUIRES_DB_AND_9_SCOPE_FIELDS')
        from anka_app.decision_offline import decision_audit,parse_decision_probe
        return decision_audit(Path(extra[0]),parse_decision_probe(extra[1:]),root=ROOT,observer=observer)
    if command=='decision-demo':
        if extra:raise RuntimeError('DECISION_DEMO_TAKES_NO_ARGUMENTS')
        from anka_app.decision_offline import decision_demo
        return decision_demo(root=ROOT,observer=observer)
    if command=='execution-demo':
        if len(extra)>1:raise RuntimeError('EXECUTION_DEMO_ACCEPTS_OPTIONAL_SCENARIO')
        from anka_app.execution_offline import execution_demo
        return execution_demo(observer=observer,scenario=extra[0] if extra else 'uncertain-crash')
    if command=='execution-sim-demo':
        from anka_app.execution_simulation import execution_sim_demo
        return execution_sim_demo(observer=observer,scenario=extra[0] if extra else 'no-confirmation')
    if command=='execution-audit':
        if len(extra)!=1:raise RuntimeError('EXECUTION_AUDIT_REQUIRES_DB_PATH')
        from anka_app.execution_offline import execution_audit
        return execution_audit(Path(extra[0]),observer=observer)
    if command=='coordination-demo':
        if len(extra)>1:raise RuntimeError('COORDINATION_DEMO_ACCEPTS_OPTIONAL_SCENARIO')
        from anka_app.coordination_offline import coordination_demo
        return coordination_demo(observer=observer,scenario=extra[0] if extra else 'handoff')
    if command=='sequence-demo':
        if extra:raise RuntimeError('SEQUENCE_DEMO_TAKES_NO_ARGUMENTS')
        from anka_app.sequence_offline import sequence_demo
        return sequence_demo(root=ROOT,observer=observer)
    if command=='scoring-demo':
        if len(extra)>1:raise RuntimeError('SCORING_DEMO_ACCEPTS_OPTIONAL_RESEARCH_POLICY')
        from anka_app.scoring_offline import scoring_demo
        return scoring_demo(root=ROOT,observer=observer,
                            policy=extra[0] if extra else 'CRA_DAMAGE_RESEARCH')
    if command=='tactical-demo':
        if extra:raise RuntimeError('TACTICAL_DEMO_TAKES_NO_ARGUMENTS')
        from anka_app.tactical_offline import tactical_demo
        return tactical_demo(root=ROOT,observer=observer)
    if command=='map-demo':
        if extra:raise RuntimeError('MAP_DEMO_TAKES_NO_ARGUMENTS')
        from anka_app.map_research_offline import map_demo
        return map_demo(root=ROOT,observer=observer)
    if command=='capture-live':
        # Independent diagnostic sample, not a session-control command.
        if extra:raise RuntimeError('CAPTURE_LIVE_TAKES_NO_ARGUMENTS')
        cfg=load_user_config(ROOT/'config/user.json')
        if not cfg.capture.server_ports:raise RuntimeError('CAPTURE_PORTS_NOT_CONFIGURED')
        if cfg.capture.interface is None:raise RuntimeError('CAPTURE_INTERFACE_NOT_CONFIGURED')
        if sys.platform!='win32':raise RuntimeError('CAPTURE_LIVE_REQUIRES_WINDOWS')
        from anka_capture.windows_live import WindowsLiveCapture, capture_bounded_sample
        from anka_capture.windows_flows import WindowsTcpOwnership,correlate_flows
        from anka_client.win32_inventory import NativeWindowsInventory
        # Account/window mapping is a conservative time-bounded diagnostic hint;
        # never allow this read-only command to change execution authority.
        inventory=NativeWindowsInventory(tuple(p.name for p in cfg.players))
        before=inventory.scan()
        recorder=None
        if cfg.capture.save_raw_evidence:
            from anka_capture.evidence_recording import ConsentedPcapngRecorder
            recorder=ConsentedPcapngRecorder(ROOT/'runtime/evidence',server_ports=cfg.capture.server_ports)
        live=WindowsLiveCapture(interface=cfg.capture.interface,server_ports=cfg.capture.server_ports,
                                evidence_recorder=recorder)
        result=capture_bounded_sample(interface=cfg.capture.interface,server_ports=cfg.capture.server_ports,
                       duration_seconds=cfg.capture.duration_seconds, observer=observer,source=live)
        after=inventory.scan()
        try:
            endpoints=WindowsTcpOwnership().snapshot()
            if before.errors or after.errors:raise RuntimeError('WINDOW_SNAPSHOT_UNRELIABLE')
            old={(w.pid,w.process_created_100ns):w for w in before.windows}
            new={(w.pid,w.process_created_100ns):w for w in after.windows}
            stable=old.keys() & new.keys()
            pid_to_gen={pid:str(created) for pid,created in stable}
            link=correlate_flows(live.flow_keys_for_attribution(),endpoints,pid_to_gen)
            result['flow_attribution']= {'status':'NOT_ATTESTED','counts':link['counts']}
        except Exception as exc:
            result['flow_attribution']={'status':'UNAVAILABLE','reason_code':type(exc).__name__.upper()}
        result['operation']='capture-live'
        return result
    if command=='clients':
        config=load_user_config(ROOT/'config/user.json')
        result=inspect_local_clients(tuple(p.name for p in config.players))
        observer.record('client.inspection_completed',boundary='client.read_only_inspection',
            payload={'status':result['status'],'observed_windows':result['observed_windows'],
                     'account_states':[b['state'] for b in result['bindings']],
                     'reasons':[b['reason'] for b in result['bindings']],
                     'scan_errors':result['scan_errors'],'input_permitted':False})
        return {'operation':'clients',**result}
    if command=='start':
        # Q10/Q11 observe-only path. It deliberately performs no physical input.
        # Load the effective user config once and bind all observations to it.
        initial_release=_release_integrity_check(observer)
        config=load_user_config(ROOT/'config/user.json')
        _start_static_preflight(observer,config)
        _architecture_check(observer)
        _readiness_check(observer)
        # Preserve the exact setup-side prerequisite state in the start incident.
        # These are evidence records only; current host probes below remain authoritative.
        capture_setup=_capture_prereq_receipt(observer)
        bridge_setup=_bridge_setup_receipt(observer)
        host=_host_check(observer,config)
        if (host.get('platform')=='WINDOWS' and host.get('candidate_windows',0)>0
                and 'WINDOW_INVENTORY_INCOMPLETE' not in host.get('issues',())):
            observer.record('client.windows_candidate_accepted',boundary='client.host_observation',
                            owner_system='anka_client',physical_input_state='NOT_SENT',payload={'candidate_windows':host['candidate_windows'],
                            'identity_certified':False,'physical_input_permitted':False})
        from anka_app.ingress_readiness import probe_start_ingress
        from anka_app.startup_acceptance import blockers_for,boundary_for
        ingress=probe_start_ingress(config,host,observer=observer)
        observer.register_snapshot('capture_ingress',ingress)
        observer.record('capture.ingress_observation_completed',boundary='capture.observe_only',
                        owner_system='anka_capture',
                        severity='WARNING' if ingress.get('status')=='FAILED' else 'INFO',
                        failure_code='START_CAPTURE_SAMPLE_FAILED' if ingress.get('status')=='FAILED' else None,
                        payload={'status':ingress.get('status'),'reason':ingress.get('reason'),
                                 'capture_attempted':ingress.get('capture_attempted',False),
                                 'physical_input_permitted':False})
        if ingress.get('status')=='CAPTURED_UNCERTIFIED':
            observer.record('capture.ingress_evidence_collected',boundary='capture.observe_only',
                            owner_system='anka_capture',physical_input_state='NOT_SENT',payload={'status':'UNCERTIFIED',
                            'physical_input_permitted':False})
        if ingress.get('status')=='CAPTURED_UNCERTIFIED' and isinstance(ingress.get('receipt',{}).get('protocol_wire'),dict):
            wire=ingress['receipt']['protocol_wire']
            observer.record('protocol.current_build_observation_completed',
                            boundary='protocol.current_build_observation',owner_system='anka_protocol',
                            physical_input_state='NOT_SENT',payload={'status':wire.get('status'),'requested_build':wire.get('requested_build'),
                                     'adapter_build':wire.get('adapter_build'),
                                     'selected_segments':wire.get('selected_segments',0),
                                     'framed_messages':wire.get('framed_messages',0),
                                     'unknown_messages':wire.get('unknown_messages',0),
                                     'current_build_certified':False,'physical_input_permitted':False})
        # Revalidate mutable and immutable identities after the bounded host/capture
        # observation. Evidence from two different configs/releases must never be
        # combined into one acceptance decision.
        _revalidate_start_identity(observer,config,initial_release)
        concrete_blockers=blockers_for(host,ingress,capture_setup=capture_setup,bridge_setup=bridge_setup)
        code=concrete_blockers[0]
        acceptance={'status':'BLOCKED','first_blocker':code,'concrete_blockers':list(concrete_blockers),
                    'physical_input_enabled':False,'live_ready':False}
        observer.register_snapshot('startup_acceptance',acceptance)
        observer.record('start.observe_only_blocked',severity='ERROR',boundary=boundary_for(code),
                        owner_system='anka_app',physical_input_state='NOT_SENT',failure_code=code,payload=acceptance)
        raise RuntimeError(code)
    if command=='stop':
        return {'operation':'stop','live_process':'NOT_RUNNING_IN_OFFLINE_MILESTONE','stopped_input':False}
    if command=='doctor':
        _preflight(observer)
        previous=_prior_runs(ROOT/'runtime',observer.run_id)
        unclean=[name for name,obj in previous if obj.get('state') not in ('CLOSED','BLOCKED','FAILED')]
        observer.record('doctor.previous_runs_scanned',boundary='operator.doctor_prior_runs',payload={'previous_runs':len(previous),'unclean_count':len(unclean)})
        return {'operation':'doctor','unclean_prior_runs':unclean,'live_status':'NOT_CERTIFIED','capture_offline_available':True,'capture_live_available':False,'capture_live_backend_installed':sys.platform=='win32' and importlib.util.find_spec('scapy') is not None,'observer_status':'PASS' if observer.available else 'UNAVAILABLE'}
    if command=='debug':
        if extra and extra[0]=='--verify':
            if len(extra)!=2:raise RuntimeError('DEBUG_VERIFY_REQUIRES_PATH')
            return {'operation':'debug_verify',**verify_incident(Path(extra[1]))}
        artifact=observer.export_incident('MANUAL_DIAGNOSTIC_EXPORT',boundary='operator.debug',detail='Manually requested diagnostic export; no live failure was demonstrated.')
        return {'operation':'debug','bundle':str(artifact),'live_status':'NOT_CERTIFIED'}
    if command=='replay':
        # Deliberately synthetic incident used for validating P1 diagnostics; not a game replay.
        observer.record('coordination.ready_observed',boundary='coordination.synthetic_ready',payload={'account_role':'CRA','ready':True})
        observer.record('coordination.ready_observed',boundary='coordination.synthetic_ready',payload={'account_role':'ENU','ready':True})
        observer.record('coordination.turn_owner_wait',severity='ERROR',boundary='coordination.ready_to_first_turn',
           failure_code='TURN_OWNER_UNPROVEN',payload={'timed_out':True,'physical_input_sent':False})
        artifact=observer.export_incident('TURN_OWNER_UNPROVEN',boundary='coordination.ready_to_first_turn',
             detail='Synthetic fixture: both Ready reported, but authoritative turn-owner evidence is absent.')
        return {'operation':'replay','status':'SYNTHETIC_INCIDENT_ONLY','bundle':str(artifact),'physical_input_sent':False}
    if command=='verify':
        # Developer-only: bounded process-isolated shards, not a third BAT command.
        _preflight(observer)
        from anka_app.verification_runner import verify_isolated, VerificationRejected
        def started(shard, total, modules):
            observer.record('verification.shard_started', boundary='verification.unittest',
                            payload={'shard': shard, 'total_shards': total,
                                     'modules': list(modules)})
        def completed(shard, total, passed, files):
            observer.record('verification.shard_passed', boundary='verification.unittest',
                            payload={'shard': shard, 'total_shards': total,
                                     'tests_passed': passed, 'test_files': files})
        try:
            summary = verify_isolated(ROOT, module_isolation=True,
                                      checkpoint_path=ROOT/'runtime'/'verification'/'module_checkpoint.json',
                                      notify=completed, notify_start=started)
        except VerificationRejected as exc:
            failure = 'verification.suite_timed_out' if exc.code == 'OFFLINE_TEST_SUITE_TIMEOUT' else 'verification.suite_failed'
            observer.record(failure, severity='ERROR', boundary='verification.unittest',
                            failure_code=exc.code, payload={'shard': exc.shard,
                            'test_modules': list(exc.modules), 'completed_test_files': exc.completed,
                            'last_test_output': exc.output[-1200:]})
            raise RuntimeError(exc.code) from exc
        observer.record('verification.suite_completed', boundary='verification.unittest',
                        payload=summary.to_dict())
        return {'operation':'verify', **summary.to_dict()}
    raise RuntimeError('UNKNOWN_COMMAND')


def main(argv:list[str]|None=None)->int:
    args=list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in COMMANDS:
        print('Usage: python -m anka_app.cli {setup|check|start|stop|doctor|debug|verify|replay|clients|capture|capture-demo|capture-live|protocol-demo|protocol-audit|semantic-demo|semantic-audit|state-demo|state-audit|quality-demo|quality-audit|protocol-qualify|fight-demo|fight-audit|decision-demo|decision-audit|map-demo|tactical-demo|scoring-demo|sequence-demo|execution-demo|execution-audit|execution-sim-demo} [arguments]')
        return 2
    command,*extra=args
    # Creating an observer itself must be failure-tolerant.
    try:
        observer=LocalDiagnostics(ROOT/'runtime')
        observer.record('bootstrap.command_started',boundary='bootstrap.command',payload={'command':command})
    except Exception as exc:
        try:print('EMERGENCY_MARKER='+str(emergency_marker(ROOT,stage='observer_create',code=type(exc).__name__)))
        except OSError:pass
        return 70
    print('ANKA_INVOCATION='+observer.invocation_id)
    print('ANKA_RUN='+observer.run_id)
    if not observer.available:
        # Observability persistence is deliberately passive.  A read-only/run
        # journal path failure must not become gameplay/startup authority: the
        # in-memory flight recorder still retains bounded evidence and incident
        # export can fall back to the OS temp directory.  Surface the degradation
        # loudly, but let Canonical/Execution/Coordination own safety decisions.
        try:print('EMERGENCY_MARKER='+str(emergency_marker(ROOT,stage='observer_unavailable',code='OBSERVER_UNAVAILABLE')))
        except OSError:pass
        observer.record('observability.storage_unavailable',severity='WARNING',
                        owner_system='anka_observability',boundary='observability.persistence',
                        failure_code='RUN_STORAGE_UNAVAILABLE',evidence_class='MISSING',
                        payload={'persistent_storage_available':False,'authority_granted':False})
        print('ANKA_OBSERVABILITY=PARTIAL')
    start_authority=None
    try:
        if command=='start':
            from anka_app.run_authority import acquire_start_authority
            start_authority=acquire_start_authority(require_windows=False)
            # Recover only durable diagnostic evidence from previous unclean runs.
            # This is bounded, best-effort and never grants gameplay/input authority.
            try:
                from anka_observability.recovery import recover_unclean_runs
                recovered=recover_unclean_runs(ROOT/'runtime',current_run_id=observer.run_id,max_runs=4)
                for recovered_path in recovered:
                    print('ANKA_RECOVERED_BUNDLE='+str(recovered_path))
                if recovered:
                    observer.record('observability.unclean_runs_recovered',owner_system='anka_observability',
                        boundary='observability.unclean_recovery',severity='WARNING',
                        payload={'recovered_count':len(recovered),'authority_granted':False})
            except Exception as recovery_exc:
                observer.note_error('UNCLEAN_RECOVERY_FAILED:'+type(recovery_exc).__name__)
        result=_command(command,observer,extra)
        # A successfully executed diagnostic can still discover an inconsistency.
        # Expose that distinction to batch files/CI instead of returning success
        # merely because an audit ran without raising an exception.
        audit_conflict=((command=='fight-audit' and result.get('status')=='BLOCKED_INCONSISTENT')
                        or (command=='decision-audit' and result.get('status','').startswith('BLOCKED'))
                        or (command=='map-demo' and result.get('status','').startswith('BLOCKED'))
                        or (command=='coordination-demo' and result.get('status')=='QUARANTINED')
                        or (command=='execution-audit' and result.get('status')=='BLOCKED_UNCERTAIN'))
        observer.record('bootstrap.command_finished',boundary='bootstrap.command',
                        payload={'command':command,'result':'EVIDENCE_CONFLICT' if audit_conflict else 'PASS'})
        observer.finish('BLOCKED' if audit_conflict else 'CLOSED')
        print('ANKA_STATUS='+result.get('status','PASS'))
        print('ANKA_RESULT='+json.dumps(result,sort_keys=True,default=str))
        print('ANKA_EVIDENCE='+str(observer.folder))
        return 10 if audit_conflict else 0
    except KeyboardInterrupt:
        boundary='startup.operator_interrupt' if command=='start' else 'bootstrap.operator_interrupt'
        try:
            observer.record('bootstrap.command_interrupted',severity='WARNING',boundary=boundary,
                            failure_code='USER_INTERRUPTED',
                            physical_input_state='NOT_SENT' if command=='start' else None,
                            payload={'command':command,'physical_input_sent':False})
            trace_spec=None
            if command=='start':
                from anka_app.startup_acceptance import STARTUP_TRACE
                trace_spec=STARTUP_TRACE
            bundle=observer.export_incident('USER_INTERRUPTED',boundary=boundary,
                detail='Operator interrupted the command; cleanup completed and no retry is implied.',
                trace_spec=trace_spec,control_state='INTERRUPTED')
            print('ANKA_BUNDLE='+str(bundle))
        except Exception as export_exc:
            print('ANKA_BUNDLE=UNAVAILABLE_'+type(export_exc).__name__)
        observer.finish('INTERRUPTED')
        print('ANKA_STATUS=INTERRUPTED')
        print('ANKA_FAILURE=USER_INTERRUPTED')
        print('ANKA_EVIDENCE='+str(observer.folder))
        return 130
    except Exception as exc:
        code=str(exc) if (isinstance(exc,(ConfigurationError,RuntimeError,CaptureRejected,ExecutionLedgerRejected,ExecutionLedgerIntegrityError,ExecutionTransitionRejected,IntakeRejected)) or
            (isinstance(exc,ValueError) and str(exc).startswith('P15_'))) else type(exc).__name__.upper()
        safe_code=''.join(c if c.isalnum() or c=='_' else '_' for c in code.upper())[:80]
        if not safe_code or not safe_code[0].isalpha(): safe_code='UNKNOWN_FAILURE'
        if command=='start':
            from anka_app.startup_acceptance import boundary_for
            boundary=boundary_for(safe_code)
        else:
            boundary=('configuration.validation' if isinstance(exc,ConfigurationError) else
                  'assets.integrity' if code=='ASSET_INTEGRITY_FAILED' else 'protocol.evidence_intake' if isinstance(exc,IntakeRejected) else 'capture.offline_replay' if command in ('capture','capture-demo') else 'capture.live_read_only' if command=='capture-live' else 'canonical.synthetic_replay' if command.startswith(('state-','quality-','fight-','decision-','map-','tactical-','scoring-','sequence-','coordination-','execution-')) else 'protocol.semantic_research' if command.startswith('semantic-') else 'protocol.read_only_audit' if command.startswith('protocol-') else 'bootstrap.'+command)
        observer.record('bootstrap.command_failed',severity='ERROR',boundary=boundary,failure_code=safe_code,
                        payload={'exception_type':type(exc).__name__, 'command':command, 'failure_detail':code,
                                 'stack_frames':safe_exception_frames(exc,ROOT)})
        try:
            trace_spec=None
            if command=='start':
                from anka_app.startup_acceptance import STARTUP_TRACE
                trace_spec=STARTUP_TRACE
            bundle=observer.export_incident(safe_code,boundary=boundary,
                detail='Blocked at '+boundary+' with '+safe_code+'; see snapshots, timeline, evidence gaps, and next verification.',
                trace_spec=trace_spec,control_state='BLOCKED')
            print('ANKA_BUNDLE='+str(bundle))
        except Exception as export_exc:
            print('ANKA_BUNDLE=UNAVAILABLE_'+type(export_exc).__name__)
            try:print('EMERGENCY_MARKER='+str(emergency_marker(ROOT,stage=boundary,code=safe_code)))
            except OSError:pass
        observer.finish('BLOCKED')
        print('ANKA_STATUS=BLOCKED')
        print('ANKA_FAILURE='+safe_code)
        print('ANKA_EVIDENCE='+str(observer.folder))
        return 40
    finally:
        if start_authority is not None:
            start_authority.close()

if __name__=='__main__':raise SystemExit(main())
