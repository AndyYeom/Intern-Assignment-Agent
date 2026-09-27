"""Constraints the database itself must enforce."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.db import session_scope
from backend.db.models import (
    Applicant,
    ApplicantSkill,
    Assignment,
    AssignmentRun,
    Project,
    ProjectRole,
    ProjectRoleSkill,
    Skill,
)


def _applicant(ref: str, email: str) -> Applicant:
    return Applicant(reference=ref, name=ref, email=email, status="ready")


def _project(name: str = "P", capacity: int = 2) -> Project:
    project = Project(name=name)
    project.roles.append(
        ProjectRole(
            name="Dev",
            capacity=capacity,
            requirements=[
                ProjectRoleSkill(skill_id="python", required_level=1, requirement_type="hard_requirement")
            ],
        )
    )
    return project


def test_duplicate_skill_name_is_rejected_case_insensitively(db):
    with pytest.raises(IntegrityError), session_scope() as s:
        s.add(Skill(id="python-dup", name="PYTHON", category="Language"))


def test_duplicate_applicant_email_is_rejected_case_insensitively(db):
    with session_scope() as s:
        s.add(_applicant("a1", "same@example.com"))
    with pytest.raises(IntegrityError), session_scope() as s:
        s.add(_applicant("a2", "SAME@example.com"))


def test_role_capacity_and_levels_are_checked(db):
    with pytest.raises(IntegrityError), session_scope() as s:
        s.add(_project(capacity=0))
    with pytest.raises(IntegrityError), session_scope() as s:
        p = _project("Q")
        p.roles[0].requirements[0].required_level = 4
        s.add(p)


def test_role_skill_must_reference_a_known_skill(db):
    with pytest.raises(IntegrityError), session_scope() as s:
        p = _project()
        p.roles[0].requirements[0].skill_id = "cobol"
        s.add(p)


def test_deleting_an_applicant_cascades_to_skills(db):
    with session_scope() as s:
        a = _applicant("a1", "a1@example.com")
        a.skills.append(ApplicantSkill(skill_id="python", final_level=2))
        s.add(a)
    with session_scope() as s:
        s.delete(s.scalar(select(Applicant)))
    with session_scope() as s:
        assert s.scalar(select(ApplicantSkill)) is None


def test_assignment_history_blocks_deleting_referenced_projects_and_applicants(db):
    with session_scope() as s:
        a = _applicant("a1", "a1@example.com")
        p = _project()
        run = AssignmentRun(configuration={}, solver_version="t", scoring_version="t")
        s.add_all([a, p, run])
        s.flush()
        role = p.roles[0]
        s.add(
            Assignment(
                assignment_run_id=run.id,
                applicant_id=a.id,
                project_id=p.id,
                project_role_id=role.id,
                solver_role_id=role.id,
                score=90,
                reason={},
            )
        )
    with pytest.raises(IntegrityError), session_scope() as s:
        s.delete(s.scalar(select(Project)))
    with pytest.raises(IntegrityError), session_scope() as s:
        s.delete(s.scalar(select(Applicant)))


def test_an_unreferenced_project_deletes_with_its_roles(db):
    with session_scope() as s:
        s.add(_project())
    with session_scope() as s:
        s.delete(s.scalar(select(Project)))
    with session_scope() as s:
        assert s.scalar(select(ProjectRole)) is None
        assert s.scalar(select(ProjectRoleSkill)) is None


def test_one_assignment_per_applicant_per_run(db):
    with session_scope() as s:
        a = _applicant("a1", "a1@example.com")
        p = _project()
        run = AssignmentRun(configuration={}, solver_version="t", scoring_version="t")
        s.add_all([a, p, run])
        s.flush()
        rid = p.roles[0].id
        values = dict(
            assignment_run_id=run.id, applicant_id=a.id, project_id=p.id,
            project_role_id=rid, solver_role_id=rid, score=1, reason={},
        )
        s.add(Assignment(**values))
        s.flush()
        s.add(Assignment(id=uuid.uuid4(), **values))
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()
