"""Tests for the LLM gateway structured-output adapter without live calls."""

import asyncio
from types import SimpleNamespace

import pytest

from project_catalog_agent.catalog.contracts import RequirementExtractionResult
from project_catalog_agent.errors import (
    RequirementExtractionConfigurationError,
    RequirementExtractionError,
    RequirementExtractionResponseError,
)
from project_catalog_agent.llm import GatewayStructuredLLMClient

VALID = RequirementExtractionResult.model_validate(
    {
        "project_summary": "Build a small Python app.",
        "requirements": [
            {
                "raw_skill": "Python",
                "importance": "hard_requirement",
                "required_level": 1,
                "confidence": 0.9,
                "evidence_text": "Build a small Python app.",
                "decision_basis": "Stated directly.",
            }
        ],
    }
)


class FakeChat:
    """Returns queued replies; records every message list it receives."""

    def __init__(self, *replies: object) -> None:
        self.replies = list(replies)
        self.calls: list[list[tuple[str, str]]] = []

    async def ainvoke(self, messages):
        self.calls.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(content=reply)


def generate(client):
    return asyncio.run(
        client.generate_structured(
            system_prompt="Extract requirements.",
            user_prompt="Build a small Python app.",
            response_model=RequirementExtractionResult,
        )
    )


def test_parses_json_and_sends_schema():
    llm = FakeChat(VALID.model_dump_json())
    assert generate(GatewayStructuredLLMClient(llm=llm)) == VALID
    system = llm.calls[0][0][1]
    assert "Extract requirements." in system
    assert "project_summary" in system


def test_accepts_fenced_json_and_block_content():
    fenced = f"```json\n{VALID.model_dump_json()}\n```"
    llm = FakeChat([{"type": "text", "text": fenced}])
    assert generate(GatewayStructuredLLMClient(llm=llm)) == VALID


def test_reasks_after_invalid_output():
    llm = FakeChat("not json", VALID.model_dump_json())
    assert generate(GatewayStructuredLLMClient(llm=llm)) == VALID
    assert len(llm.calls) == 2
    assert llm.calls[1][-1][0] == "human"
    assert "did not validate" in llm.calls[1][-1][1]


def test_gives_up_after_max_attempts():
    llm = FakeChat("{}", "{}")
    with pytest.raises(RequirementExtractionResponseError):
        generate(GatewayStructuredLLMClient(llm=llm, max_attempts=2))


def test_wraps_gateway_failure():
    llm = FakeChat(ConnectionError("down"))
    with pytest.raises(RequirementExtractionError):
        generate(GatewayStructuredLLMClient(llm=llm))


def test_missing_configuration(monkeypatch):
    for name in ("LLM_GATEWAY_URL", "LLM_GATEWAY_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RequirementExtractionConfigurationError):
        GatewayStructuredLLMClient.from_environment()


def test_ignores_text_after_the_first_object():
    reply = f"```json\n{VALID.model_dump_json()}\n```\nOn reflection:\n{{\"project_summary\": "
    llm = FakeChat(reply)
    assert generate(GatewayStructuredLLMClient(llm=llm)) == VALID
    assert len(llm.calls) == 1


def test_rejoins_an_answer_split_by_gateway_continuations():
    body = VALID.model_dump_json()
    cut = body.index('"requirements"')
    reply = f"```json\n{body[:cut]}```json\n{body[cut:]}```json\n{{}}"
    llm = FakeChat(reply)
    assert generate(GatewayStructuredLLMClient(llm=llm)) == VALID
    assert len(llm.calls) == 1
