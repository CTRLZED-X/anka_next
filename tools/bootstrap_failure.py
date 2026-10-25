"""Dependency-free incident export before pip/install succeeds.

Usage: python tools/bootstrap_failure.py DEPENDENCY_INSTALL_FAILED
No raw installer console output is copied to a shareable archive.
"""
from __future__ import annotations
from pathlib import Path
from hashlib import sha256
from zipfile import ZipFile,ZIP_DEFLATED
from datetime import datetime,timezone
from uuid import uuid4
import json
import re
import sys

def blob(x):return (json.dumps(x,sort_keys=True,indent=2)+'\n').encode('utf8')

def main(args:list[str]) -> int:
    code=args[0] if args else 'BOOTSTRAP_FAILED'
    if not re.fullmatch('[A-Z][A-Z0-9_]{2,80}',code):code='BOOTSTRAP_FAILED'
    folder=Path.cwd()/'runtime'/'bootstrap'
    try:folder.mkdir(parents=True,exist_ok=True)
    except OSError:
        from tempfile import gettempdir
        folder=Path(gettempdir())/'ANKA_NEXT'/'bootstrap';folder.mkdir(parents=True,exist_ok=True)
    identity='bootstrap-'+uuid4().hex
    out=folder/(identity+'.zip')
    body={
      'diagnosis.json':blob({'schema_version':1,'failure_code':code,'first_observed_boundary':'bootstrap.dependencies',
        'finding_status':'HYPOTHESIS_NOT_VERIFIED','confidence':'UNDETERMINED',
        'missing_information':'This exporter ran before installation; raw pip output is excluded for privacy.'}),
      'evidence_matrix.json':blob({'schema_version':1,'sections':{
          'bootstrap':'PARTIAL','configuration':'MISSING','identity':'MISSING','capture':'MISSING',
          'protocol':'MISSING','canonical':'MISSING','live_state':'MISSING','coordination':'MISSING',
          'decision':'MISSING','execution':'MISSING','outcome':'MISSING'}}),
      'timeline.jsonl':b'',
      'GPT_READ_FIRST.md':('# ANKA bootstrap incident\n\n**Failure code:** '+code+'\n\n'
        '**Observed stage:** dependency installation or interpreter setup.\n\n'
        'Detailed installer output is stored in the local bootstrap log, not in this sanitized archive.\n'
        'Reproduce after checking the Python version, network access, package source and permissions.\n').encode(),
    }
    manifest={'schema_version':1,'incident_id':identity,'source':'STDLIB_BOOTSTRAP_ONLY',
      'created_utc':datetime.now(timezone.utc).isoformat(),'run_id':None,'raw_protocol_included':False,
      'external_upload':False,'completeness':'PARTIAL','dropped_events':None,
      'files':{name:{'sha256':sha256(value).hexdigest(),'bytes':len(value)} for name,value in body.items()}}
    with ZipFile(out,'w',ZIP_DEFLATED) as z:
        for name,value in body.items():z.writestr(name,value)
        z.writestr('manifest.json',blob(manifest))
    print('ANKA_BOOTSTRAP_BUNDLE='+str(out))
    return 0
if __name__=='__main__':raise SystemExit(main(sys.argv[1:]))
