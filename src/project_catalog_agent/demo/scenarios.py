"""Deterministic terminal-demo scenarios and controlled artifacts."""

from dataclasses import dataclass
from enum import Enum

from project_catalog_agent.catalog.contracts import (
    CatalogDecisionPolicyConfig,
    CreateProjectRequest,
    ExtractedRequirement,
    MappingStatus,
    MatchMethod,
    ProficiencyLevel,
    RequirementExtractionResult,
    RequirementImportance,
    TaxonomyCandidate,
    TaxonomyMapping,
    TaxonomyNormalizationResult,
)


class DemoScenario(str, Enum):
    """Controlled terminal demonstration routes."""

    AMBIGUOUS_CLOUD = "ambiguous_cloud"
    MISSING_LEVEL = "missing_level"
    UNMAPPED_SKILL = "unmapped_skill"
    EXHAUSTED_RECOVERY = "exhausted_recovery"
    CUSTOM = "custom"


@dataclass(frozen=True)
class DemoScenarioBundle:
    """One request plus controlled upstream outputs and policy settings."""

    scenario: DemoScenario
    request: CreateProjectRequest
    extraction: RequirementExtractionResult
    normalization: TaxonomyNormalizationResult
    policy_config: CatalogDecisionPolicyConfig


def scenario_bundle(
    scenario: DemoScenario,
    *,
    request: CreateProjectRequest | None = None,
    custom_kind: str = "1",
) -> DemoScenarioBundle:
    """Build deterministic artifacts without branching in production services."""
    if scenario is DemoScenario.MISSING_LEVEL:
        return _missing_level(request)
    if scenario is DemoScenario.UNMAPPED_SKILL:
        return _unmapped(request)
    if scenario is DemoScenario.EXHAUSTED_RECOVERY:
        return _ambiguous_cloud(request, exhausted=True)
    if scenario is DemoScenario.CUSTOM:
        if custom_kind == "2":
            return _ambiguous_cloud(request, exhausted=False)
        if custom_kind == "3":
            return _missing_level(request)
        if custom_kind == "4":
            return _unmapped(request)
        return _valid_custom(request)
    return _ambiguous_cloud(request, exhausted=False)


def _valid_custom(request: CreateProjectRequest | None) -> DemoScenarioBundle:
    if request is None:
        raise ValueError("custom valid scenario requires a request")
    extraction = RequirementExtractionResult(
        project_summary="A controlled valid custom project.",
        requirements=[
            _requirement(
                "Python",
                request.project_description,
                RequirementImportance.HARD_REQUIREMENT,
                ProficiencyLevel.INTERMEDIATE,
            )
        ],
    )
    return DemoScenarioBundle(
        scenario=DemoScenario.CUSTOM,
        request=request,
        extraction=extraction,
        normalization=TaxonomyNormalizationResult(
            mappings=[_resolved(0, "Python", "python", "Python")]
        ),
        policy_config=CatalogDecisionPolicyConfig(),
    )


def _ambiguous_cloud(
    request: CreateProjectRequest | None,
    *,
    exhausted: bool,
) -> DemoScenarioBundle:
    actual_request = request or CreateProjectRequest(
        request_id="DEMO-CLOUD-001" if not exhausted else "DEMO-EXHAUSTED-001",
        project_name=(
            "Cloud Reporting Application"
            if not exhausted
            else "Exhausted Cloud Recovery"
        ),
        project_description=(
            "Build a reporting application using Python. The completed "
            "application may be deployed to AWS, Azure, or GCP."
        ),
    )
    description = actual_request.project_description
    extraction = RequirementExtractionResult(
        project_summary="Build and deploy a Python reporting application.",
        requirements=[
            _requirement(
                "Python",
                description,
                RequirementImportance.HARD_REQUIREMENT,
                ProficiencyLevel.INTERMEDIATE,
            ),
            _requirement(
                "AWS, Azure, or GCP",
                description,
                RequirementImportance.PREFERRED,
                ProficiencyLevel.ENTRY,
            ),
        ],
    )
    normalization = TaxonomyNormalizationResult(
        mappings=[
            _resolved(0, "Python", "python", "Python"),
            TaxonomyMapping(
                source_requirement_index=1,
                raw_skill="AWS, Azure, or GCP",
                status=MappingStatus.NEEDS_REVIEW,
                match_method=MatchMethod.UNRESOLVED,
                candidates=[
                    TaxonomyCandidate(skill_id="aws", canonical_name="AWS"),
                    TaxonomyCandidate(skill_id="gcp-azure", canonical_name="GCP/Azure"),
                ],
                decision_basis="The description names multiple cloud platforms.",
            ),
        ],
        unresolved_skills=["AWS, Azure, or GCP"],
    )
    config = CatalogDecisionPolicyConfig(
        max_clarification_requests_per_issue=0 if exhausted else 1
    )
    return DemoScenarioBundle(
        scenario=(
            DemoScenario.EXHAUSTED_RECOVERY
            if exhausted
            else DemoScenario.AMBIGUOUS_CLOUD
        ),
        request=actual_request,
        extraction=extraction,
        normalization=normalization,
        policy_config=config,
    )


