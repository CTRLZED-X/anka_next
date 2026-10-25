"""P20 deterministic, *synthetic-only* cross-system regression.

Composition belongs in anka_app; the independent domains do not import one
another. The separate fake execution fixture is NEVER constructed from the
Decision research report. This is not a live runtime or an authority grant.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from anka_contracts.state import OfflineStateEvent
from anka_contracts.coordination_flow import PartyMember, PartyFixtureEvent
from anka_contracts.decision import CastProbe
from anka_contracts.execution_flow import OfflineActionIntent, OfflineOutcomeEvidence
from anka_contracts.execution_simulation import OfflineWindowObservation
from anka_canonical.journal import SQLiteFixtureJournal
from anka_live_state.reducer import apply_offline_event
from anka_coordination.party_lifecycle import replay_party
from anka_workflow.mission_research import evaluate_mission
from anka_decision.probe import inspect_cast_probe
from anka_execution.ledger import OfflineExecutionLedger
from anka_execution.fake_input import OfflineFakeInputDriver, OfflineWindowFeed
from anka_execution.offline_dispatch import OfflineDispatchCoordinator
from anka_app.decision_offline import reference_kernel
from anka_contracts.causal_evidence import PartySourceLink
from anka_app.source_link_audit import audit_party_source_links


CASES = frozenset({
    'handoff', 'missing-end-confirmation', 'conflicting-owner',
    'stale-enu-state', 'wrong-fight', 'focus-lost', 'missing-outcome',
    'driver-raises-after', 'duplicate-dispatch',
    'source-missing', 'source-reused', 'source-orphan',
})


def _fixture_stream(account: str, actor: int, *, turn: bool, ended: bool = False,
                    fight: str = 'fight20') -> tuple[OfflineStateEvent, ...]:
    steps = [('FIGHT_STARTED', {}), ('ACTOR_SEEN', {'actor_id': actor}),
             ('ACTOR_HP_SET', {'actor_id': actor, 'value': 2800, 'maximum': 3200}),
             ('ACTOR_RESOURCE_SET', {'actor_id': actor, 'resource': 'AP', 'value': 11}),
             ('ACTOR_RESOURCE_SET', {'actor_id': actor, 'resource': 'MP', 'value': 5}),
             ('ACTOR_POSITION_SET', {'actor_id': actor, 'value': 215 if account == 'cra' else 220}),
             ('ACTOR_COOLDOWNS_SET', {'actor_id': actor, 'cooldowns': ((32435, 0),)})]
    if turn:
        steps.append(('TURN_STARTED', {'actor_id': actor}))
    if ended:
        steps.append(('TURN_ENDED', {'actor_id': actor}))
    return tuple(OfflineStateEvent(f'p20-{account}-{n}', f'{account}-session', account, 1,
                    fight, n, kind, **data) for n, (kind, data) in enumerate(steps, 1))


def _party_events(case: str) -> tuple[PartyFixtureEvent, ...]:
    raw = [
        (0, 'READY', 'cra', 777, None), (1, 'READY', 'enu', 888, None),
        (2, 'FIGHT_STARTED', None, None, 'fight20'),
        (3, 'TURN_STARTED', 'cra', 777, 'fight20'),
        (4, 'END_TURN_INTENDED', 'cra', 777, 'fight20'),
    ]
    if case != 'missing-end-confirmation':
        raw.append((5, 'TURN_ENDED', 'cra', 777, 'fight20'))
    raw.append((6, 'TURN_STARTED', 'enu', 888, 'fight20'))
    return tuple(PartyFixtureEvent(n, tick, kind, f'p20-party-{n}', account,
                1 if account is not None else None, actor, fight)
                 for n, (tick, kind, account, actor, fight) in enumerate(raw, 1))


def _fixture_source_links(party_events: tuple[PartyFixtureEvent, ...]) -> tuple[PartySourceLink, ...]:
    """Explicit synthetic source claims; the audit independently verifies each."""
    links = []
    for item in party_events:
        if item.kind == 'FIGHT_STARTED':
            for account in ('cra', 'enu'):
                links.append(PartySourceLink(item.event_id, f'{account}-session', f'p20-{account}-1'))
        elif item.kind in ('TURN_STARTED', 'TURN_ENDED'):
            sequence = 9 if item.kind == 'TURN_ENDED' else 8
            links.append(PartySourceLink(item.event_id, f'{item.account_id}-session',
                                         f'p20-{item.account_id}-{sequence}'))
    return tuple(links)


def _scope_failure(snapshots: dict[str, dict | None], owner: int | None,
                   fight_id: str | None) -> tuple[str, ...]:
    issues: list[str] = []
    for account, actor in (('cra', 777), ('enu', 888)):
        snap = snapshots.get(account)
        if not isinstance(snap, dict):
            issues.append(f'P20_{account.upper()}_STATE_MISSING')
            continue
        if (snap.get('session_id') != f'{account}-session' or snap.get('account_id') != account
                or snap.get('account_generation') != 1 or snap.get('fight_id') != fight_id
                or snap.get('authority') != 'SYNTHETIC_FIXTURE_ONLY'
                or snap.get('actionable') is not False):
            issues.append(f'P20_{account.upper()}_STATE_SCOPE_MISMATCH')
        if not isinstance(snap.get('actors'), dict) or str(actor) not in snap['actors']:
            issues.append(f'P20_{account.upper()}_ACTOR_UNPROVEN')
    cra = snapshots.get('cra')
    enu = snapshots.get('enu')
    if isinstance(cra, dict) and cra.get('turn_owner_id') is not None:
        issues.append('P20_CRA_TURN_STILL_ACTIVE')
    if not isinstance(enu, dict) or enu.get('turn_owner_id') != owner or owner != 888:
        issues.append('P20_ENU_TURN_NOT_RECONCILED')
    if isinstance(enu, dict) and enu.get('revision', 0) < 8:
        issues.append('P20_ENU_STATE_REVISION_STALE')
    return tuple(issues)


def _run(root: Path, folder: Path, case: str) -> dict:
    history = folder / 'fixture_state.sqlite3'
    exec_db = folder / 'fixture_actions.sqlite3'
    cra_events = _fixture_stream('cra', 777, turn=True,
                                  ended=case != 'conflicting-owner')
    enu_events = _fixture_stream('enu', 888, turn=case != 'stale-enu-state',
                                  fight='wrong-fight' if case == 'wrong-fight' else 'fight20')
    with SQLiteFixtureJournal(history, reducer=apply_offline_event) as journal:
        for event in (*cra_events, *enu_events):
            journal.append_fixture(event)
        evidence = journal.audited_evidence(('cra-session', 'enu-session'))
    views = evidence['views']
    snapshots = {'cra': views['cra-session']['snapshot'],
                 'enu': views['enu-session']['snapshot']}
    members = (PartyMember('cra', 1, 777, 'leader'), PartyMember('enu', 1, 888, 'follower'))
    party_events = _party_events(case)
    party = replay_party(members, party_events)
    # A turn-active fight is not a won fight; workflow must preserve uncertainty.
    mission = evaluate_mission((party,), ())
    failures: list[str] = list(party.reasons)
    if party.status != 'TURN_ACTIVE':
        failures.append('P20_COORDINATION_NOT_ACTIVE')
    failures.extend(_scope_failure(snapshots, party.turn_owner, party.fight_id))
    trace = ['canonical.audit', 'live_state.replay', 'coordination.replay', 'workflow.outcome_accounting']
    source_audit = None
    if not failures:
        links = _fixture_source_links(party_events)
        # Deliberately damaged provenance in permanent synthetic regressions.
        if case == 'source-missing':
            links = tuple(link for link in links if link.source_event_id != 'p20-enu-8')
        elif case == 'source-reused':
            links = (*links, links[-1])
        elif case == 'source-orphan':
            links = (*links[:-1], PartySourceLink(links[-1].party_event_id,
                                                 'enu-session', 'p20-enu-999'))
        source_audit = audit_party_source_links(members=members, party_events=party_events,
            journal_evidence=evidence, links=links)
        trace.append('integration.source_link_audit')
        failures.extend(source_audit.reasons)
    if mission.confirmed_synthetic_wins != 0 or mission.synthetic_losses != 0:
        failures.append('P20_WORKFLOW_INVENTED_OUTCOME')
    decision = None
    dispatch = None
    actual_attempts = 0
    action_status = None
    if not failures:
        # Research-only probe: never becomes an executable approval.
        probe = CastProbe('enu-session', 'enu', 1, 'fight20', 8, 888, 32435, 3, 229)
        decision = inspect_cast_probe(snapshots['enu'], probe, kernel=reference_kernel(root))
        trace.append('decision.kernel_research')
        if decision.status != 'RESEARCH_ONLY' or decision.actionable or decision.authoritative:
            failures.append('P20_DECISION_RESEARCH_BOUNDARY_FAILED')
    if not failures:
        # This is an explicitly independent synthetic fixture, NOT a conversion
        # from CastProbeReport to a live action. The fake-only driver enforces it.
        intent = OfflineActionIntent('p20-fixture-action', 'fixture-end-turn',
            'enu-session', 'enu', 'sim-window-enu', 1, 'fight20', 'turn-2',
            888, snapshots['enu']['revision'], 'END_TURN')
        windows = OfflineWindowObservation('enu', 'sim-window-enu', 1, True, True, True)
        second = windows
        if case == 'focus-lost':
            second = OfflineWindowObservation('enu', 'sim-window-enu', 1, True, False, True)
        fake = OfflineFakeInputDriver('raise-after' if case == 'driver-raises-after'
                                      else 'simulated-input')
        ledger = OfflineExecutionLedger(exec_db)
        fixture_outcome = None if case == 'missing-outcome' else OfflineOutcomeEvidence(
            'p20-proof-1', intent.action_id, intent.session_id, intent.account_id,
            intent.client_id, intent.window_generation, intent.fight_id, intent.turn_id,
            intent.actor_id, intent.state_revision + 1, 'ACCEPTED')
        dispatch = OfflineDispatchCoordinator(ledger, fake, OfflineWindowFeed(windows, second))\
            .run(intent, evidence=fixture_outcome)
        actual_attempts = fake.attempt_count
        action_status = ledger.audit(intent.action_id).status
        trace.extend(('execution.fake_dispatch', 'execution.ledger_audit'))
        if case == 'duplicate-dispatch':
            try:
                OfflineDispatchCoordinator(ledger, OfflineFakeInputDriver(),
                    OfflineWindowFeed(windows, windows)).run(intent)
            except ValueError:
                trace.append('execution.duplicate_rejected')
            else:
                failures.append('P20_DUPLICATE_DISPATCH_ACCEPTED')
        if action_status != 'CONFIRMED':
            failures.append(dispatch.reason if dispatch is not None else 'P20_DISPATCH_UNCERTAIN')
            failures.append('P20_DISPATCH_UNCERTAIN')
        if case == 'focus-lost' and actual_attempts != 0:
            failures.append('P20_FOCUS_LOSS_SENT_INPUT')
        if case == 'driver-raises-after' and actual_attempts != 1:
            failures.append('P20_FAKE_ATTEMPT_COUNT_WRONG')
    if actual_attempts > 1:
        failures.append('P20_MULTIPLE_FAKE_ATTEMPTS')
    if case == 'missing-end-confirmation' and actual_attempts:
        failures.append('P20_DISPATCH_WHILE_HANDOFF_UNPROVEN')
    return {'scenario': case, 'status': 'BLOCKED_SYNTHETIC' if failures else 'SYNTHETIC_REPLAY_PASS',
            'first_failure': failures[0] if failures else None, 'reasons': list(dict.fromkeys(failures)),
            'boundaries': trace, 'state_audit': evidence['audit']['status'],
            'state_revisions': {a: v['revision'] for a, v in snapshots.items()},
            'party': {'status': party.status, 'turn_owner': party.turn_owner,
                      'first_failed_sequence': party.first_failed_sequence},
            'workflow': mission.to_dict(),
            'source_link_audit': source_audit.to_dict() if source_audit else None,
            'decision': decision.to_dict() if decision else None,
            'execution': dispatch.to_dict() if dispatch else None,
            'ledger_status': action_status, 'fake_attempts': actual_attempts,
            'synthetic_only': True, 'actionable': False, 'authoritative': False,
            'live_ready': False, 'physical_input_sent': False}


def run_integrated_fixture(root: Path, *, scenario: str = 'handoff',
                           observer=None) -> dict:
    """Never accepts external drivers, raw events, or authority flags."""
    if scenario not in CASES:
        raise ValueError('P20_UNKNOWN_SCENARIO')
    with TemporaryDirectory(prefix='anka-p20-') as tmp:
        result = _run(Path(root), Path(tmp), scenario)
    if observer is not None:
        try:
            observer.record('integration.p20_replay_completed',
                boundary='integration.synthetic_only',
                severity='ERROR' if result['first_failure'] else 'INFO',
                payload={'scenario': scenario, 'status': result['status'],
                         'first_failure': result['first_failure'],
                         'boundaries': result['boundaries'],
                         'fake_attempts': result['fake_attempts'],
                         'physical_input_sent': False})
            if result['first_failure']:
                observer.export_incident(result['first_failure'],
                    boundary='integration.synthetic_only',
                    detail='Cross-system synthetic regression; no real game input was attempted.')
        except Exception:
            pass  # Observer cannot cause fake-only integration tests to send input.
    return result
