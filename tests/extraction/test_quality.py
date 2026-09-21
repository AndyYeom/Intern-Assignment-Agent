"""Tests for deterministic extraction quality warnings."""

from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    ExtractedRequirement,
    IssueSeverity,
    ProficiencyLevel,
    RequirementExtractionResult,
    RequirementImportance,
)
from project_catalog_agent.extraction import (
    ExtractionQualityChecker,
    ExtractionQualityIssueCode,
)


def make_request(description: str) -> CreateProjectRequest:
    """Build a valid project request."""
    return CreateProjectRequest(
        request_id="REQ-QUALITY-001",
        project_name="Quality Test",
        project_description=description,
    )


def make_requirement(
    *,
    raw_skill: str = "Python",
    importance: RequirementImportance = RequirementImportance.HARD_REQUIREMENT,
    evidence_text: str = "Python is required.",
) -> ExtractedRequirement:
    """Build a valid extracted requirement."""
    return ExtractedRequirement(
        raw_skill=raw_skill,
        importance=importance,
        required_level=ProficiencyLevel.INTERMEDIATE,
        evidence_text=evidence_text,
        decision_basis="The mandatory work requires independent implementation.",
        confidence=0.9,
    )


def make_result(
    requirements: list[ExtractedRequirement],
) -> RequirementExtractionResult:
    """Build a validated extraction result."""
    return RequirementExtractionResult(
        project_summary="A quality-check test project.",
        requirements=requirements,
    )


def issue_codes(
    request: CreateProjectRequest,
    result: RequirementExtractionResult,
) -> list[str]:
    """Return issue codes emitted for a request and result."""
    return [issue.code for issue in ExtractionQualityChecker().check(request, result)]


def test_verbatim_evidence_produces_no_warning() -> None:
    request = make_request("Python is required.")
    result = make_result([make_requirement()])

    assert issue_codes(request, result) == []


def test_non_verbatim_evidence_is_reported() -> None:
    request = make_request("Python is required for the backend.")
    result = make_result(
        [make_requirement(evidence_text="Python is definitely required.")]
    )

    assert issue_codes(request, result) == [
        ExtractionQualityIssueCode.EVIDENCE_NOT_VERBATIM.value
    ]


def test_raw_skill_level_modifier_is_reported() -> None:
    request = make_request("Strong Python is required.")
    result = make_result(
        [
            make_requirement(
                raw_skill="Strong Python",
                evidence_text="Strong Python is required.",
            )
        ]
    )

    assert issue_codes(request, result) == [
        ExtractionQualityIssueCode.RAW_SKILL_CONTAINS_LEVEL_MODIFIER.value
    ]


def test_unsupported_learning_opportunity_is_reported() -> None:
    request = make_request("Students will use RAG to answer questions.")
    result = make_result(
        [
            make_requirement(
                raw_skill="RAG",
                importance=RequirementImportance.LEARNING_OPPORTUNITY,
                evidence_text="Students will use RAG to answer questions.",
            )
        ]
    )

    assert issue_codes(request, result) == [
        ExtractionQualityIssueCode.LEARNING_OPPORTUNITY_NOT_SUPPORTED.value
    ]


def test_explicit_learning_language_is_supported() -> None:
    evidence = "During the project, students will learn RAG."
    request = make_request(evidence)
    result = make_result(
        [
            make_requirement(
                raw_skill="RAG",
                importance=RequirementImportance.LEARNING_OPPORTUNITY,
                evidence_text=evidence,
            )
        ]
    )

    assert issue_codes(request, result) == []


def test_possible_action_phrase_fragmentation_is_reported() -> None:
    description = "Profile the service and compare optimization trade-offs."
    request = make_request(description)
    result = make_result(
        [
            make_requirement(
                raw_skill="Profile the service",
                evidence_text="Profile the service",
            ),
            make_requirement(
                raw_skill="Compare optimization trade-offs",
                evidence_text="compare optimization trade-offs",
            ),
        ]
    )

    assert issue_codes(request, result) == [
        ExtractionQualityIssueCode.POSSIBLE_REQUIREMENT_FRAGMENTATION.value
    ]


def test_single_action_phrase_does_not_trigger_fragmentation_warning() -> None:
    request = make_request("Design REST APIs.")
    result = make_result(
        [
            make_requirement(
                raw_skill="Design REST APIs", evidence_text="Design REST APIs"
            )
        ]
    )

    assert issue_codes(request, result) == []


def test_quality_issues_are_structured_warnings() -> None:
    request = make_request("Python is required.")
    result = make_result([make_requirement(raw_skill="Advanced Python")])

    issues = ExtractionQualityChecker().check(request, result)

    assert issues[0].code == (
        ExtractionQualityIssueCode.RAW_SKILL_CONTAINS_LEVEL_MODIFIER.value
    )
    assert issues[0].severity is IssueSeverity.WARNING
    assert issues[0].field == "requirements.0.raw_skill"
    assert issues[0].message


def test_quality_checker_does_not_mutate_request_or_result() -> None:
    request = make_request("Python is required.")
    result = make_result([make_requirement(raw_skill="Strong Python")])
    request_before = request.model_dump()
    result_before = result.model_dump()

    ExtractionQualityChecker().check(request, result)

    assert request.model_dump() == request_before
    assert result.model_dump() == result_before
