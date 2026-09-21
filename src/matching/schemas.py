"""External schemas for student-project matching."""

from enum import Enum

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator


class StudentSkill(BaseModel):
    skill_id: str
    level: int = Field(ge=0, le=5)

    @field_validator("skill_id")
    @classmethod
    def validate_skill_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("skill_id must not be empty")
        return value


class StudentProfile(BaseModel):
    student_id: str
    name: str
    skills: list[StudentSkill] = Field(default_factory=list)

    @field_validator("student_id", "name")
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{info.field_name} must not be empty")
        return value

    @model_validator(mode="after")
    def validate_unique_skills(self) -> "StudentProfile":
        skill_ids = [skill.skill_id for skill in self.skills]
        if len(skill_ids) != len(set(skill_ids)):
            raise ValueError("student skill IDs must be unique")
        return self


class RequirementType(str, Enum):
    HARD_REQUIREMENT = "hard_requirement"
    PREFERRED = "preferred"
    LEARNING_OPPORTUNITY = "learning_opportunity"


class ProjectSkillRequirement(BaseModel):
    skill_id: str
    required_level: int = Field(ge=0, le=5)
    requirement_type: RequirementType
    importance: float = Field(default=1.0, gt=0)

    @field_validator("skill_id")
    @classmethod
    def validate_skill_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("skill_id must not be empty")
        return value


class ProjectProfile(BaseModel):
    project_id: str
    name: str
    description: str = ""
    min_team_size: int = Field(default=1, ge=1)
    max_team_size: int = 1
    requirements: list[ProjectSkillRequirement] = Field(default_factory=list)

    @field_validator("project_id", "name")
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{info.field_name} must not be empty")
        return value

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_project(self) -> "ProjectProfile":
        if self.max_team_size < self.min_team_size:
            raise ValueError("max_team_size must be at least min_team_size")

        skill_ids = [requirement.skill_id for requirement in self.requirements]
        if len(skill_ids) != len(set(skill_ids)):
            raise ValueError("project requirement skill IDs must be unique")
        return self


class TaxonomyNode(BaseModel):
    skill_id: str
    name: str
    parent_id: str | None = None

    @field_validator("skill_id", "name")
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{info.field_name} must not be empty")
        return value

    @field_validator("parent_id")
    @classmethod
    def normalize_parent_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def validate_parent(self) -> "TaxonomyNode":
        if self.parent_id == self.skill_id:
            raise ValueError("a taxonomy node cannot be its own parent")
        return self


class TaxonomyTree(BaseModel):
    nodes: list[TaxonomyNode] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_nodes(self) -> "TaxonomyTree":
        skill_ids = [node.skill_id for node in self.nodes]
        if len(skill_ids) != len(set(skill_ids)):
            raise ValueError("taxonomy node skill IDs must be unique")

        known_ids = set(skill_ids)
        if any(
            node.parent_id is not None and node.parent_id not in known_ids
            for node in self.nodes
        ):
            raise ValueError("taxonomy parent_id must reference an existing node")
        return self


class MatchingConstraints(BaseModel):
    minimum_lca_depth: int = Field(default=1, ge=0)
    allow_unassigned: bool = True


class GAConfig(BaseModel):
    population_size: int = Field(default=100, gt=0)
    max_generations: int = Field(default=200, gt=0)
    mutation_rate: float = Field(default=0.05, ge=0, le=1)
    elite_count: int = Field(default=5, ge=0)
    tournament_size: int = Field(default=3, ge=1)
    target_score: float = Field(default=90.0, ge=0, le=100)
    patience: int = Field(default=30, ge=0)
    seed: int = 42

    @model_validator(mode="after")
    def validate_population_settings(self) -> "GAConfig":
        if self.elite_count >= self.population_size:
            raise ValueError("elite_count must be less than population_size")
        if self.tournament_size > self.population_size:
            raise ValueError("tournament_size must not exceed population_size")
        return self


class MatchingInput(BaseModel):
    students: list[StudentProfile] = Field(min_length=1)
    projects: list[ProjectProfile] = Field(min_length=1)
    taxonomy: TaxonomyTree
    constraints: MatchingConstraints = Field(default_factory=MatchingConstraints)
    config: GAConfig = Field(default_factory=GAConfig)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "MatchingInput":
        student_ids = [student.student_id for student in self.students]
        if len(student_ids) != len(set(student_ids)):
            raise ValueError("student IDs must be unique")

        project_ids = [project.project_id for project in self.projects]
        if len(project_ids) != len(set(project_ids)):
            raise ValueError("project IDs must be unique")
        return self


class MatchingOutput(BaseModel):
    assignments: dict[str, str | None]
    final_score: float = Field(ge=0, le=100)
    score_breakdown: dict[str, float]
    unassigned_students: list[str]
    unassigned_projects: list[str]
    generations: int = Field(ge=0)
    stop_reason: str

    @field_validator("score_breakdown")
    @classmethod
    def validate_score_breakdown(
        cls, value: dict[str, float]
    ) -> dict[str, float]:
        if any(not 0 <= score <= 100 for score in value.values()):
            raise ValueError("score_breakdown values must be between 0 and 100")
        return value

    @field_validator("stop_reason")
    @classmethod
    def validate_stop_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("stop_reason must not be empty")
        return value
