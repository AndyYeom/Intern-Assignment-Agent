"""Validation outcomes for the supplied BUILD manual cases."""

from pathlib import Path

import pytest
from scripts.manual_test_profile_builder import load_cases

from project_catalog_agent.errors import ProjectProfileBuildError
from project_catalog_agent.profile import ProjectProfileBuilder, ProjectProfileValidator
from project_catalog_agent.taxonomy import JsonTaxonomyRepository


@pytest.mark.parametrize(
    ("case_number", "expected_valid", "expected_codes"),
    [
        (1, True, []),
        (2, True, []),
        (3, False, ["UNMAPPED_REQUIREMENT", "NEEDS_REVIEW_REQUIREMENT"]),
        (4, True, []),
    ],
)
def test_manual_build_profile_validation_outcomes(
    case_number: int,
    expected_valid: bool,
    expected_codes: list[str],
) -> None:
    build_case = load_cases(Path("tests/manual/profile_build_cases.json"))[
        case_number - 1
    ]
    profile = ProjectProfileBuilder().build(
        request=build_case.request,
        extraction=build_case.extraction_result,
        normalization=build_case.normalization_result,
    )

    result = ProjectProfileValidator(
        taxonomy_repository=JsonTaxonomyRepository()
    ).validate(profile)

    assert result.valid is expected_valid
    assert [issue.code for issue in result.issues] == expected_codes


def test_build_005_fails_before_validation() -> None:
    build_case = load_cases(Path("tests/manual/profile_build_cases.json"))[4]

    with pytest.raises(ProjectProfileBuildError):
        ProjectProfileBuilder().build(
            request=build_case.request,
            extraction=build_case.extraction_result,
            normalization=build_case.normalization_result,
        )
