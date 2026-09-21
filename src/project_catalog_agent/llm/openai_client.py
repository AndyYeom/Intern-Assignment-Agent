"""OpenAI adapter for provider-neutral structured generation."""

from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, SecretStr, ValidationError

from project_catalog_agent.config.settings import Settings
from project_catalog_agent.errors import (
    RequirementExtractionConfigurationError,
    RequirementExtractionError,
    RequirementExtractionResponseError,
)

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class OpenAIStructuredLLMClient:
    """Generate Pydantic-validated output with the OpenAI Responses API."""

    def __init__(
        self,
        *,
        api_key: SecretStr | str | None,
        model: str,
        client: AsyncOpenAI | None = None,
    ) -> None:
        """Configure the adapter without making an API request."""
        model_name = model.strip()
        if not model_name:
            msg = "OpenAI model configuration is missing"
            raise RequirementExtractionConfigurationError(msg)

        if client is None:
            key = (
                api_key.get_secret_value()
                if isinstance(api_key, SecretStr)
                else api_key
            )
            if key is None or not key.strip():
                msg = "OpenAI API key configuration is missing"
                raise RequirementExtractionConfigurationError(msg)
            client = AsyncOpenAI(api_key=key)

        self._client = client
        self._model = model_name

    @classmethod
    def from_settings(cls, settings: Settings) -> "OpenAIStructuredLLMClient":
        """Create an adapter from application settings."""
        return cls(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredModel],
    ) -> StructuredModel:
        """Request and validate structured output from OpenAI."""
        try:
            response = await self._client.responses.parse(
                model=self._model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                text_format=response_model,
            )
        except Exception as error:
            msg = "OpenAI structured-output request failed"
            raise RequirementExtractionError(msg) from error

        for output in response.output:
            if output.type == "message":
                for content in output.content:
                    if content.type == "refusal":
                        msg = "OpenAI refused the structured-output request"
                        raise RequirementExtractionResponseError(msg)

        parsed = response.output_parsed
        if parsed is None:
            msg = "OpenAI returned empty structured output"
            raise RequirementExtractionResponseError(msg)

        try:
            return response_model.model_validate(parsed.model_dump())
        except ValidationError as error:
            msg = "OpenAI returned invalid structured output"
            raise RequirementExtractionResponseError(msg) from error
