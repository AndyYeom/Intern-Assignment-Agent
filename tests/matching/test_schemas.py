import pytest
from pydantic import BaseModel, ValidationError

from matching import (
    GAConfig,
    MatchingConstraints,
    MatchingInput,
    MatchingOutput,
    ProjectProfile,
    ProjectSkillRequirement,
    RequirementType,
    StudentProfile,
    StudentSkill,
    TaxonomyNode,
    TaxonomyTree,
)


def student(student_id: str = "student-1") -> StudentProfile:
    return StudentProfile(student_id=student_id, name="Student")


def project(project_id: str = "project-1") -> ProjectProfile:
    return ProjectProfile(project_id=project_id, name="Project")


def taxonomy() -> TaxonomyTree:
    return TaxonomyTree(nodes=[TaxonomyNode(skill_id="python", name="Python")])


def matching_input(**changes: object) -> MatchingInput:
    values: dict[str, object] = {
        "students": [student()],
        "projects": [project()],
        "taxonomy": taxonomy(),
    }
    values.update(changes)
    return MatchingInput.model_validate(values)


def matching_output(**changes: object) -> MatchingOutput:
    values: dict[str, object] = {
        "assignments": {"student-1": "project-1"},
        "final_score": 90,
        "score_breakdown": {"skills": 90},
        "unassigned_students": [],
        "unassigned_projects": [],
        "generations": 10,
        "stop_reason": "target reached",
    }
    values.update(changes)
    return MatchingOutput.model_validate(values)


def test_constructs_valid_student_skill() -> None:
    assert StudentSkill(skill_id="python", level=4).level == 4


def test_constructs_valid_student_profile() -> None:
    profile = StudentProfile(
        student_id="s-1",
        name="Ada",
        skills=[StudentSkill(skill_id="python", level=4)],
    )
    assert profile.skills[0].skill_id == "python"


def test_constructs_valid_project_requirement() -> None:
    requirement = ProjectSkillRequirement(
        skill_id="python",
        required_level=3,
        requirement_type=RequirementType.HARD_REQUIREMENT,
    )
    assert requirement.importance == 1.0


def test_constructs_valid_project_profile() -> None:
    requirement = ProjectSkillRequirement(
        skill_id="python",
        required_level=3,
        requirement_type=RequirementType.PREFERRED,
    )
    profile = ProjectProfile(
        project_id="p-1",
        name="Compiler",
        max_team_size=2,
        requirements=[requirement],
    )
    assert profile.requirements == [requirement]


def test_constructs_valid_taxonomy_node_and_tree() -> None:
    root = TaxonomyNode(skill_id="programming", name="Programming")
    child = TaxonomyNode(
        skill_id="python", name="Python", parent_id="programming"
    )
    assert TaxonomyTree(nodes=[root, child]).nodes == [root, child]


def test_matching_constraints_defaults_and_valid_construction() -> None:
    constraints = MatchingConstraints()
    assert constraints.minimum_lca_depth == 1
    assert constraints.allow_unassigned is True
    assert MatchingConstraints(minimum_lca_depth=0, allow_unassigned=False)


def test_ga_config_defaults_and_valid_construction() -> None:
    assert GAConfig().model_dump() == {
        "population_size": 100,
        "max_generations": 200,
        "mutation_rate": 0.05,
        "elite_count": 5,
        "tournament_size": 3,
        "target_score": 90.0,
        "patience": 30,
        "seed": 42,
    }
    assert GAConfig(population_size=10, elite_count=1, tournament_size=2)


def test_constructs_valid_matching_input() -> None:
    request = matching_input()
    assert request.students[0].student_id == "student-1"
    assert request.constraints == MatchingConstraints()
    assert request.config == GAConfig()


def test_constructs_valid_matching_output() -> None:
    result = matching_output()
    assert result.assignments == {"student-1": "project-1"}


def test_strips_whitespace() -> None:
    skill = StudentSkill(skill_id=" python ", level=2)
    learner = StudentProfile(student_id=" s-1 ", name=" Ada ", skills=[skill])
    requirement = ProjectSkillRequirement(
        skill_id=" python ",
        required_level=2,
        requirement_type=RequirementType.PREFERRED,
    )
    work = ProjectProfile(
        project_id=" p-1 ",
        name=" Project ",
        description=" description ",
        requirements=[requirement],
    )
    node = TaxonomyNode(skill_id=" skill ", name=" Skill ", parent_id=" root ")
    result = matching_output(stop_reason=" complete ")

    assert (skill.skill_id, learner.student_id, learner.name) == (
        "python",
        "s-1",
        "Ada",
    )
    assert (work.project_id, work.name, work.description) == (
        "p-1",
        "Project",
        "description",
    )
    assert (node.skill_id, node.name, node.parent_id) == ("skill", "Skill", "root")
    assert result.stop_reason == "complete"


@pytest.mark.parametrize(
    ("model", "values"),
    [
        (StudentSkill, {"skill_id": " ", "level": 1}),
        (StudentProfile, {"student_id": " ", "name": "Student"}),
        (StudentProfile, {"student_id": "s-1", "name": " "}),
        (
            ProjectSkillRequirement,
            {
                "skill_id": " ",
                "required_level": 1,
                "requirement_type": RequirementType.PREFERRED,
            },
        ),
        (ProjectProfile, {"project_id": " ", "name": "Project"}),
        (ProjectProfile, {"project_id": "p-1", "name": " "}),
        (TaxonomyNode, {"skill_id": " ", "name": "Skill"}),
        (TaxonomyNode, {"skill_id": "skill", "name": " "}),
    ],
)
def test_rejects_blank_required_text(
    model: type[BaseModel], values: dict[str, object]
) -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        model.model_validate(values)


