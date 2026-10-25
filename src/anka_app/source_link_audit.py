"""P22 exact source-provenance reconciliation for synthetic fight events.

This composition-layer audit joins two independent systems through contracts;
no source package imports another system's internal code. Journal evidence must
already be hash/replay audited inside one SQLite snapshot. Links never prove
network attribution or global cross-account event ordering.
"""
from __future__ import annotations
from collections import defaultdict
from anka_contracts.causal_evidence import PartySourceLink, PartySourceAudit
from anka_contracts.coordination_flow import PartyFixtureEvent, PartyMember
from anka_contracts.state import OfflineStateEvent


def audit_party_source_links(*, members: tuple[PartyMember, ...],
                             party_events: tuple[PartyFixtureEvent, ...],
                             journal_evidence: dict,
                             links: tuple[PartySourceLink, ...]) -> PartySourceAudit:
    if (type(members) is not tuple or not members
            or any(not isinstance(x, PartyMember) for x in members)
            or len({m.account_id for m in members}) != len(members)):
        raise ValueError('P22_MEMBERS_INVALID')
    if (type(party_events) is not tuple or any(not isinstance(x, PartyFixtureEvent) for x in party_events)
            or type(links) is not tuple or any(not isinstance(x, PartySourceLink) for x in links)):
        raise ValueError('P22_LINK_INPUT_INVALID')
    if not isinstance(journal_evidence, dict) or journal_evidence.get('authority') != 'SYNTHETIC_FIXTURE_ONLY' or journal_evidence.get('actionable') is not False:
        return PartySourceAudit(('P22_UNVERIFIED_JOURNAL_EVIDENCE',), 0, 0)
    if journal_evidence.get('audit', {}).get('status') != 'PASS':
        return PartySourceAudit(('P22_JOURNAL_AUDIT_FAILED',), 0, 0)
    views = journal_evidence.get('views')
    if not isinstance(views, dict):
        return PartySourceAudit(('P22_JOURNAL_VIEWS_INVALID',), 0, 0)
    identities = {m.account_id: m for m in members}
    events = {}
    for session_id, view in views.items():
        if not isinstance(view, dict) or not isinstance(view.get('events'), tuple):
            return PartySourceAudit(('P22_JOURNAL_VIEW_INVALID',), 0, 0)
        for source in view['events']:
            if not isinstance(source, OfflineStateEvent) or source.session_id != session_id:
                return PartySourceAudit(('P22_JOURNAL_VIEW_INVALID',), 0, 0)
            key = (session_id, source.event_id)
            if key in events:
                return PartySourceAudit(('P22_DUPLICATE_JOURNAL_SOURCE',), 0, 0)
            events[key] = source
    parties = {p.event_id: p for p in party_events}
    if len(parties) != len(party_events):
        return PartySourceAudit(('P22_DUPLICATE_PARTY_EVENT',), 0, 0)
    grouped = defaultdict(list)
    used_sources = set()
    for link in links:
        if link.party_event_id not in parties:
            return PartySourceAudit(('P22_UNKNOWN_PARTY_REFERENCE',), len(links), len(grouped))
        party = parties[link.party_event_id]
        if party.kind not in ('FIGHT_STARTED', 'TURN_STARTED', 'TURN_ENDED'):
            return PartySourceAudit(('P22_UNSUPPORTED_LINK_KIND',), len(links), len(grouped))
        key = (link.source_session_id, link.source_event_id)
        if key in used_sources:
            return PartySourceAudit(('P22_SOURCE_REUSED',), len(links), len(grouped))
        used_sources.add(key)
        source = events.get(key)
        if source is None:
            return PartySourceAudit(('P22_SOURCE_NOT_IN_AUDITED_JOURNAL',), len(links), len(grouped))
        if source.kind != party.kind:
            return PartySourceAudit(('P22_SOURCE_KIND_MISMATCH',), len(links), len(grouped))
        if source.fight_id != party.fight_id:
            return PartySourceAudit(('P22_SOURCE_FIGHT_MISMATCH',), len(links), len(grouped))
        member = identities.get(source.account_id)
        if member is None or source.account_generation != member.generation:
            return PartySourceAudit(('P22_SOURCE_ACCOUNT_GENERATION_MISMATCH',), len(links), len(grouped))
        if party.account_id is not None and (source.account_id != party.account_id
                                               or source.actor_id != party.actor_id
                                               or source.account_generation != party.generation):
            return PartySourceAudit(('P22_SOURCE_ACTOR_MISMATCH',), len(links), len(grouped))
        if party.kind == 'FIGHT_STARTED' and source.actor_id is not None:
            return PartySourceAudit(('P22_FIGHT_SOURCE_INVALID',), len(links), len(grouped))
        grouped[party.event_id].append(source)
    linked = 0
    # Every ownership transition must have exactly one matching journal event.
    # Fight start must be observed once per account, never inferred from a
    # single participant's local observation.
    for party in party_events:
        if party.kind not in ('FIGHT_STARTED', 'TURN_STARTED', 'TURN_ENDED'):
            continue
        linked += 1
        sources = grouped.get(party.event_id, ())
        if party.kind == 'FIGHT_STARTED':
            if len(sources) != len(members) or {x.account_id for x in sources} != set(identities):
                return PartySourceAudit(('P22_FIGHT_START_SOURCES_MISSING',), len(links), linked)
        elif len(sources) != 1:
            return PartySourceAudit(('P22_TURN_SOURCE_MISSING_OR_DUPLICATED',), len(links), linked)
    # Relative ordering is provable ONLY within an account generation and
    # session. A cross-account total order would need an independent server
    # turn epoch or trustworthy shared clock, neither available in this fixture.
    last_seen = {}
    for party in party_events:
        for source in grouped.get(party.event_id, ()):  # account-local chronology
            key = (source.session_id, source.account_generation)
            if source.sequence <= last_seen.get(key, 0):
                return PartySourceAudit(('P22_SOURCE_ORDER_CONFLICT',), len(links), linked)
            last_seen[key] = source.sequence
    return PartySourceAudit((), len(links), linked)
