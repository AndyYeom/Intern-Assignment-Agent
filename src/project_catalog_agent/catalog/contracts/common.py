"""Shared types for catalog domain contracts."""

from enum import Enum, IntEnum

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Base model for all catalog contracts."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class RequirementImportance(str, Enum):
    """Importance assigned to a project requirement."""

    HARD_REQUIREMENT = "hard_requirement"
    PREFERRED = "preferred"
    LEARNING_OPPORTUNITY = "learning_opportunity"


class ProficiencyLevel(IntEnum):
    """Shared proficiency levels used by project requirements."""

    ENTRY = 1
    INTERMEDIATE = 2
    ADVANCED = 3


class MatchMethod(str, Enum):
    """Method used to map a raw skill to the taxonomy."""

    EXACT = "exact"
    ALIAS = "alias"
    SEMANTIC = "semantic"
    LLM_SELECTED = "llm_selected"
    CLARIFIED = "clarified"
    UNRESOLVED = "unresolved"


class MappingStatus(str, Enum):
    """Outcome of mapping an extracted skill to the shared taxonomy."""

    RESOLVED = "resolved"
    NEEDS_REVIEW = "needs_review"
    UNMAPPED = "unmapped"


class IssueSeverity(str, Enum):
    """Severity of a validation issue."""

    WARNING = "warning"
    BLOCKING = "blocking"


class IssueCategory(str, Enum):
    """Category of a validation issue."""

    INVALID_VALUE = "invalid_value"
    MISSING_INFORMATION = "missing_information"
    AMBIGUITY = "ambiguity"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    PERMISSION = "permission"
    SYSTEM_ERROR = "system_error"


class AnswerType(str, Enum):
    """Expected form of an answer to a clarification question."""

    FREE_TEXT = "free_text"
    SINGLE_CHOICE = "single_choice"
    INTEGER = "integer"


class CatalogResultStatus(str, Enum):
    """Final state represented by a catalog result."""

    COMPLETED = "completed"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    ESCALATED = "escalated"
    FAILED = "failed"
