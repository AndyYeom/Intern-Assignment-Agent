"""External project creation request contract."""

from typing import Annotated

from pydantic import Field

from project_catalog_agent.catalog.contracts.common import ContractModel


class CreateProjectRequest(ContractModel):
    """A new project submission received by the catalog agent."""

    request_id: Annotated[str, Field(min_length=1, max_length=100)]
    project_name: Annotated[str, Field(min_length=1, max_length=200)]
    project_description: Annotated[str, Field(min_length=1, max_length=20_000)]
