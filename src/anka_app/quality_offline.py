"""P9 application composition: independent research qualifier + synthetic-state quality.

No historical candidate is converted into an OfflineStateEvent or a live write.
"""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from anka_contracts.canonical import CanonicalDraft, EvidenceRef
from anka_contracts.state import OfflineStateEvent
from anka_canonical.qualification import ResearchContext, review_candidates
from anka_canonical.journal import SQLiteFixtureJournal
from anka_live_state.reducer import apply_offline_event
from anka_live_state.quality import inspect_state_quality


def quality_demo(*, observer=None) -> dict:
    evidence=EvidenceRef('Dofus 3.7.10.10','historical_3_7_10_10','jtk',1,0,sha256(b'synthetic').hexdigest())
    draft=CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',777,evidence,resource='AP',value=11)
    review=review_candidates((draft,),ResearchContext('Dofus 3.7.10.10','historical_3_7_10_10',
                                                   transport='OBSERVED_NO_GAPS',identity='PROVISIONAL'))
    with TemporaryDirectory(prefix='anka-p9-quality-') as folder:
        with SQLiteFixtureJournal(Path(folder)/'state.sqlite3',reducer=apply_offline_event) as journal:
            def ev(n,kind,**kw):
                return OfflineStateEvent('p9-'+str(n),'p9-session','cra',1,'fight-a',n,kind,**kw)
            for item in (ev(1,'FIGHT_STARTED'),ev(2,'ACTOR_SEEN',actor_id=777),
                         ev(3,'ACTOR_HP_SET',actor_id=777,value=2800,maximum=3200),
                         ev(4,'ACTOR_RESOURCE_SET',actor_id=777,resource='AP',value=11),
                         ev(5,'ACTOR_RESOURCE_SET',actor_id=777,resource='MP',value=5),
                         ev(6,'ACTOR_POSITION_SET',actor_id=777,value=215),
                         ev(7,'ACTOR_COOLDOWNS_SET',actor_id=777,cooldowns=()),
                         ev(8,'TURN_STARTED',actor_id=777)):
                journal.append_fixture(item)
            quality=inspect_state_quality(journal.snapshot('p9-session'),session_id='p9-session',
                                          account_id='cra',account_generation=1,actor_id=777)
            audit=journal.audit()
    if observer is not None:
        observer.record('qualification.research_review_completed',boundary='canonical.research_qualification',
            payload={'status':review.status,'reason_codes':list(review.reason_codes),'actionable':False})
        observer.record('state.synthetic_quality_checked',boundary='state.quality_assessment',
            payload={'status':quality.status,'failures':list(quality.failures),'revision':quality.revision,'actionable':False})
    return {'operation':'quality-demo','status':'RESEARCH_AND_SYNTHETIC_ONLY',
            'protocol_research':review.to_dict(),'synthetic_state':quality.to_dict(),
            'journal':audit,'committed_historical_candidates':0,'live_ready':False,'physical_input_sent':False}


def quality_audit(path:Path, session_id:str, actor_id:int, *, observer=None)->dict:
    # The journal opens read-only and independently replays before quality assessment.
    with SQLiteFixtureJournal(path,reducer=apply_offline_event,read_only=True) as journal:
        checked=journal.audited_snapshot(session_id)
        audit=checked['audit']
        snapshot=checked['snapshot']
    if snapshot is None:
        result=inspect_state_quality(None,session_id=session_id,account_id='unknown',
                                     account_generation=0,actor_id=actor_id)
    else:
        result=inspect_state_quality(snapshot,session_id=session_id,account_id=snapshot['account_id'],
                        account_generation=snapshot['account_generation'],actor_id=actor_id)
    if observer is not None:
        observer.record('state.synthetic_quality_checked',boundary='state.quality_assessment',
                        payload={'status':result.status,'failures':list(result.failures),'actionable':False})
    return {'operation':'quality-audit','status':'SYNTHETIC_STATE_ONLY','quality':result.to_dict(),
            'journal':audit,'live_ready':False,'physical_input_sent':False}
