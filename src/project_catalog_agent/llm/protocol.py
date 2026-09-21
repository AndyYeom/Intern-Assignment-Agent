"""Provider-neutral structured language-model interface."""

from typing import Protocol, TypeVar

from pydantic import BaseModel

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class StructuredLLMClient(Protocol):
    """Generate a response validated against a Pydantic model."""

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredModel],
    ) -> StructuredModel:
        """Return provider output parsed as ``response_model``."""
        ...