def _missing_level(request: CreateProjectRequest | None) -> DemoScenarioBundle:
    actual_request = request or CreateProjectRequest(
        request_id="DEMO-LEVEL-001",
        project_name="Python Service Development",
        project_description="Python is required to implement the service.",
    )
    extraction = RequirementExtractionResult(
        project_summary="Implement a service using Python.",
        requirements=[
            _requirement(
                "Python",
                actual_request.project_description,
                RequirementImportance.HARD_REQUIREMENT,
                None,
            )
        ],
    )
    return DemoScenarioBundle(
        scenario=DemoScenario.MISSING_LEVEL,
        request=actual_request,
        extraction=extraction,
        normalization=TaxonomyNormalizationResult(
            mappings=[_resolved(0, "Python", "python", "Python")]
        ),
        policy_config=CatalogDecisionPolicyConfig(),
    )


def _unmapped(request: CreateProjectRequest | None) -> DemoScenarioBundle:
    actual_request = request or CreateProjectRequest(
        request_id="DEMO-UNMAPPED-001",
        project_name="Quantum Workflow Optimization",
        project_description=(
            "Students must use Python and Quantum Workflow Harmonization to "
            "optimize the application."
        ),
    )
    raw_skill = "Quantum Workflow Harmonization"
    extraction = RequirementExtractionResult(
        project_summary="Optimize an application using an unknown workflow skill.",
        requirements=[
            _requirement(
                "Python",
                actual_request.project_description,
                RequirementImportance.HARD_REQUIREMENT,
                ProficiencyLevel.INTERMEDIATE,
            ),
            _requirement(
                raw_skill,
                actual_request.project_description,
                RequirementImportance.HARD_REQUIREMENT,
                ProficiencyLevel.INTERMEDIATE,
            ),
        ],
    )
    return DemoScenarioBundle(
        scenario=DemoScenario.UNMAPPED_SKILL,
        request=actual_request,
        extraction=extraction,
        normalization=TaxonomyNormalizationResult(
            mappings=[
                _resolved(0, "Python", "python", "Python"),
                TaxonomyMapping(
                    source_requirement_index=1,
                    raw_skill=raw_skill,
                    status=MappingStatus.UNMAPPED,
                    match_method=MatchMethod.UNRESOLVED,
                    decision_basis="The controlled skill is absent from taxonomy.",
                ),
            ],
            unresolved_skills=[raw_skill],
        ),
        policy_config=CatalogDecisionPolicyConfig(),
    )


def _requirement(
    raw_skill: str,
    evidence: str,
    importance: RequirementImportance,
    level: ProficiencyLevel | None,
) -> ExtractedRequirement:
    return ExtractedRequirement(
        raw_skill=raw_skill,
        importance=importance,
        required_level=level,
        confidence=0.95,
        evidence_text=evidence,
        decision_basis="Controlled deterministic demonstration input.",
    )


def _resolved(
    index: int, raw_skill: str, skill_id: str, canonical_name: str
) -> TaxonomyMapping:
    return TaxonomyMapping(
        source_requirement_index=index,
        raw_skill=raw_skill,
        status=MappingStatus.RESOLVED,
        match_method=MatchMethod.EXACT,
        skill_id=skill_id,
        canonical_skill=canonical_name,
        decision_basis="Controlled canonical taxonomy match.",
    )
