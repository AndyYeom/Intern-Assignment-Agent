"""Run live structured requirement extraction against representative projects.

This is an opt-in manual test. It sends project names and descriptions to the
configured OpenAI model and may incur API usage charges.
"""

import asyncio
from argparse import ArgumentParser

from project_catalog_agent.catalog.contracts import CreateProjectRequest
from project_catalog_agent.config.settings import Settings
from project_catalog_agent.extraction import (
    ExtractionArtifactWriter,
    LLMRequirementExtractor,
)
from project_catalog_agent.llm import OpenAIStructuredLLMClient
from project_catalog_agent.resources import load_proficiency_taxonomy_version
from project_catalog_agent.taxonomy import (
    ArtifactRecordingNormalizationRunner,
    HybridTaxonomyNormalizer,
    JsonTaxonomyRepository,
    LLMTaxonomyMappingSelector,
    NormalizationArtifactWriter,
)

TEST_REQUESTS = [
    CreateProjectRequest(
        request_id="REQ-TEST-001",
        project_name="Student Project Matching Platform",
        project_description=(
            "Build a web platform that matches students with suitable "
            "industry projects. Students must independently implement the "
            "backend using Python and FastAPI, design REST APIs, and create "
            "a PostgreSQL database schema. They should be able to make normal "
            "architectural decisions without continuous supervision. React "
            "experience is helpful but not required because the existing "
            "frontend can be reused."
        ),
    ),
    CreateProjectRequest(
        request_id="REQ-TEST-002",
        project_name="Company Document Question-Answering Assistant",
        project_description=(
            "Develop an assistant that answers questions using internal "
            "company documents. Applicants should have basic Python experience "
            "before joining. During the project, students will learn "
            "retrieval-augmented generation, embeddings, vector search, and "
            "evaluation of LLM responses. Previous experience with RAG or "
            "vector databases is not required."
        ),
    ),
    CreateProjectRequest(
        request_id="REQ-TEST-003",
        project_name="Production Machine Learning Optimization",
        project_description=(
            "Improve an existing production machine-learning service that "
            "currently suffers from high inference latency and unstable memory "
            "usage. The student must profile the service, identify unfamiliar "
            "performance bottlenecks, compare optimization trade-offs, modify "
            "a codebase created by another engineering team, and explain why "
            "the selected solution is appropriate. Strong Python and "
            "machine-learning capability are required."
        ),
    ),
]


async def main(*, normalize: bool = False) -> None:
    """Extract and print requirements for each representative request."""
    settings = Settings()
    client = OpenAIStructuredLLMClient.from_settings(settings)
    extractor = LLMRequirementExtractor(client=client)
    artifact_writer = ExtractionArtifactWriter()
    taxonomy_repository = JsonTaxonomyRepository()
    taxonomy_version = taxonomy_repository.version
    proficiency_version = load_proficiency_taxonomy_version()
    normalizer = HybridTaxonomyNormalizer(
        repository=taxonomy_repository,
        selector=LLMTaxonomyMappingSelector(client),
    )
    normalization_writer = NormalizationArtifactWriter()
    normalization_runner = ArtifactRecordingNormalizationRunner(
        normalizer=normalizer,
        artifact_writer=normalization_writer,
        extraction_model_name=settings.openai_model,
        normalization_model_name=settings.openai_model,
        taxonomy_version=taxonomy_version,
        proficiency_version=proficiency_version,
    )

    for request in TEST_REQUESTS:
        print(f"\n--- {request.request_id}: {request.project_name} ---")
        result = await extractor.extract(request)
        print(result.model_dump_json(indent=2, exclude_none=True))
        artifact_path = artifact_writer.write(
            request=request,
            result=result,
            model_name=settings.openai_model,
            taxonomy_version=taxonomy_version,
            proficiency_version=proficiency_version,
        )
        print(f"Artifact: {artifact_path}")
        if normalize:
            recorded = await normalization_runner.run(
                request=request,
                extraction=result,
            )
            print(recorded.result.model_dump_json(indent=2, exclude_none=True))
            print(f"Normalization artifact: {recorded.artifact_path}")


def parse_arguments() -> bool:
    """Return whether optional live taxonomy normalization was requested."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--normalize",
        action="store_true",
        help="also map extracted skills using the configured OpenAI model",
    )
    arguments = parser.parse_args()
    return bool(arguments.normalize)


if __name__ == "__main__":
    asyncio.run(main(normalize=parse_arguments()))
