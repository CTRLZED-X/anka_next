"""Read-only, fail-closed ingestion of external protocol-upgrade evidence bundles.

Never executes supplied content, extracts files, imports adapter code, or grants
canonical/live/physical authority. Raw captures and witness media never enter
reports. This is *intake*, not protocol certification or decoding.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from io import BytesIO
from base64 import b32encode
from zipfile import ZipFile, BadZipFile, ZipInfo, ZIP_STORED, ZIP_DEFLATED
import json
import re
import stat
import math

MAX_ARCHIVE = 128 * 1024 * 1024
MAX_MEMBER = 64 * 1024 * 1024
MAX_UNCOMPRESSED = 192 * 1024 * 1024
MAX_MANIFEST = 96 * 1024
MAX_ORACLE = 256 * 1024
MAX_FILES = 32
MAX_CASES = 128
BUILD_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._ -]{2,95}$')
IDENTIFIER = re.compile(r'^[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,95}$')
HASH = re.compile(r'^[0-9a-f]{64}$')
CAPABILITIES = frozenset({
    'character_identity', 'fight_start', 'fight_end', 'turn_start', 'turn_end',
    'actor_cell', 'actor_hp', 'actor_ap', 'actor_mp', 'spell_cast', 'spell_cooldown',
    'movement', 'action_outcome', 'ready', 'fight_join', 'fight_result',
})
REQUIRED_CAPABILITIES = frozenset({
    'character_identity', 'fight_start', 'turn_start', 'turn_end',
    'actor_cell', 'actor_hp', 'actor_ap', 'actor_mp', 'spell_cast', 'action_outcome',
})
KINDS = frozenset({'pcapng', 'oracle', 'screenshot', 'game_log', 'video', 'proto'})

class IntakeRejected(ValueError):
    """Stable non-sensitive error code, safe to include in a diagnostic bundle."""


def reject(code: str):
    raise IntakeRejected('P28_' + code)


def evidence_binding_id(archive_sha256: str, protocol_build: str, adapter_id: str) -> str:
    """Opaque stable identifier for one exact intake/comparison evidence tuple.

    Base32 hides client/version text from low-level comparison reports (and
    prevents accidentally leaking expected numeric stats in diagnostic tests).
    It is a consistency checksum, NOT a signed or trusted attestation.
    """
    payload = json.dumps([archive_sha256, protocol_build, adapter_id],
                         ensure_ascii=True, separators=(',', ':')).encode('utf-8')
    return b32encode(sha256(payload).digest()).decode('ascii').rstrip('=')


def evidence_case_binding(archive_sha256: str, protocol_build: str, adapter_id: str,
                          case_index: int, case_evidence: tuple) -> str:
    """Opaque, versioned *case-specific* join key for a research result.

    This prevents same-capability rows from becoming interchangeable when
    a comparator report is mixed or reordered. It is not a signature and does
    not establish account-role identity or independent witness credibility.
    """
    payload = json.dumps(['ANKA_RESEARCH_CASE_V1', archive_sha256, protocol_build,
                          adapter_id, case_index, list(case_evidence)],
                         ensure_ascii=True, separators=(',', ':')).encode('utf-8')
    return b32encode(sha256(payload).digest()).decode('ascii').rstrip('=')


def _object(value, required, optional=()):
    if not isinstance(value, dict) or (set(required)-value.keys()) or (value.keys() - set(required) - set(optional)):
        reject('SCHEMA_INVALID')
    return value


def _unique_json(raw: bytes):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                reject('DUPLICATE_JSON_KEY')
            out[key] = value
        return out
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                          parse_constant=lambda _: reject('NONFINITE_JSON'))
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        if isinstance(exc, IntakeRejected):
            raise
        reject('JSON_INVALID')


def _id(value, *, build=False):
    if type(value) is not str or not (BUILD_PATTERN if build else IDENTIFIER).fullmatch(value):
        reject('IDENTIFIER_INVALID')
    return value


def _member_name(value):
    if type(value) is not str or not 1 <= len(value) <= 160 or '\\' in value or ':' in value:
        reject('PATH_UNSAFE')
    p = PurePosixPath(value)
    if p.is_absolute() or str(p) != value or any(c in ('.', '..', '') for c in value.split('/')):
        reject('PATH_UNSAFE')
    if value.endswith('/') or value.startswith('runtime/'):
        reject('PATH_UNSAFE')
    return value


def _sha(value):
    if type(value) is not str or not HASH.fullmatch(value):
        reject('HASH_INVALID')
    return value


def _member_bytes(archive: ZipFile, info: ZipInfo, limit: int) -> bytes:
    if info.file_size > limit:
        reject('FILE_SIZE_LIMIT')
    try:
        with archive.open(info, 'r') as f:
            out = f.read(limit + 1)
    except (OSError, BadZipFile, RuntimeError, EOFError):
        reject('CORRUPT_MEMBER')
    if len(out) != info.file_size or len(out) > limit:
        reject('CORRUPT_MEMBER')
    return out


def _hash_member(archive: ZipFile, info: ZipInfo, expected: str) -> None:
    h = sha256()
    count = 0
    try:
        with archive.open(info) as stream:
            while data := stream.read(1024 * 1024):
                count += len(data)
                if count > MAX_MEMBER:
                    reject('FILE_SIZE_LIMIT')
                h.update(data)
    except (OSError, BadZipFile, RuntimeError, EOFError):
        reject('CORRUPT_MEMBER')
    if count != info.file_size or h.hexdigest() != expected:
        reject('FILE_HASH_MISMATCH')


@dataclass(frozen=True)
class IntakeReport:
    protocol_build: str
    adapter_id: str
    archive_sha256: str
    source_count: int
    case_count: int
    covered_capabilities: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    cases_with_witness: int
    intake_complete: bool
    # Validated, privacy-safe selectors aligned to the manifest case order.
    # Does not include names, actor IDs, values, captures or oracle content.
    case_evidence: tuple[tuple[str, str, bool, bool], ...] = ()

    def to_dict(self) -> dict:
        return {
            'status': 'EVIDENCE_INTAKE_READY_FOR_MANUAL_REVIEW' if self.intake_complete else 'EVIDENCE_INTAKE_INCOMPLETE',
            'protocol_build': self.protocol_build, 'adapter_id': self.adapter_id,
            'archive_sha256': self.archive_sha256, 'source_count': self.source_count,
            'case_count': self.case_count,
            'covered_capabilities': list(self.covered_capabilities),
            'missing_capabilities': list(self.missing_capabilities),
            'cases_with_witness': self.cases_with_witness,
            'blockers': [
                'CURRENT_BUILD_SEMANTIC_ADAPTER_NOT_CERTIFIED',
                'OBSERVATION_ORACLES_NOT_INDEPENDENTLY_VERIFIED',
                'END_TO_END_LIVE_ACCEPTANCE_PENDING',
                *(['REQUIRED_CAPABILITY_EVIDENCE_INCOMPLETE'] if self.missing_capabilities else []),
                *(['VISUAL_OR_LOG_WITNESS_MISSING'] if self.cases_with_witness < self.case_count else []),
            ],
            'live_semantic_certified': False, 'canonical_commits': 0,
            'physical_input_sent': False, 'adapter_activated': False,
        }


def inspect_evidence_pack(path: Path) -> IntakeReport:
    """Audit one untrusted ZIP without extracting or persisting its contents."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError:
        reject('PACK_UNREADABLE')
    if size > MAX_ARCHIVE or size <= 0:
        reject('ARCHIVE_SIZE_LIMIT')
    # Capture one bounded immutable snapshot so a concurrently replaced ZIP
    # cannot give a digest for one archive and validated members from another.
    try:
        with path.open('rb') as inp:
            raw_archive = inp.read(MAX_ARCHIVE + 1)
        if not raw_archive or len(raw_archive) > MAX_ARCHIVE:
            reject('ARCHIVE_SIZE_LIMIT')
        archive_hash = sha256(raw_archive)
        with ZipFile(BytesIO(raw_archive)) as archive:
            members = archive.infolist()
            if not 2 <= len(members) <= MAX_FILES:
                reject('ARCHIVE_MEMBER_COUNT')
            found = {}
            keys = set()
            total = 0
            for info in members:
                name = _member_name(info.filename)
                folded = name.casefold()
                if folded in keys:
                    reject('ARCHIVE_DUPLICATE_NAME')
                keys.add(folded)
                mode = (info.external_attr >> 16) & 0o170000
                if info.is_dir() or mode not in (0, stat.S_IFREG) or info.flag_bits & 1:
                    reject('ARCHIVE_UNSAFE_MEMBER')
                if info.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
                    reject('ARCHIVE_COMPRESSION_UNSUPPORTED')
                if info.file_size > MAX_MEMBER or info.compress_size == 0 and info.file_size != 0:
                    reject('FILE_SIZE_LIMIT')
                if info.compress_size and info.file_size > info.compress_size * 300:
                    reject('ARCHIVE_SUSPICIOUS_RATIO')
                total += info.file_size
                if total > MAX_UNCOMPRESSED:
                    reject('ARCHIVE_EXPANSION_LIMIT')
                found[name] = info
            if 'manifest.json' not in found:
                reject('MANIFEST_MISSING')
            manifest = _object(_unique_json(_member_bytes(archive, found['manifest.json'], MAX_MANIFEST)),
                {'schema', 'package_kind', 'protocol_build', 'adapter_id', 'sources', 'cases'}, {'server_ports'})
            if type(manifest['schema']) is not int or manifest['schema'] != 1 or manifest['package_kind'] != 'ANKA_PROTOCOL_EVIDENCE':
                reject('MANIFEST_VERSION_UNSUPPORTED')
            build = _id(manifest['protocol_build'], build=True)
            adapter = _id(manifest['adapter_id'])
            if 'server_ports' in manifest:
                ports = manifest['server_ports']
                if (not isinstance(ports, list) or not 1 <= len(ports) <= 8
                        or any(type(x) is not int or not 1 <= x <= 65535 for x in ports)
                        or len(set(ports)) != len(ports)):
                    reject('PORTS_INVALID')
            sources = manifest['sources']
            cases = manifest['cases']
            if not isinstance(sources, list) or not 2 <= len(sources) <= MAX_FILES-1:
                reject('SOURCE_COUNT_INVALID')
            if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
                reject('CASE_COUNT_INVALID')
            declared = {}
            source_hashes = {}  # identity by bytes, not caller-chosen filename
            for source in sources:
                src = _object(source, {'path', 'sha256', 'kind'})
                name = _member_name(src['path'])
                kind = src['kind']
                if type(kind) is not str or kind not in KINDS or name in declared or name == 'manifest.json':
                    reject('SOURCE_INVALID')
                if name not in found:
                    reject('SOURCE_MISSING')
                if kind == 'pcapng' and not name.lower().endswith('.pcapng'):
                    reject('SOURCE_KIND_MISMATCH')
                if kind == 'oracle' and not name.lower().endswith('.json'):
                    reject('SOURCE_KIND_MISMATCH')
                if kind == 'screenshot' and not name.lower().endswith(('.png', '.jpg', '.jpeg')):
                    reject('SOURCE_KIND_MISMATCH')
                if kind == 'video' and not name.lower().endswith(('.mp4', '.mkv')):
                    reject('SOURCE_KIND_MISMATCH')
                if kind == 'game_log' and not name.lower().endswith(('.log', '.txt', '.json')):
                    reject('SOURCE_KIND_MISMATCH')
                if kind == 'proto' and not name.lower().endswith('.proto'):
                    reject('SOURCE_KIND_MISMATCH')
                _hash_member(archive, found[name], _sha(src['sha256']))
                # Prove the witness has the declared *file type*, not that it
                # proves the annotation's truth (which needs manual review).
                if kind == 'screenshot':
                    with archive.open(found[name]) as image:
                        head = image.read(8)
                    if not (name.lower().endswith('.png') and head == b'\x89PNG\r\n\x1a\n' or
                            name.lower().endswith(('.jpg', '.jpeg')) and head[:3] == b'\xff\xd8\xff'):
                        reject('WITNESS_FORMAT_INVALID')
                declared[name] = kind
                source_hashes[name] = src['sha256']
            if set(found) != set(declared) | {'manifest.json'}:
                reject('UNDECLARED_ARCHIVE_MEMBER')
            if 'pcapng' not in declared.values() or 'oracle' not in declared.values():
                reject('MISSING_REQUIRED_SOURCE_KIND')
            oracle_index = {}
            for name, kind in declared.items():
                if kind == 'pcapng':
                    with archive.open(found[name]) as stream:
                        if stream.read(4) != b'\x0a\x0d\x0d\x0a':
                            reject('PCAPNG_SIGNATURE_INVALID')
                if kind != 'oracle':
                    continue
                doc = _object(_unique_json(_member_bytes(archive, found[name], MAX_ORACLE)),
                              {'schema','observations'})
                if type(doc['schema']) is not int or doc['schema'] != 1 or not isinstance(doc['observations'], list) or len(doc['observations']) > MAX_CASES:
                    reject('ORACLE_SCHEMA_INVALID')
                for item in doc['observations']:
                    item = _object(item, {'id', 'capability', 'expected'}, {'note'})
                    oid = _id(item['id'])
                    capability = item['capability']
                    if type(capability) is not str or capability not in CAPABILITIES or not isinstance(item['expected'],dict) or not item['expected'] or len(item['expected']) > 24:
                        reject('ORACLE_OBSERVATION_INVALID')
                    # Expected values must be reproducible JSON scalars only.
                    if any(type(k) is not str or len(k) > 80 for k in item['expected']):
                        reject('ORACLE_EXPECTED_VALUE_INVALID')
                    if any(type(v) not in (int, str, bool, float) or (type(v) is str and len(v) > 128) or (type(v) is float and not math.isfinite(v)) for v in item['expected'].values()):
                        reject('ORACLE_EXPECTED_VALUE_INVALID')
                    if (name, oid) in oracle_index:
                        reject('ORACLE_DUPLICATE_ID')
                    oracle_index[(name, oid)] = capability
            covered = set()
            ids = set()
            witnessed = 0
            case_evidence = []
            # A single selected transport message or the same independent
            # oracle assertion cannot be relabelled as BOTH client accounts.
            # Source digests prevent trivial filename aliases from bypassing
            # this check. This is a necessary research hygiene condition; it
            # does NOT certify that either declared account role is genuine.
            selector_roles = {}
            # One selected packet may contain many different capabilities, but
            # it is only ONE source observation per role/capability. Differently
            # named oracle assertions must not inflate same-field coverage.
            selector_capability_claims = set()
            oracle_roles = {}
            for row in cases:
                row = _object(row, {'id','capability','capture','oracle','oracle_id','account_role'}, {'witness','selector'})
                if 'selector' in row:
                    sel = _object(row['selector'], {'packet_number','message_index','wire_name',
                        'direction','transport_generation','flow_digest'})
                    for field in ('packet_number','message_index','transport_generation'):
                        if type(sel[field]) is not int or sel[field] < 0:
                            reject('SELECTOR_INVALID')
                    if (type(sel['wire_name']) is not str or not sel['wire_name'].isascii()
                            or not sel['wire_name'].replace('_','').isalnum()
                            or not 1 <= len(sel['wire_name']) <= 96
                            or sel['direction'] not in ('server_to_client','client_to_server')
                            or type(sel['flow_digest']) is not str or not HASH.fullmatch(sel['flow_digest'])):
                        reject('SELECTOR_INVALID')
                cid = _id(row['id'])
                capability = row['capability']
                role = row['account_role']
                if cid in ids or type(capability) is not str or capability not in CAPABILITIES or type(role) is not str or role not in ('leader','follower','other'):
                    reject('CASE_INVALID')
                ids.add(cid)
                if type(row['capture']) is not str or type(row['oracle']) is not str or declared.get(row['capture']) != 'pcapng' or declared.get(row['oracle']) != 'oracle':
                    reject('CASE_SOURCE_MISMATCH')
                if type(row['oracle_id']) is not str or oracle_index.get((row['oracle'], row['oracle_id'])) != capability:
                    reject('CASE_ORACLE_MISMATCH')
                oracle_source = (source_hashes[row['oracle']], row['oracle_id'])
                previous_oracle_role = oracle_roles.get(oracle_source)
                if previous_oracle_role is not None:
                    # Reusing an assertion (even in the same role) does not
                    # create an additional independent observation.
                    reject('ORACLE_OBSERVATION_REUSED')
                oracle_roles[oracle_source] = role
                if 'selector' in row:
                    sel = row['selector']
                    selector_source = (source_hashes[row['capture']],
                        sel['packet_number'], sel['message_index'],
                        sel['transport_generation'], sel['flow_digest'],
                        sel['wire_name'], sel['direction'])
                    previous_selector_role = selector_roles.get(selector_source)
                    if previous_selector_role is not None and previous_selector_role != role:
                        reject('CROSS_ROLE_SOURCE_REUSE')
                    selector_roles[selector_source] = role
                    claim = (selector_source, role, capability)
                    if claim in selector_capability_claims:
                        reject('DUPLICATE_SOURCE_CAPABILITY_CLAIM')
                    selector_capability_claims.add(claim)
                witness = row.get('witness')
                if witness is not None:
                    if type(witness) is not str or declared.get(witness) not in ('screenshot','game_log','video'):
                        reject('CASE_WITNESS_MISMATCH')
                    witnessed += 1
                covered.add(capability)
                case_evidence.append((capability, role, witness is not None, 'selector' in row))
            missing = tuple(sorted(REQUIRED_CAPABILITIES-covered))
            return IntakeReport(build,adapter,archive_hash.hexdigest(),len(sources),len(cases),
                tuple(sorted(covered)),missing,witnessed,not missing and witnessed == len(cases),
                tuple(case_evidence))
    except (BadZipFile, OSError, EOFError):
        reject('ARCHIVE_INVALID')
