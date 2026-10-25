"""P30: hash-pinned, project-local semantic recipes for new wire layouts.

This is NOT an adapter activation API. Recipes yield research-only CanonicalDrafts;
no imported protocol ZIP can supply code or a recipe to this loader. Exact-build
matches and independently annotated cases are required for research comparison.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json
import re

from anka_contracts.canonical import CanonicalDraft, EvidenceRef
from anka_contracts.semantic import SemanticResult
from anka_contracts.fight_semantic import FightResearchDraft, FightResearchResult
from anka_contracts.protocol import WireMessage
from anka_protocol.adapters.historical import HistoricalCatalog
from anka_protocol.wire import parse_fields, WireRejected

_ID = re.compile(r'^[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,95}$')
_BUILD = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._ -]{2,95}$')
_HASH = re.compile(r'^[0-9a-f]{64}$')
_ALLOWED = {'actor_ap', 'actor_mp', 'actor_range', 'actor_hp'}
_FIGHT = {'fight_start','fight_end','turn_start','turn_end','actor_cell','spell_cast'}
_FIGHT_PATHS = {
    'fight_start': ('fight_id_path',),
    'fight_end': ('fight_id_path',),
    'turn_start': ('fight_id_path','actor_path','turn_index_path'),
    'turn_end': ('fight_id_path','actor_path','turn_index_path'),
    'actor_cell': ('fight_id_path','actor_path','cell_path'),
    'spell_cast': ('fight_id_path','actor_path','spell_id_path','target_cell_path'),
}
_FIELDS = {'actor_ap': 'value_path', 'actor_mp': 'value_path',
           'actor_range': 'value_path', 'actor_hp': 'value_path'}
_MAX_RECIPES = 16
_MAX_RULES = 32
_MAX_DEPTH = 5
_MAX_FILE = 32768


class RecipeRejected(ValueError):
    """Public errors are stable codes, not user-supplied contents."""


def _fail(code: str):
    raise RecipeRejected('P30_' + code)


def _json(raw: bytes):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                _fail('DUPLICATE_JSON_KEY')
            result[k] = v
        return result
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                          parse_constant=lambda _: _fail('INVALID_JSON_CONSTANT'))
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        if isinstance(exc, RecipeRejected):
            raise
        _fail('JSON_INVALID')


def _keys(obj, required, optional=()):
    if type(obj) is not dict or set(obj) - set(required) - set(optional) or set(required) - set(obj):
        _fail('RECIPE_SCHEMA_INVALID')


def _id(value, *, build=False):
    if type(value) is not str or not (_BUILD if build else _ID).fullmatch(value):
        _fail('IDENTIFIER_INVALID')
    return value


def _path(value):
    if (not isinstance(value, list) or not 1 <= len(value) <= _MAX_DEPTH
        or any(type(x) is not int or not 1 <= x < 2**29 for x in value)):
        _fail('FIELD_PATH_INVALID')
    return tuple(value)


@dataclass(frozen=True, slots=True)
class _Rule:
    wire_name: str
    capability: str
    actor_path: tuple[int, ...]
    value_path: tuple[int, ...]
    maximum_path: tuple[int, ...] | None


@dataclass(frozen=True, slots=True)
class _FightRule:
    wire_name: str
    capability: str
    paths: tuple[tuple[int, ...], ...]


class DeclarativeResearchAdapter:
    def __init__(self, build: str, adapter_id: str, rules: tuple[_Rule, ...],
                 fight_rules: tuple[_FightRule, ...] = ()):
        self.build = build
        self.adapter_id = adapter_id
        self.rules = {r.wire_name: r for r in rules}
        self.fight_rules = {r.wire_name: r for r in fight_rules}

    def decode(self, msg: WireMessage, *, context=None) -> SemanticResult:
        base = dict(adapter_id=self.adapter_id, protocol_build=self.build, wire_name=msg.name)
        rule = self.rules.get(msg.name)
        if rule is None:
            return SemanticResult('NO_SEMANTIC_MAPPING', **base)
        if msg.direction != 'server_to_client':
            return SemanticResult('QUARANTINED', failure_code='P30_DIRECTION_MISMATCH', **base)
        try:
            node = parse_fields(msg.body)
            actor = _scalar(node, rule.actor_path, signed=True)
            value = _scalar(node, rule.value_path)
            provenance = EvidenceRef(self.build, self.adapter_id, msg.name,
                                     msg.packet_number, msg.generation,
                                     sha256(msg.flow_key.encode('utf-8')).hexdigest(),
                                     message_index=msg.message_index)
            if rule.capability == 'actor_hp':
                maximum = _scalar(node, rule.maximum_path)
                draft = CanonicalDraft('ACTOR_HP_ABSOLUTE', actor, provenance,
                                       value=value, maximum=maximum)
            else:
                resource = {'actor_ap':'AP','actor_mp':'MP','actor_range':'RANGE'}[rule.capability]
                draft = CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE', actor, provenance,
                                       resource=resource, value=value)
            return SemanticResult('CANDIDATES_ONLY', candidates=(draft,), **base)
        except (ValueError, TypeError, KeyError, WireRejected):
            return SemanticResult('QUARANTINED', failure_code='P30_SCHEMA_OR_VALUE_DRIFT', **base)


    def decode_fight(self, msg: WireMessage, *, context=None) -> FightResearchResult:
        """Read-only event research: no Canonical journal, no execution authority."""
        base = dict(adapter_id=self.adapter_id, protocol_build=self.build, wire_name=msg.name)
        rule = self.fight_rules.get(msg.name)
        if rule is None:
            return FightResearchResult('NO_SEMANTIC_MAPPING', **base)
        if msg.direction != 'server_to_client':
            return FightResearchResult('QUARANTINED', failure_code='P31_DIRECTION_MISMATCH', **base)
        try:
            node = parse_fields(msg.body)
            fields = _FIGHT_PATHS[rule.capability]
            values = dict(zip(fields, (_scalar(node, path, signed=(name == 'actor_path'))
                                       for name, path in zip(fields, rule.paths))))
            proof = EvidenceRef(self.build, self.adapter_id, msg.name, msg.packet_number,
                                msg.generation, sha256(msg.flow_key.encode('utf-8')).hexdigest(),
                                message_index=msg.message_index)
            aliases = {'fight_id_path':'fight_id','actor_path':'actor_id',
                       'turn_index_path':'turn_index','cell_path':'cell_id',
                       'spell_id_path':'spell_id','target_cell_path':'target_cell'}
            kind = {'fight_start':'FIGHT_START_OBSERVED','fight_end':'FIGHT_END_OBSERVED',
                    'turn_start':'TURN_START_OBSERVED','turn_end':'TURN_END_OBSERVED',
                    'actor_cell':'ACTOR_CELL_OBSERVED','spell_cast':'SPELL_CAST_OBSERVED'}[rule.capability]
            draft = FightResearchDraft(kind,proof,**{aliases[k]:v for k,v in values.items()})
            return FightResearchResult('CANDIDATES_ONLY', candidates=(draft,), **base)
        except (ValueError, TypeError, KeyError, WireRejected):
            return FightResearchResult('QUARANTINED', failure_code='P31_SCHEMA_OR_VALUE_DRIFT', **base)


def _scalar(node: dict, path: tuple[int, ...], *, signed=False) -> int:
    if not path:
        raise ValueError('EMPTY_PATH')
    current = node
    for index, number in enumerate(path):
        occurrences = current.get(number, ())
        if len(occurrences) != 1:
            raise ValueError('MISSING_OR_REPEATED_FIELD')
        item = occurrences[0]
        if index < len(path)-1:
            if type(item) is not bytes:
                raise ValueError('EXPECTED_NESTED_MESSAGE')
            current = parse_fields(item)
        else:
            if type(item) is not int:
                raise ValueError('EXPECTED_VARINT')
            return item - (1 << 64) if signed and item >= (1 << 63) else item
    raise ValueError('UNREACHABLE')


def load_local_recipe(root: Path, *, build: str, adapter_id: str):
    """Return (adapter, wire catalog) from a hash-pinned LOCAL registry.

    No network access, imports, dynamic expressions, wildcards, or config-provided
    filesystem paths. Only exact build + adapter matches can be selected.
    """
    directory = Path(root) / 'reference' / 'protocol' / 'research_adapters'
    registry = directory / 'registry.json'
    if not registry.exists():
        return None
    if directory.is_symlink() or registry.is_symlink():
        _fail('SYMLINK_FORBIDDEN')
    if registry.stat().st_size > _MAX_FILE:
        _fail('REGISTRY_TOO_LARGE')
    document = _json(registry.read_bytes())
    _keys(document, {'schema','source_role','adapters'})
    if type(document['schema']) is not int or document['schema'] != 1 or document['source_role'] != 'LOCAL_REVIEWED_RESEARCH_ONLY':
        _fail('REGISTRY_UNSAFE')
    entries = document['adapters']
    if not isinstance(entries, list) or len(entries) > _MAX_RECIPES:
        _fail('REGISTRY_ENTRIES_INVALID')
    found = None
    keys = set()
    for entry in entries:
        _keys(entry, {'protocol_build', 'adapter_id', 'file', 'sha256'})
        key = (_id(entry['protocol_build'], build=True), _id(entry['adapter_id']))
        if key in keys:
            _fail('DUPLICATE_REGISTRY_ENTRY')
        keys.add(key)
        filename = entry['file']
        if (type(filename) is not str or not re.fullmatch(r'[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,95}\.json', filename)
            or filename == 'registry.json' or type(entry['sha256']) is not str or not _HASH.fullmatch(entry['sha256'])):
            _fail('REGISTRY_ENTRY_INVALID')
        if key == (build, adapter_id):
            found = entry
    if found is None:
        return None
    file = directory / found['file']
    if file.is_symlink() or not file.is_file() or file.stat().st_size > _MAX_FILE:
        _fail('RECIPE_UNSAFE_FILE')
    raw = file.read_bytes()
    if sha256(raw).hexdigest() != found['sha256']:
        _fail('RECIPE_HASH_MISMATCH')
    doc = _json(raw)
    _keys(doc, {'schema','source_role','protocol_build','adapter_id','rules'})
    if (type(doc['schema']) is not int or doc['schema'] not in (1, 2) or doc['source_role'] != 'LOCAL_REVIEWED_RESEARCH_ONLY'
        or doc['protocol_build'] != build or doc['adapter_id'] != adapter_id):
        _fail('RECIPE_VERSION_MISMATCH')
    rows = doc['rules']
    if not isinstance(rows, list) or not 1 <= len(rows) <= _MAX_RULES:
        _fail('RULE_COUNT_INVALID')
    rules = []
    fight_rules = []
    names = set()
    for row in rows:
        if type(row) is not dict:
            _fail('RULE_UNSAFE')
        capability = row.get('capability')
        if capability in _FIGHT and doc['schema'] == 2:
            fields = _FIGHT_PATHS[capability]
            _keys(row, {'wire_name','direction','capability',*fields})
            wire = _id(row['wire_name'])
            if not re.fullmatch(r'[A-Za-z0-9_]{1,96}', wire) or wire in names or row['direction'] != 'server_to_client':
                _fail('RULE_UNSAFE')
            paths = tuple(_path(row[name]) for name in fields)
            if len(set(paths)) != len(paths):
                _fail('AMBIGUOUS_PATHS')
            fight_rules.append(_FightRule(wire, capability, paths))
        else:
            _keys(row, {'wire_name','direction','capability','actor_path','value_path'}, {'maximum_path'})
            wire = _id(row['wire_name'])
            if not re.fullmatch(r'[A-Za-z0-9_]{1,96}', wire):
                _fail('WIRE_NAME_INVALID')
            if (wire in names or capability not in _ALLOWED or row['direction'] != 'server_to_client'
                or (capability == 'actor_hp') != ('maximum_path' in row)):
                _fail('RULE_UNSAFE')
            actor = _path(row['actor_path']); value = _path(row['value_path'])
            maximum = _path(row['maximum_path']) if 'maximum_path' in row else None
            if actor == value or (maximum is not None and len({actor,value,maximum})!=3):
                _fail('AMBIGUOUS_PATHS')
            rules.append(_Rule(wire, capability, actor, value, maximum))
        names.add(wire)
    adapter = DeclarativeResearchAdapter(build, adapter_id, tuple(rules), tuple(fight_rules))
    # Catalog is observed only, not proof that any listed wire is semantically correct.
    catalog = HistoricalCatalog(adapter_id, build,
        frozenset((r.wire_name, 'server_to_client') for r in (*rules,*fight_rules)),
        evidence_source='P30_LOCAL_RESEARCH_RECIPE_ONLY', semantic_certified=False)
    return adapter, catalog
