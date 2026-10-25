"""P58 self-contained preflight proving untrusted evidence cannot cross journal."""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from anka_contracts.admission import (AdmissionScope,AdmissionRehearsal,UntrustedPacketClaim,UntrustedCharacterClaim)
from anka_contracts.canonical import EvidenceRef,CanonicalDraft
from anka_canonical.admission_review import review_admission_rehearsal, MANDATORY_BLOCKERS
from anka_canonical.journal import SQLiteFixtureJournal
from anka_live_state.reducer import apply_offline_event


def admission_boundary_smoke()->dict:
    ref0=EvidenceRef('UnverifiedCurrentClaim','untrusted-adapter','jnj',1,1,'a'*64)
    ref1=EvidenceRef('UnverifiedCurrentClaim','untrusted-adapter','jvj',2,1,'a'*64)
    scope=AdmissionScope('p58-session','p58-account',1,'p58-fight',
        'UnverifiedCurrentClaim','untrusted-adapter','a'*64,1,3,4,'b'*64)
    p0=UntrustedPacketClaim(ref0,'server_to_client',b'world',sha256(b'world').hexdigest(),'b'*64)
    p1=UntrustedPacketClaim(ref1,'server_to_client',b'fight',sha256(b'fight').hexdigest(),'b'*64)
    char=UntrustedCharacterClaim(ref0,41,sha256(b'character').hexdigest())
    candidate=CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',41,ref1,resource='AP',value=11)
    attempt=AdmissionRehearsal(scope,char,(p0,p1),(candidate,))
    report=review_admission_rehearsal(attempt)
    if (report.status!='STRUCTURALLY_CONSISTENT_UNTRUSTED' or report.certified or
        not set(MANDATORY_BLOCKERS).issubset(report.reasons)):
        raise RuntimeError('P58_UNTRUSTED_PROMOTED_OR_REHEARSAL_BROKEN')
    wrong=AdmissionRehearsal(scope,char,(p0,),(candidate,))
    rejected=review_admission_rehearsal(wrong)
    if rejected.status!='QUARANTINED' or 'P58_SEMANTIC_PACKET_NOT_PRESENT' not in rejected.reasons:
        raise RuntimeError('P58_UNBOUND_SOURCE_NOT_REJECTED')
    with TemporaryDirectory(prefix='anka-p58-admission-') as folder:
        with SQLiteFixtureJournal(Path(folder)/'fixture.db',reducer=apply_offline_event) as journal:
            try:
                journal.append_fixture_envelope(attempt)
            except TypeError:
                pass
            else:
                raise RuntimeError('P58_UNTRUSTED_JOURNAL_WRITE_ACCEPTED')
            if journal.audit()['events']!=0:
                raise RuntimeError('P58_UNTRUSTED_JOURNAL_CHANGED')
    return {'status':'PASS_UNTRUSTED_ADMISSION_BLOCKED',
        'structural_consistency_only':True,'missing_semantic_source_quarantined':True,
        'journal_rejected_untrusted_rehearsal':True,'canonical_commits':0,
        'live_ready':False,'actionable':False,'physical_input_sent':False}
