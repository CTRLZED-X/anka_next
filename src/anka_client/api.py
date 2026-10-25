"""Public read-only Client System facade. All live input stays prohibited."""
from __future__ import annotations
import os
from dataclasses import asdict
from anka_client.discovery import bind_accounts
from anka_client.geometry import geometry_diagnosis
from anka_contracts.client import WindowInventory, CharacterEvidenceProvider


class ClientInspection:
    def __init__(self, inventory: WindowInventory, identity: CharacterEvidenceProvider | None = None):
        self.inventory=inventory
        self.identity=identity

    def inspect(self,names:tuple[str,...])->dict:
        scan=self.inventory.scan()
        # identity provider must be constructed by a future trustworthy composition
        # root. There is deliberately no title-to-identity automatic fallback.
        evidence=self.identity.snapshot() if self.identity is not None else ()
        bindings=bind_accounts(names,scan,evidence)
        by_hwnd={w.hwnd:w for w in scan.windows}
        geometry={b.name:geometry_diagnosis(by_hwnd[b.hwnd]) for b in bindings
                  if b.hwnd is not None and b.hwnd in by_hwnd}
        return {'status':'NOT_CERTIFIED', 'physical_input_permitted':False,
                'scan_errors':list(scan.errors),'observed_windows':len(scan.windows),
                'bindings':[asdict(b) for b in bindings], 'geometry':geometry,
                'live_character_provider':self.identity is not None}


def inspect_local_clients(names:tuple[str,...])->dict:
    if os.name!='nt':
        return {'status':'NOT_AVAILABLE','reason':'WINDOWS_REQUIRED','physical_input_permitted':False,
                'bindings':[],'observed_windows':0,'scan_errors':[]}
    from anka_client.win32_inventory import NativeWindowsInventory
    return ClientInspection(NativeWindowsInventory(names)).inspect(names)


def inspect_reference_bridge(window, port:int, reader=None, *, map_id:int|None=None):
    """Read-only P44 bridge research: never certifies an input or player."""
    from anka_client.unity_bridge import LocalLoopbackBridgeReader, ReadOnlyBridgeInspector
    inspector=ReadOnlyBridgeInspector(reader if reader is not None else LocalLoopbackBridgeReader())
    if map_id is None:
        return inspector.inspect_identity(window,port)
    return inspector.inspect_coordinates(window,port,map_id=map_id)


def audit_reference_bridge_source(root):
    """Source-only integrity result; not a host/client acceptance proof."""
    from anka_client.bridge_source import audit_bridge_source
    return audit_bridge_source(root)
