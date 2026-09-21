"""Run one controlled Step 6 ProjectProfileBuilder case by number.

The cases contain predefined request, extraction, and normalization inputs.
This script calls no extractor, taxonomy normalizer, repository, or LLM.
"""

import argparse
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from project_catalog_agent.catalog.contracts import (
    ContractModel,
    CreateProjectRequest,
    MappingStatus,
    ProficiencyLevel,
    ProjectProfile,
    RequirementExtractionResult,
    RequirementImportance,
    TaxonomyNormalizationResult,
)
from project_catalog_agent.errors import ProjectProfileBuildError
from project_catalog_agent.profile import (
    ArtifactRecordingProjectProfileBuilder,
    ProfileArtifactWriter,
    ProjectProfileBuilder,
)

DEFAULT_CASES_PATH = Path("tests/manual/profile_build_cases.json")


class ExpectedRequirement(ContractModel):
    """Expected aggregate fields for one built project requirement."""

    skill_id: str
    canonical_skill: str | None = None
    importance: RequirementImportance
    required_level: ProficiencyLevel | None
    provenance_count: int = Field(ge=0)
    provenance_raw_skills: list[str] = Field(default_factory=list)


class ExpectedBuildResult(ContractModel):
    """Expected profile or build-error outcome."""

    result_type: Literal["profile", "error"]
    requirement_count: int | None = Field(default=None, ge=0)
    requirement_order: list[str] = Field(default_factory=list)
    requirements: list[ExpectedRequirement] = Field(default_factory=list)
    unresolved_skills: list[str] = Field(default_factory=list)
    unresolved_statuses: list[MappingStatus] = Field(default_factory=list)
    error_type: str | None = None
    error_reason: str | None = None


class ManualProfileBuildCase(ContractModel):
    """One complete controlled Step 6 case."""

    case_id: str
    description: str
    request: CreateProjectRequest
    extraction_result: RequirementExtractionResult
    normalization_result: TaxonomyNormalizationResult
    expected: ExpectedBuildResult


