from enum import StrEnum


class Certainty(StrEnum):
    DETERMINISTIC = "deterministic"
    DETERMINISTIC_IF_CONTEXT_COMPLETE = "deterministic_if_context_complete"
    LIVE_REQUIRED = "live_required"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"
