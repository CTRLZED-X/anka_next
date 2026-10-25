"""Python stdlib fallback for startup failures. Does not import business modules."""
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4
from datetime import datetime,timezone


def emergency_marker(root:Path,*,stage:str,code:str)->Path:
    obj={'schema_version':1,'invocation_id':'inv-'+uuid4().hex,'stage':stage,'code':code,
         'utc':datetime.now(timezone.utc).isoformat(),'status':'INCOMPLETE_BOOTSTRAP_ONLY'}
    for folder in [root/'runtime'/'emergency',Path(tempfile.gettempdir())/'ANKA_NEXT'/'emergency']:
        try:
            folder.mkdir(parents=True,exist_ok=True)
            file=folder/(obj['invocation_id']+'.json')
            file.write_text(json.dumps(obj,indent=2)+'\n',encoding='utf8')
            return file
        except OSError:continue
    raise OSError('NO_WRITABLE_DIAGNOSTIC_LOCATION')
