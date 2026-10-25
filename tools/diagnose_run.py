"""Offline bundle verification; no runtime/startup effects."""
import json
import sys
from pathlib import Path
from anka_observability.bundle import verify_incident

if __name__=='__main__':
    if len(sys.argv)!=2:
        print('usage: python tools/diagnose_run.py bundle.zip')
        raise SystemExit(2)
    result=verify_incident(Path(sys.argv[1]))
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['status']=='PASS' else 1)