@pytest.mark.parametrize("level", [-1, 6])
def test_rejects_invalid_student_skill_level(level: int) -> None:
    with pytest.raises(ValidationError):
        StudentSkill(skill_id="python", level=level)


def test_rejects_duplicate_student_skills() -> None:
    with pytest.raises(ValidationError, match="must be unique"):
        StudentProfile(
            student_id="s-1",
            name="Student",
            skills=[
                StudentSkill(skill_id="python", level=2),
                StudentSkill(skill_id=" python ", level=3),
            ],
        )


@pytest.mark.parametrize("level", [-1, 6])
def test_rejects_invalid_project_requirement_level(level: int) -> None:
    with pytest.raises(ValidationError):
        ProjectSkillRequirement(
            skill_id="python",
            required_level=level,
            requirement_type=RequirementType.PREFERRED,
        )


@pytest.mark.parametrize("importance", [0, -0.1])
def test_rejects_nonpositive_importance(importance: float) -> None:
    with pytest.raises(ValidationError):
        ProjectSkillRequirement(
            skill_id="python",
            required_level=2,
            requirement_type=RequirementType.PREFERRED,
            importance=importance,
        )


def test_rejects_duplicate_project_requirements() -> None:
    with pytest.raises(ValidationError, match="must be unique"):
        ProjectProfile.model_validate(
            {
                "project_id": "p-1",
                "name": "Project",
                "requirements": [
                    {
                        "skill_id": "python",
                        "required_level": 2,
                        "requirement_type": "preferred",
                    },
                    {
                        "skill_id": " python ",
                        "required_level": 3,
                        "requirement_type": "hard_requirement",
                    },
                ],
            }
        )


def test_rejects_min_team_size_below_one() -> None:
    with pytest.raises(ValidationError):
        ProjectProfile(project_id="p-1", name="Project", min_team_size=0)


def test_rejects_max_team_size_below_minimum() -> None:
    with pytest.raises(ValidationError, match="max_team_size"):
        ProjectProfile(
            project_id="p-1", name="Project", min_team_size=2, max_team_size=1
        )


def test_rejects_duplicate_taxonomy_nodes() -> None:
    with pytest.raises(ValidationError, match="must be unique"):
        TaxonomyTree(
            nodes=[
                TaxonomyNode(skill_id="python", name="Python"),
                TaxonomyNode(skill_id=" python ", name="Python 2"),
            ]
        )


def test_rejects_missing_taxonomy_parent() -> None:
    with pytest.raises(ValidationError, match="existing node"):
        TaxonomyTree(
            nodes=[
                TaxonomyNode(
                    skill_id="python", name="Python", parent_id="programming"
                )
            ]
        )


def test_rejects_self_parenting_taxonomy_node() -> None:
    with pytest.raises(ValidationError, match="own parent"):
        TaxonomyNode(skill_id=" python ", name="Python", parent_id="python ")


def test_rejects_empty_taxonomy() -> None:
    with pytest.raises(ValidationError):
        TaxonomyTree(nodes=[])


def test_converts_blank_parent_id_to_none() -> None:
    node = TaxonomyNode(skill_id="python", name="Python", parent_id=" ")
    assert node.parent_id is None


def test_rejects_negative_minimum_lca_depth() -> None:
    with pytest.raises(ValidationError):
        MatchingConstraints(minimum_lca_depth=-1)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"population_size": 0}, "population_size"),
        ({"max_generations": 0}, "max_generations"),
        ({"mutation_rate": -0.1}, "mutation_rate"),
        ({"mutation_rate": 1.1}, "mutation_rate"),
        ({"population_size": 5, "elite_count": 5}, "elite_count"),
        ({"elite_count": -1}, "elite_count"),
        ({"population_size": 5, "tournament_size": 6}, "tournament_size"),
        ({"tournament_size": 0}, "tournament_size"),
        ({"target_score": -0.1}, "target_score"),
        ({"target_score": 100.1}, "target_score"),
        ({"patience": -1}, "patience"),
    ],
)
def test_rejects_invalid_ga_config(
    changes: dict[str, int | float], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        GAConfig(**changes)


def test_matching_input_defaults_are_independent() -> None:
    first = matching_input()
    second = matching_input()
    assert first.constraints is not second.constraints
    assert first.config is not second.config


@pytest.mark.parametrize("field", ["students", "projects"])
def test_rejects_empty_matching_input_collection(field: str) -> None:
    with pytest.raises(ValidationError):
        matching_input(**{field: []})


def test_rejects_duplicate_student_ids() -> None:
    with pytest.raises(ValidationError, match="student IDs must be unique"):
        matching_input(students=[student(" s-1 "), student("s-1")])


def test_rejects_duplicate_project_ids() -> None:
    with pytest.raises(ValidationError, match="project IDs must be unique"):
        matching_input(projects=[project(" p-1 "), project("p-1")])


@pytest.mark.parametrize("score", [-0.1, 100.1])
def test_rejects_invalid_final_score(score: float) -> None:
    with pytest.raises(ValidationError):
        matching_output(final_score=score)


@pytest.mark.parametrize("score", [-0.1, 100.1, float("nan")])
def test_rejects_invalid_score_breakdown(score: float) -> None:
    with pytest.raises(ValidationError, match="score_breakdown"):
        matching_output(score_breakdown={"skills": score})


def test_rejects_negative_generations() -> None:
    with pytest.raises(ValidationError):
        matching_output(generations=-1)


def test_rejects_blank_stop_reason() -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        matching_output(stop_reason="   ")
