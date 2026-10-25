"""Readiness is an explicit tri-state, not a boolean success assumption."""
from enum import Enum

class Readiness(str, Enum):
    READY = 'READY'
    BLOCKED = 'BLOCKED'
    NOT_CERTIFIED = 'NOT_CERTIFIED'
