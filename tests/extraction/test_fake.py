"""Tests for the deterministic fake requirement extractor."""

import asyncio

from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    RequirementExtractionResult,
)
from project_catalog_agent.extraction import FakeRequirementExtractor


def make_request(request_id: str = "req-001") -> CreateProjectRequest:
    """Build a valid extraction request."""
    return CreateProjectRequest(
        request_id=request_id,
        project_name="Recommendation Engine",
        project_description="Build a course recommendation engine.",
    )


def make_result() -> RequirementExtractionResult:
    """Build a deterministic empty extraction result."""
    return RequirementExtractionResult(
        project_summary="A course recommendation project.",
        requirements=[],
    )


def test_fake_extractor_returns_configured_result() -> None:
    expected = make_result()
    extractor = FakeRequirementExtractor(expected)

    result = asyncio.run(extractor.extract(make_request()))

    assert result == expected
    assert result is not expected


def test_fake_extractor_records_input_request() -> None:
    request = make_request()
    extractor = FakeRequirementExtractor(make_result())

    asyncio.run(extractor.extract(request))

    assert extractor.received_requests == [request]
    assert extractor.received_requests[0] is not request


def test_fake_extractor_instances_do_not_share_mutable_state() -> None:
    first = FakeRequirementExtractor(make_result())
    second = FakeRequirementExtractor(make_result())

    asyncio.run(first.extract(make_request("req-first")))

    assert len(first.received_requests) == 1
    assert second.received_requests == []
