"""Structured LLM-backed requirement extraction."""

from pydantic import BaseModel, ValidationError

from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    RequirementExtractionResult,
)
from project_catalog_agent.errors import (
    RequirementExtractionConfigurationError,
    RequirementExtractionError,
    RequirementExtractionResponseError,
)
from project_catalog_agent.extraction.prompts import (
    REQUIREMENT_IMPORTANCE_DEFINITIONS,
    build_system_prompt,
    build_user_prompt,
)
from project_catalog_agent.llm import StructuredLLMClient
from project_catalog_agent.resources import load_proficiency_taxonomy


class LLMRequirementExtractor:
    """Extract requirements through a provider-neutral structured LLM client."""

    def __init__(
        self,
        client: StructuredLLMClient,
        *,
        proficiency_taxonomy: str | None = None,
        requirement_importance: str = REQUIREMENT_IMPORTANCE_DEFINITIONS,
    ) -> None:
        """Configure extraction prompts and the injected structured client."""
        taxonomy = (
            load_proficiency_taxonomy()
            if proficiency_taxonomy is None
            else proficiency_taxonomy
        )
        if not taxonomy:
            msg = "shared proficiency taxonomy is empty"
            raise RequirementExtractionConfigurationError(msg)
        if not requirement_importance.strip():
            msg = "requirement importance definitions are empty"
            raise RequirementExtractionConfigurationError(msg)

        self._client = client
        self._system_prompt = build_system_prompt(
            proficiency_taxonomy=taxonomy,
            requirement_importance=requirement_importance,
        )

    async def extract(
        self,
        request: CreateProjectRequest,
    ) -> RequirementExtractionResult:
        """Validate input, request structured output, and validate the response."""
        try:
            validated_request = CreateProjectRequest.model_validate(
                request.model_dump()
            )
        except ValidationError as error:
            msg = "requirement extraction request is invalid"
            raise RequirementExtractionError(msg) from error

        try:
            generated: object = await self._client.generate_structured(
                system_prompt=self._system_prompt,
                user_prompt=build_user_prompt(validated_request),
                response_model=RequirementExtractionResult,
            )
        except (
            RequirementExtractionConfigurationError,
            RequirementExtractionResponseError,
        ):
            raise
        except Exception as error:
            msg = "requirement extraction provider request failed"
            raise RequirementExtractionError(msg) from error

        if generated is None:
            msg = "requirement extraction provider returned empty output"
            raise RequirementExtractionResponseError(msg)

        payload = (
            generated.model_dump() if isinstance(generated, BaseModel) else generated
        )
        try:
            return RequirementExtractionResult.model_validate(payload)
        except ValidationError as error:
            msg = "requirement extraction provider returned invalid structured output"
            raise RequirementExtractionResponseError(msg) from error