def parse_arguments() -> argparse.Namespace:
    """Parse optional case-file and non-interactive selection arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--case", type=int, help="case number to run")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/profile"),
        help="directory for successful profile artifacts",
    )
    return parser.parse_args()


def load_cases(path: Path) -> list[ManualProfileBuildCase]:
    """Load and validate the controlled JSON cases."""
    return [
        ManualProfileBuildCase.model_validate(item)
        for item in json.loads(path.read_text(encoding="utf-8"))
    ]


def select_case(
    cases: list[ManualProfileBuildCase],
    case_number: int | None,
) -> ManualProfileBuildCase:
    """Select one case by number, prompting until the input is valid."""
    if case_number is not None and not 1 <= case_number <= len(cases):
        msg = f"case number must be between 1 and {len(cases)}"
        raise ValueError(msg)
    if case_number is None:
        print("Select one Step 6 profile-builder case:")
        for index, build_case in enumerate(cases, start=1):
            print(f"  {index}. {build_case.case_id} — {build_case.description}")
        while case_number is None:
            raw_value = input(f"Enter a number (1-{len(cases)}): ").strip()
            if raw_value.isdigit() and 1 <= int(raw_value) <= len(cases):
                case_number = int(raw_value)
            else:
                print("Invalid selection. Please enter one listed number.")
    return cases[case_number - 1]


def compare_profile(
    profile: ProjectProfile,
    expected: ExpectedBuildResult,
) -> list[str]:
    """Return readable mismatches between a profile and expected fields."""
    mismatches: list[str] = []
    if expected.result_type != "profile":
        return ["expected an error, but the builder returned a profile"]
    if len(profile.requirements) != expected.requirement_count:
        mismatches.append(
            f"requirement_count expected={expected.requirement_count} "
            f"actual={len(profile.requirements)}"
        )
    actual_order = [item.skill_id for item in profile.requirements]
    if actual_order != expected.requirement_order:
        mismatches.append(
            f"requirement_order expected={expected.requirement_order} "
            f"actual={actual_order}"
        )
    if profile.unresolved_skills != expected.unresolved_skills:
        mismatches.append(
            f"unresolved_skills expected={expected.unresolved_skills} "
            f"actual={profile.unresolved_skills}"
        )
    actual_statuses = [item.mapping_status for item in profile.unresolved_requirements]
    if actual_statuses != expected.unresolved_statuses:
        mismatches.append(
            "unresolved_statuses "
            f"expected={[item.value for item in expected.unresolved_statuses]} "
            f"actual={[item.value for item in actual_statuses]}"
        )

    for index, expected_requirement in enumerate(expected.requirements):
        if index >= len(profile.requirements):
            mismatches.append(f"missing requirement at position {index}")
            continue
        actual = profile.requirements[index]
        fields = {
            "skill_id": (actual.skill_id, expected_requirement.skill_id),
            "importance": (actual.importance, expected_requirement.importance),
            "required_level": (
                actual.required_level,
                expected_requirement.required_level,
            ),
            "provenance_count": (
                len(actual.provenance),
                expected_requirement.provenance_count,
            ),
        }
        if expected_requirement.canonical_skill is not None:
            fields["canonical_skill"] = (
                actual.canonical_name,
                expected_requirement.canonical_skill,
            )
        for field_name, (actual_value, expected_value) in fields.items():
            if actual_value != expected_value:
                mismatches.append(
                    f"requirement[{index}].{field_name} "
                    f"expected={expected_value} actual={actual_value}"
                )
        if expected_requirement.provenance_raw_skills:
            actual_raw_skills = [item.raw_skill for item in actual.provenance]
            if actual_raw_skills != expected_requirement.provenance_raw_skills:
                mismatches.append(
                    f"requirement[{index}].provenance_raw_skills "
                    f"expected={expected_requirement.provenance_raw_skills} "
                    f"actual={actual_raw_skills}"
                )
    return mismatches


def compare_error(error: Exception, expected: ExpectedBuildResult) -> list[str]:
    """Return mismatches between an exception and expected error details."""
    mismatches: list[str] = []
    if expected.result_type != "error":
        return [f"expected a profile, but builder raised {type(error).__name__}"]
    if type(error).__name__ != expected.error_type:
        mismatches.append(
            f"error_type expected={expected.error_type} actual={type(error).__name__}"
        )
    if expected.error_reason and str(error) != expected.error_reason:
        mismatches.append(
            f"error_reason expected={expected.error_reason!r} actual={str(error)!r}"
        )
    return mismatches


def run_case(build_case: ManualProfileBuildCase, output: Path) -> bool:
    """Run one case, print its output, and return whether it matched."""
    print(f"\n--- {build_case.case_id}: {build_case.description} ---")
    runner = ArtifactRecordingProjectProfileBuilder(
        builder=ProjectProfileBuilder(),
        artifact_writer=ProfileArtifactWriter(output),
    )
    try:
        recorded = runner.build(
            request=build_case.request,
            extraction=build_case.extraction_result,
            normalization=build_case.normalization_result,
        )
    except ProjectProfileBuildError as error:
        mismatches = compare_error(error, build_case.expected)
        print(f"Builder error: {type(error).__name__}: {error}")
        print(f"Result: {'PASS' if not mismatches else 'FAIL'}")
        for mismatch in mismatches:
            print(f"  - {mismatch}")
        return not mismatches

    mismatches = compare_profile(recorded.profile, build_case.expected)
    print(recorded.profile.model_dump_json(indent=2, exclude_none=True))
    print(f"Artifact: {recorded.artifact_path}")
    print(f"Result: {'PASS' if not mismatches else 'FAIL'}")
    for mismatch in mismatches:
        print(f"  - {mismatch}")
    return not mismatches


def main() -> int:
    """Load, select, and run exactly one controlled profile-builder case."""
    arguments = parse_arguments()
    build_case = select_case(load_cases(arguments.cases), arguments.case)
    return 0 if run_case(build_case, arguments.output) else 1


if __name__ == "__main__":
    raise SystemExit(main())
