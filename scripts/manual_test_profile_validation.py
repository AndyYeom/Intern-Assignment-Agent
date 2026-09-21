"""Run one or all controlled Step 7 ProjectProfileValidator cases.

Enter 0 to run every case or select a one-based case index. This script is
deterministic and calls no extractor, normalizer, builder, LLM, or external API.
"""

import argparse
from pathlib import Path
from runpy import run_path
from typing import cast

from project_catalog_agent.catalog.contracts import ContractModel, ProjectProfile
from project_catalog_agent.profile import ProjectProfileValidator
from project_catalog_agent.taxonomy import JsonTaxonomyRepository

DEFAULT_CASES_PATH = Path("tests/manual/profile_validation_cases.py")


class ManualValidationCase(ContractModel):
    """One controlled profile and its expected validation result."""

    name: str
    expected_valid: bool
    expected_codes: list[str]
    payload: ProjectProfile


def parse_arguments() -> argparse.Namespace:
    """Parse the optional non-interactive case index."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument(
        "--case",
        type=int,
        help="case index to run; use 0 to run all cases",
    )
    return parser.parse_args()


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[ManualValidationCase]:
    """Validate and return the supplied manual cases."""
    namespace = run_path(str(path))
    raw_cases = cast(list[object], namespace["TEST_CASES"])
    return [ManualValidationCase.model_validate(item) for item in raw_cases]


def select_cases(
    cases: list[ManualValidationCase],
    case_index: int | None,
) -> list[ManualValidationCase]:
    """Select all cases for zero or one case by its one-based index."""
    if case_index is not None and not 0 <= case_index <= len(cases):
        msg = f"case index must be between 0 and {len(cases)}"
        raise ValueError(msg)
    if case_index is None:
        print("Select a Step 7 validation case:")
        print("  0. Run all cases")
        for index, validation_case in enumerate(cases, start=1):
            print(f"  {index}. {validation_case.name}")
        while case_index is None:
            raw_value = input(f"Enter a number (0-{len(cases)}): ").strip()
            if raw_value.isdigit() and 0 <= int(raw_value) <= len(cases):
                case_index = int(raw_value)
            else:
                print("Invalid selection. Please enter one listed number.")
    return cases if case_index == 0 else [cases[case_index - 1]]


def run_case(
    validation_case: ManualValidationCase,
    validator: ProjectProfileValidator,
) -> bool:
    """Validate one case, print its report, and return whether it matched."""
    result = validator.validate(validation_case.payload)
    actual_codes = [issue.code for issue in result.issues]
    passed = (
        result.valid is validation_case.expected_valid
        and actual_codes == validation_case.expected_codes
    )
    print(f"\n--- {validation_case.name} ---")
    print(result.model_dump_json(indent=2))
    print(f"Expected valid: {validation_case.expected_valid}")
    print(f"Expected codes: {validation_case.expected_codes}")
    print(f"Actual valid:   {result.valid}")
    print(f"Actual codes:   {actual_codes}")
    print(f"Result: {'PASS' if passed else 'FAIL'}")
    return passed


def main() -> int:
    """Run the selected cases and return a shell-friendly status code."""
    arguments = parse_arguments()
    selected_cases = select_cases(load_cases(arguments.cases), arguments.case)
    validator = ProjectProfileValidator(taxonomy_repository=JsonTaxonomyRepository())
    results = [
        run_case(validation_case, validator) for validation_case in selected_cases
    ]
    passed_count = sum(results)
    print("\nSummary")
    print(f"  Passed: {passed_count}")
    print(f"  Failed: {len(results) - passed_count}")
    print(f"  Total:  {len(results)}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
