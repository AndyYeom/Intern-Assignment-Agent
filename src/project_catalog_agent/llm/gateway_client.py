"""LLM gateway adapter for provider-neutral structured generation.

Uses the same Ollama-compatible gateway as the profile and evidence agents
(LLM_GATEWAY_URL, LLM_GATEWAY_API_KEY, LLM_MODEL), so the catalog agent can
run without an OpenAI key.
"""

import json
import os
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from project_catalog_agent.errors import (
    RequirementExtractionConfigurationError,
    RequirementExtractionError,
    RequirementExtractionResponseError,
)

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)

GATEWAY_SETTINGS = ("LLM_GATEWAY_URL", "LLM_GATEWAY_API_KEY", "LLM_MODEL")


def gateway_configured() -> bool:
    """Return whether every gateway setting is present in the environment."""
    return all(os.getenv(name, "").strip() for name in GATEWAY_SETTINGS)


def _message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def _first_json_object(text: str) -> str:
    """Return the first complete JSON object in ``text``.

    Gateway models sometimes wrap the object in code fences or keep writing
    after it; only the first object is the answer.
    """
    start = text.find("{")
    if start == -1:
        return text
    try:
        obj, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError:
        return text[start:]
    return json.dumps(obj)


class GatewayStructuredLLMClient:
    """Generate Pydantic-validated output through the shared LLM gateway."""

    def __init__(self, *, llm: Any, max_attempts: int = 3) -> None:
        """Wrap a LangChain chat model; no request is made here."""
        if max_attempts < 1:
            msg = "max_attempts must be at least 1"
            raise ValueError(msg)
        self._llm = llm
        self._max_attempts = max_attempts

    @classmethod
    def from_environment(cls) -> "GatewayStructuredLLMClient":
        """Create an adapter from the LLM_* gateway settings."""
        missing = [name for name in GATEWAY_SETTINGS if not os.getenv(name, "").strip()]
        if missing:
            msg = "Missing gateway configuration: " + ", ".join(missing)
            raise RequirementExtractionConfigurationError(msg)

        from langchain_ollama import ChatOllama

        llm = ChatOllama(
            model=os.environ["LLM_MODEL"].strip(),
            base_url=os.environ["LLM_GATEWAY_URL"].strip(),
            temperature=0.0,
            num_predict=2500,
            client_kwargs={
                "headers": {"X-API-Key": os.environ["LLM_GATEWAY_API_KEY"].strip()}
            },
        )
        return cls(llm=llm)

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredModel],
    ) -> StructuredModel:
        """Request JSON matching ``response_model``; re-ask on invalid output."""
        schema = json.dumps(response_model.model_json_schema())
        messages = [
            (
                "system",
                f"{system_prompt}\n\nRespond with one JSON object only, no prose "
                f"and no code fences, matching this JSON schema:\n{schema}",
            ),
            ("human", user_prompt),
        ]
        error: Exception | None = None
        for _ in range(self._max_attempts):
            try:
                message = await self._llm.ainvoke(messages)
            except Exception as exc:
                msg = "Gateway structured-output request failed"
                raise RequirementExtractionError(msg) from exc

            text = _message_text(message)
            try:
                return response_model.model_validate_json(_first_json_object(text))
            except ValidationError as exc:
                error = exc
                messages = [
                    *messages,
                    ("ai", text),
                    (
                        "human",
                        "That output did not validate against the schema:\n"
                        f"{exc}\nReturn the corrected JSON object only.",
                    ),
                ]

        msg = "Gateway returned invalid structured output"
        raise RequirementExtractionResponseError(msg) from error
