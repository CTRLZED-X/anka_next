"""Dependency-free release-integrity gate used by setup before pip/install."""
from __future__ import annotations
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'src'
if str(SRC) not in sys.path:sys.path.insert(0,str(SRC))
from anka_app.release_integrity import verify_release_integrity

def main()->int:
    result=verify_release_integrity(ROOT)
    safe=result.safe_receipt()
    print('RELEASE_INTEGRITY='+safe['status'])
    print('RELEASE_ID='+str(safe.get('release_id') or 'UNKNOWN'))
    print('RELEASE_CHECKED_FILES='+str(safe.get('checked_files',0)))
    return 0 if result.status=='PASS' else 40

if __name__=='__main__':raise SystemExit(main())
