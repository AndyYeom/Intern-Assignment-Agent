"""Top-level catalog operation result contract."""

from typing import Annotated, Self

from pydantic import Field, model_validator

from project_catalog_agent.catalog.contracts.clarification import (
    ClarificationQuestion,
)
from project_catalog_agent.catalog.contracts.common import (
    CatalogResultStatus,
    ContractModel,
)
from project_catalog_agent.catalog.contracts.profile import ProjectProfile
from project_catalog_agent.catalog.contracts.validation import ValidationIssue


class CatalogResult(ContractModel):
    """Outcome returned by the project catalog process."""

    request_id: Annotated[str, Field(min_length=1, max_length=100)]
    status: CatalogResultStatus
    project_profile: ProjectProfile | None = None
    project_id: str | None = None
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    clarification_questions: list[ClarificationQuestion] = Field(default_factory=list)
    message: str | None = None

    @model_validator(mode="after")
    def validate_status_requirements(self) -> Self:
        """Ensure required data is present for the selected status."""
        if (
            self.status is CatalogResultStatus.COMPLETED
            and self.project_profile is None
        ):
            msg = "completed results require a project profile"
            raise ValueError(msg)
        if (
            self.status is CatalogResultStatus.AWAITING_CLARIFICATION
            and not self.clarification_questions
        ):
            msg = "awaiting-clarification results require a clarification question"
            raise ValueError(msg)
        if (
            self.status
            in {
                CatalogResultStatus.ESCALATED,
                CatalogResultStatus.FAILED,
            }
            and not self.message
        ):
            msg = f"{self.status.value} results require a message"
            raise ValueError(msg)
        return self
