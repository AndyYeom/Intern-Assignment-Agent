"""Tests for the OpenAI structured-output adapter without live API calls."""

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest
from openai import AsyncOpenAI

from project_catalog_agent.catalog.contracts import RequirementExtractionResult
from project_catalog_agent.errors import (
    RequirementExtractionConfigurationError,
    RequirementExtractionError,
    RequirementExtractionResponseError,
)
from project_catalog_agent.llm import OpenAIStructuredLLMClient


class FakeResponses:
    """Controlled replacement for the SDK Responses resource."""

    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeOpenAI:
    """Minimal fake matching the SDK surface used by the adapter."""

    def __init__(self, response: object) -> None:
        self.responses = FakeResponses(response)


def make_result() -> RequirementExtractionResult:
    """Build an empty structured extraction result."""
    return RequirementExtractionResult(
        project_summary="A documentation project.",
        requirements=[],
    )


def make_client(response: object) -> tuple[OpenAIStructuredLLMClient, FakeOpenAI]:
    """Build an adapter around the fake SDK client."""
    fake = FakeOpenAI(response)
    adapter = OpenAIStructuredLLMClient(
        api_key=None,
        model="gpt-4o-mini",
        client=cast(AsyncOpenAI, fake),
    )
    return adapter, fake


def generate(client: OpenAIStructuredLLMClient) -> RequirementExtractionResult:
    """Call the adapter with fixed prompts and response model."""
    return asyncio.run(
        client.generate_structured(
            system_prompt="system",
            user_prompt="user",
            response_model=RequirementExtractionResult,
        )
    )


def test_adapter_returns_revalidated_structured_output() -> None:
    expected = make_result()
    response = SimpleNamespace(output=[], output_parsed=expected)
    client, fake = make_client(response)

    result = generate(client)

    assert result == expected
    assert result is not expected
    assert fake.responses.calls[0]["text_format"] is RequirementExtractionResult


def test_adapter_rejects_provider_refusal() -> None:
    refusal = SimpleNamespace(type="refusal", refusal="Cannot comply")
    message = SimpleNamespace(type="message", content=[refusal])
    response = SimpleNamespace(output=[message], output_parsed=None)
    client, _ = make_client(response)

    with pytest.raises(RequirementExtractionResponseError, match="refused"):
        generate(client)


def test_adapter_rejects_empty_output() -> None:
    response = SimpleNamespace(output=[], output_parsed=None)
    client, _ = make_client(response)

    with pytest.raises(RequirementExtractionResponseError, match="empty"):
        generate(client)


def test_adapter_rejects_malformed_parsed_output() -> None:
    parsed = SimpleNamespace(
        model_dump=lambda: {
            "project_summary": "Summary",
            "requirements": [],
            "unexpected": True,
        }
    )
    response = SimpleNamespace(output=[], output_parsed=parsed)
    client, _ = make_client(response)

    with pytest.raises(RequirementExtractionResponseError) as error_info:
        generate(client)

    assert error_info.value.__cause__ is not None


def test_adapter_wraps_provider_failure() -> None:
    provider_error = RuntimeError("network unavailable")
    client, _ = make_client(provider_error)

    with pytest.raises(RequirementExtractionError) as error_info:
        generate(client)

    assert error_info.value.__cause__ is provider_error


@pytest.mark.parametrize(
    ("api_key", "model"),
    [(None, "gpt-4o-mini"), ("test-key", "   ")],
)
def test_missing_provider_configuration_is_rejected(
    api_key: str | None,
    model: str,
) -> None:
    with pytest.raises(RequirementExtractionConfigurationError):
        OpenAIStructuredLLMClient(api_key=api_key, model=model)


def test_package_import_does_not_require_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    from project_catalog_agent import extraction

    assert extraction.LLMRequirementExtractor is not None
