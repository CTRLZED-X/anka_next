class KernelError(Exception):
    """Base class for ANKA Game Kernel errors."""


class DuplicateDefinitionError(KernelError):
    """Raised when a registry receives the same canonical identifier twice."""


class DefinitionNotFoundError(KernelError, KeyError):
    """Raised when a required canonical definition is absent."""


class UnsupportedMechanicError(KernelError):
    """Raised when a semantic mechanic is not implemented by this Kernel build."""


class ExternalGameDataError(KernelError):
    """Raised when configured external Static/Mapuse data cannot be loaded safely."""
