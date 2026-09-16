"""Tests for evidence -> taxonomy mapping."""
from __future__ import annotations

import json

from generator.github import skill_map


def test_every_mapping_target_is_a_canonical_skill_id():
    """A typo in a mapping table would silently drop evidence."""
    valid = skill_map.skill_ids()
    for table, name in (
        (skill_map.LANGUAGE_TO_SKILL, "LANGUAGE_TO_SKILL"),
        (skill_map.DEPENDENCY_TO_SKILL, "DEPENDENCY_TO_SKILL"),
    ):
        bad = {k: v for k, v in table.items() if v not in valid}
        assert not bad, f"{name} points at non-taxonomy ids: {bad}"

    bad_files = [(p.pattern, s) for p, s, _ in skill_map.FILE_PATTERNS if s not in valid]
    assert not bad_files, f"FILE_PATTERNS points at non-taxonomy ids: {bad_files}"


def test_parses_package_json():
    text = json.dumps({
        "dependencies": {"react": "^18.0.0", "next": "14.0", "@reduxjs/toolkit": "2.0"},
        "devDependencies": {"jest": "^29"},
    })
    deps = skill_map.parse_manifest("package.json", text)
    assert {"react", "next", "jest", "@reduxjs/toolkit"} <= deps

    skills = {s.skill_id for s in skill_map.signals_from_dependencies(deps, "package.json")}
    assert {"react", "nextjs", "unit-testing", "state-management"} <= skills


def test_parses_requirements_txt():
    text = "fastapi==0.110.0\nsqlalchemy>=2\n# a comment\nchromadb\npytest==8.0\n"
    deps = skill_map.parse_manifest("requirements.txt", text)
    skills = {s.skill_id for s in skill_map.signals_from_dependencies(deps, "requirements.txt")}
    assert {"flask-fastapi", "data-modeling", "rag", "unit-testing"} <= skills


def test_manifests_reach_skills_languages_cannot():
    """Languages only cover ~9 skills; manifests are what give taxonomy breadth."""
    from_languages = set(skill_map.LANGUAGE_TO_SKILL.values())
    from_deps = set(skill_map.DEPENDENCY_TO_SKILL.values())
    assert len(from_deps - from_languages) > 25


def test_trivial_language_share_is_not_evidence():
    """A few bytes of CSS in a Python repo does not evidence HTML/CSS."""
    signals = skill_map.signals_from_languages({"Python": 500_000, "CSS": 200})
    assert {s.skill_id for s in signals} == {"python"}


def test_file_patterns_detect_infrastructure_skills():
    paths = [".github/workflows/ci.yml", "Dockerfile", "tests/test_api.py", "k8s/deploy.yaml"]
    skills = {s.skill_id for s in skill_map.signals_from_tree(paths)}
    assert {"cicd", "docker", "unit-testing", "kubernetes"} <= skills


def test_source_strength_ordering():
    """A declared dependency must outweigh a self-declared topic."""
    assert skill_map.SOURCE_STRENGTH["manifest"] > skill_map.SOURCE_STRENGTH["topic"]
    assert skill_map.SOURCE_STRENGTH["language"] > skill_map.SOURCE_STRENGTH["repo_name"]
