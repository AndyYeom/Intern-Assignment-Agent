"""Administrator roles used at trusted authorization boundaries."""

from enum import Enum


class AdminRole(str, Enum):
    """Mutually exclusive V1 terminal administrator roles."""

    CLARIFIER = "clarifier"
    ESCALATOR = "escalator"
