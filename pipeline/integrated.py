"""Connected agent preview. Live model calls or explicitly labelled fixture replay.

Run from the repository root: python -m pipeline.integrated --mode replay.
No placements are published; human review is always pending.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator
from src.evidence_agent import evaluate_github
from src.profile_agent.profile_models import ApplicantProfile

from matching import optimize_matching
from matching.assignment import students_for_project
from matching.preprocessing import preprocess_inputs
from matching.pruning import build_candidate_options
from matching.repair import hard_requirements_covered
from matching.schemas import (
    GAConfig,
    MatchingInput,
    ProjectProfile,
    StudentProfile,
    TaxonomyTree,
)
from matching.scoring import student_growth_opportunity_score, student_project_fit
from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    RequirementExtractionResult,
)
from project_catalog_agent.profile.builder import ProjectProfileBuilder
from project_catalog_agent.profile.validator import ProjectProfileValidator
from project_catalog_agent.taxonomy.json_repository import JsonTaxonomyRepository
from project_catalog_agent.taxonomy.normalizer import HybridTaxonomyNormalizer

from .resolve_profile import resolve_profile

ROOT = Path(__file__).resolve().parents[1]


class ApplicantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    applicant_id: str = Field(min_length=1)
    resume: str
    saved_profile: str
    portfolio: str | None = None


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: CreateProjectRequest
    min_team_size: int = Field(default=1, ge=1)
    capacity: int = Field(ge=1)
    replay_extraction: RequirementExtractionResult

    @model_validator(mode="after")
    def check_capacity(self):
        if self.min_team_size > self.capacity:
            raise ValueError("minimum team size exceeds capacity")
        return self


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    applicants: list[ApplicantInput] = Field(min_length=1, max_length=5)
    projects: list[ProjectInput] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def unique_ids(self):
        for ids in (
            [a.applicant_id for a in self.applicants],
            [p.request.request_id for p in self.projects],
        ):
            if len(ids) != len(set(ids)):
                raise ValueError("duplicate input IDs")
        return self


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(folder, name, payload):
    (folder / name).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def matching_student(profile, report, taxonomy):
    """Join evidence by the original skill name, then canonicalize conservatively."""
    if profile.applicant_id != report.applicant_id:
        raise ValueError("profile/evidence applicant ID mismatch")
    resolved = resolve_profile(profile.model_dump(), report.payload())
    lookup = {}
    for skill in taxonomy.list_skills():
        for name in [skill.skill_id, skill.canonical_name, *skill.aliases]:
            lookup[name.casefold().strip()] = skill.skill_id
    skills, unmapped = {}, []
    for name, level in resolved["skills"].items():
        skill_id = lookup.get(name.casefold().strip())
        if not skill_id:
            unmapped.append(name)
            continue
        if level not in (1, 2, 3):
            raise ValueError(f"invalid resolved proficiency for {name}")
        skills[skill_id] = min(skills.get(skill_id, level), level)
    student = StudentProfile(
        student_id=profile.applicant_id,
        name=profile.applicant_id,
        skills=[{"skill_id": key, "level": level} for key, level in skills.items()],
    )
    return student, {**resolved, "unmapped_skills": unmapped}


def matching_project(profile, item):
    if profile.unresolved_requirements or profile.unresolved_skills:
        raise ValueError("project has unresolved skills; reviewer input required")
    if any(r.required_level is None for r in profile.requirements):
        raise ValueError("project has missing proficiency; reviewer input required")
    return ProjectProfile(
        project_id=profile.request_id,
        name=profile.project_name,
        description=profile.project_description,
        min_team_size=item.min_team_size,
        max_team_size=item.capacity,
        requirements=[
            {
                "skill_id": r.skill_id,
                "required_level": int(r.required_level),
                "requirement_type": r.importance.value,
            }
            for r in profile.requirements
        ],
    )


async def run(inputs, output, mode):
    if mode not in {"replay", "live"}:
        raise ValueError("mode must be replay or live")
    # Never reuse a previous output directory: stale live/replay artifacts must not mix.
    output.mkdir(parents=True, exist_ok=False)
    status = {
        "mode": mode,
        "status": "running",
        "review_status": "pending",
        "published": False,
        "proficiency_scale": "1-3",
        "github_source": "checked-in corpus",
        "stages": [],
    }
    save(output, "status.json", status)
    try:
        extractor = selector = None
        if mode == "live":
            from src.profile_agent.profile_graph import create_profile_llm

            from project_catalog_agent.config.settings import Settings
            from project_catalog_agent.extraction.llm_extractor import (
                LLMRequirementExtractor,
            )
            from project_catalog_agent.llm.openai_client import (
                OpenAIStructuredLLMClient,
            )
            from project_catalog_agent.taxonomy.selector import (
                LLMTaxonomyMappingSelector,
            )

            create_profile_llm()  # validate configuration before any extraction/model call
            client = OpenAIStructuredLLMClient.from_settings(Settings())
            extractor = LLMRequirementExtractor(client)
            selector = LLMTaxonomyMappingSelector(client)
        taxonomy = JsonTaxonomyRepository(ROOT / "data/taxonomy.json")
        students, profiles, reports, resolved = [], [], [], []
        print(f"[1/4] Profile -> evidence -> resolved skills ({mode})", flush=True)
        for item in inputs.applicants:
            if not (ROOT / f"data/githubs/profiles/{item.applicant_id}.json").is_file():
                raise ValueError(
                    f"Missing collected GitHub profile: {item.applicant_id}"
                )
            if mode == "live":
                from src.profile_agent.profile_graph import evaluate_resume

                profile = evaluate_resume(
                    ROOT / item.resume,
                    applicant_id=item.applicant_id,
                    portfolio_path=ROOT / item.portfolio if item.portfolio else None,
                )
            else:
                profile = ApplicantProfile.model_validate(
                    read_json(ROOT / item.saved_profile)
                )
            if profile.applicant_id != item.applicant_id:
                raise ValueError("saved profile ID differs from manifest")
            report = evaluate_github(item.applicant_id, profile, use_llm=mode == "live")
            student, resolution = matching_student(profile, report, taxonomy)
            students.append(student)
            profiles.append(profile.model_dump(mode="json"))
            reports.append(report.model_dump(mode="json"))
            resolved.append(resolution)
            save(output, "profiles.json", profiles)
            save(output, "evidence.json", reports)
            save(output, "resolved.json", resolved)
            print(
                f"  {item.applicant_id}: {len(student.skills)} mapped skills; evidence={report.mode}",
                flush=True,
            )
        status["stages"].append(
            {
                "profile": "live" if mode == "live" else "saved output",
                "evidence": [r["mode"] for r in reports],
            }
        )
        print("[2/4] Catalog extraction -> normalization -> validation", flush=True)
        projects, catalogs = [], []
        for item in inputs.projects:
            extraction = (
                await extractor.extract(item.request)
                if extractor
                else item.replay_extraction
            )
            normalization = await HybridTaxonomyNormalizer(
                taxonomy, selector
            ).normalize(extraction)
            profile = ProjectProfileBuilder().build(
                request=item.request, extraction=extraction, normalization=normalization
            )
            validation = ProjectProfileValidator(taxonomy_repository=taxonomy).validate(
                profile
            )
            catalogs.append(
                {
                    "profile": profile.model_dump(mode="json"),
                    "extraction": extraction.model_dump(mode="json"),
                    "validation": validation.model_dump(mode="json"),
                }
            )
            save(output, "catalog.json", catalogs)
            if not validation.valid:
                raise ValueError(f"Catalog review required: {item.request.request_id}")
            projects.append(matching_project(profile, item))
        status["stages"].append(
            {
                "catalog_extraction": "live" if mode == "live" else "synthetic fixture",
                "normalization_and_validation": "real components",
            }
        )
        # Flat taxonomy deliberately allows exact-ID matching only. A shared category
        # such as Language is not evidence that Java and Python are interchangeable.
        tree = TaxonomyTree(
            nodes=[
                {"skill_id": s.skill_id, "name": s.canonical_name}
                for s in taxonomy.list_skills()
            ]
        )
        data = MatchingInput(
            students=students,
            projects=projects,
            taxonomy=tree,
            config=GAConfig(seed=42),
        )
        save(output, "matching-input.json", data.model_dump(mode="json"))
        print("[3/4] Score matrix -> existing matching optimizer", flush=True)
        context = preprocess_inputs(data)
        options = build_candidate_options(context)
        matrix = [
            {
                "applicant_id": s.student_id,
                "project_id": p.project_id,
                "candidate": p.project_id in options[s.student_id],
                "fit_score": student_project_fit(s, p, context),
                "growth_by_skill": {
                    r.skill_id: student_growth_opportunity_score(s, r, context)
                    for r in p.requirements
                },
            }
            for s in students
            for p in projects
        ]
        save(output, "scores.json", matrix)
        result = optimize_matching(data)
        for project in projects:
            team = students_for_project(result.assignments, project.project_id)
            if team and (
                not project.min_team_size <= len(team) <= project.max_team_size
                or not hard_requirements_covered(team, project, context)
            ):
                raise ValueError(f"Invalid assignment for {project.project_id}")
        for student_id, project_id in result.assignments.items():
            if project_id is not None and project_id not in options[student_id]:
                raise ValueError("optimizer returned a non-candidate placement")
        status.update(
            status="draft_requires_review",
            unassigned=result.unassigned_students,
            pending_reviews=["profiles_and_catalog", "scores", "mentor_placement"],
            live_model_validation=mode == "live",
        )
        save(
            output,
            "assignment-draft.json",
            {
                **result.model_dump(mode="json"),
                "review_status": "pending",
                "published": False,
            },
        )
        save(output, "status.json", status)
        print(
            f"[4/4] DRAFT: {len(students) - len(result.unassigned_students)}/{len(students)} assigned; "
            f"score={result.final_score:.2f}; human approval pending",
            flush=True,
        )
        print(f"Artifacts: {output}", flush=True)
        return result
    except Exception as error:
        status.update(status="failed", error_type=type(error).__name__)
        save(output, "status.json", status)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["replay", "live"], default="replay")
    parser.add_argument(
        "--input", type=Path, default=ROOT / "data/integration-demo.json"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv

        if not args.env_file.is_file():
            parser.error("environment file does not exist")
        load_dotenv(args.env_file, override=True)
    os.chdir(ROOT)
    try:
        result = asyncio.run(
            run(
                RunInput.model_validate(read_json(args.input.resolve())),
                args.output_dir.resolve(),
                args.mode,
            )
        )
    except Exception as error:
        print(f"Integration stopped: {type(error).__name__}: {error}")
        return 1
    return 2 if result.unassigned_students else 0


if __name__ == "__main__":
    raise SystemExit(main())
