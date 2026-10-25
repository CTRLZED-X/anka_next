"""P62: synthetic proof that PCAPNG-reported capture drops cannot be silently ignored.

No current-client qualification, Canonical authority, or physical input.
"""
from __future__ import annotations
from pathlib import Path
from struct import pack
from tempfile import TemporaryDirectory
from anka_capture.api import CaptureRejected, inspect_pcapng
from anka_app.historical_pcapng_offline import _block, _packet


def capture_loss_metadata_smoke() -> dict:
    frame = _packet(100, 2, b'')
    loss_option = pack('<HHQ', 4, 8, 1)  # epb_dropcount, one lost packet
    capture = (_block(0x0a0d0d0a, b'\x4d\x3c\x2b\x1a' + pack('<HHq', 1, 0, -1)) +
               _block(1, pack('<HHI', 1, 0, 65535)) +
               _block(6, pack('<IIIII', 0, 0, 0, len(frame), len(frame)) + frame +
                      b'\0'*((-len(frame))%4) + loss_option))
    with TemporaryDirectory(prefix='anka_p62_loss_smoke_') as folder:
        path=Path(folder)/'synthetic.pcapng';path.write_bytes(capture)
        try:
            inspect_pcapng(path,server_ports=(40400,))
        except CaptureRejected as exc:
            if str(exc)!='CAPTURE_CONTENT_INVALID':
                raise RuntimeError('P62_WRONG_DROP_REJECTION') from None
        else:
            raise RuntimeError('P62_CAPTURE_LOSS_METADATA_SILENTLY_IGNORED')
    return {'status':'PASS_REPORTED_CAPTURE_LOSS_QUARANTINED',
            'driver_completeness_certified':False,
            'account_binding_verified':False,
            'canonical_commits':0,'physical_input_sent':False}
