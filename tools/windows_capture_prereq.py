"""Internal setup helper: record Windows capture prerequisites, no installation."""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
import json
from anka_capture.windows_backend import probe_npcap_presence
ROOT=Path(__file__).resolve().parents[1]

def _release_manifest_sha()->str|None:
    path=ROOT/'RELEASE_MANIFEST.json'
    return sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def main()->int:
    result={'schema_version':2,**probe_npcap_presence(),'physical_input_enabled':False,
            'release_manifest_sha256':_release_manifest_sha()}
    path=ROOT/'runtime'/'capture_prereq.json';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n',encoding='utf8')
    print('CAPTURE_PREREQ='+result['status'])
    return 0
if __name__=='__main__':raise SystemExit(main())
