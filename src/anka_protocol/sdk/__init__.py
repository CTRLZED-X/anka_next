"""Version-independent Protocol SDK. No version adapter is activated here."""
from .runtime import ProtocolAdapterRuntime, ProtocolTransaction, AdapterContextCheckpoint, TransactionResult
from .opaque import OpaqueFingerprint, OpaquePolicy
__all__=["ProtocolAdapterRuntime","ProtocolTransaction","AdapterContextCheckpoint","TransactionResult","OpaqueFingerprint","OpaquePolicy"]
