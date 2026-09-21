"""Run normalization only for one of six controlled project cases.

The extraction results are predefined in the case file. This script never
calls RequirementExtractor; it calls the configured model only when the
normalizer cannot resolve a raw skill deterministically.
"""

import argparse
import asyncio
from pathlib import Path

from pydantic import Field

from project_catalog_agent.catalog.contracts import (
    ContractModel,
    CreateProjectRequest,
    RequirementExtractionResult,
)
from project_catalog_agent.config.settings import Settings
from project_catalog_agent.llm import OpenAIStructuredLLMClient
from project_catalog_agent.resources import load_proficiency_taxonomy_version
from project_catalog_agent.taxonomy import (
    ArtifactRecordingNormalizationRunner,
    HybridTaxonomyNormalizer,
    JsonTaxonomyRepository,
    LLMTaxonomyMappingSelector,
    NormalizationArtifactWriter,
)

DEFAULT_CASES_PATH = Path("tests/manual/normalization_project_cases.json")


class ManualProjectCase(ContractModel):
    """A project request paired with its controlled extraction result."""

    request: CreateProjectRequest
    extraction: RequirementExtractionResult


class ManualProjectCaseSuite(ContractModel):
    """Versioned collection of normalization-only project cases."""

    test_suite_version: str
    cases: list[ManualProjectCase] = Field(min_length=1)


def parse_arguments() -> argparse.Namespace:
    """Parse optional non-interactive case and model overrides."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--case", type=int, help="case number to run")
    parser.add_argument("--model", help="OpenAI model used for unresolved skills")
    return parser.parse_args()


def load_suite(path: Path) -> ManualProjectCaseSuite:
    """Load and validate controlled normalization cases."""
    return ManualProjectCaseSuite.model_validate_json(path.read_text(encoding="utf-8"))


def select_case(
    suite: ManualProjectCaseSuite,
    case_number: int | None,
) -> ManualProjectCase:
    """Select one case by number, prompting until the input is valid."""
    if case_number is not None and not 1 <= case_number <= len(suite.cases):
        msg = f"case number must be between 1 and {len(suite.cases)}"
        raise ValueError(msg)

    if case_number is None:
        print("Select one normalization-only project case:")
        for index, project_case in enumerate(suite.cases, start=1):
            request = project_case.request
            print(f"  {index}. {request.request_id} — {request.project_name}")
        while case_number is None:
            raw_value = input(f"Enter a number (1-{len(suite.cases)}): ").strip()
            if raw_value.isdigit() and 1 <= int(raw_value) <= len(suite.cases):
                case_number = int(raw_value)
            else:
                print("Invalid selection. Please enter one listed number.")

    return suite.cases[case_number - 1]


async def run(project_case: ManualProjectCase, *, model_override: str | None) -> None:
    """Normalize the controlled extraction and store its validated artifact."""
    settings = Settings()
    model_name = model_override or settings.openai_model
    client = OpenAIStructuredLLMClient(
        api_key=settings.openai_api_key,
        model=model_name,
    )
    repository = JsonTaxonomyRepository()
    normalizer = HybridTaxonomyNormalizer(
        repository,
        LLMTaxonomyMappingSelector(client),
    )
    runner = ArtifactRecordingNormalizationRunner(
        normalizer=normalizer,
        artifact_writer=NormalizationArtifactWriter(),
        extraction_model_name="controlled-manual-input",
        normalization_model_name=model_name,
        taxonomy_version=repository.version,
        proficiency_version=load_proficiency_taxonomy_version(),
    )

    request = project_case.request
    extraction = project_case.extraction
    print(f"\n--- {request.request_id}: {request.project_name} ---")
    print("Controlled extraction input (RequirementExtractor was not called):")
    print(extraction.model_dump_json(indent=2, exclude_none=True))

    recorded = await runner.run(request=request, extraction=extraction)
    print("\nNormalization result:")
    print(recorded.result.model_dump_json(indent=2, exclude_none=True))
    print(f"\nNormalization artifact: {recorded.artifact_path}")


def main() -> None:
    """Load, select, and run exactly one normalization-only project case."""
    arguments = parse_arguments()
    suite = load_suite(arguments.cases)
    project_case = select_case(suite, arguments.case)
    asyncio.run(run(project_case, model_override=arguments.model))


if __name__ == "__main__":
    main()
