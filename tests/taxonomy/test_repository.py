"""Tests for the JSON-backed taxonomy repository."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from project_catalog_agent.catalog.contracts import ExactMatchSource
from project_catalog_agent.taxonomy import (
    JsonTaxonomyRepository,
    TaxonomyLoadError,
    TaxonomyValidationError,
)

TaxonomyData = dict[str, object]


def skill(
    skill_id: str,
    name: str,
    *,
    aliases: list[str] | None = None,
) -> TaxonomyData:
    """Build taxonomy skill data for validation tests."""
    return {
        "id": skill_id,
        "name": name,
        "category": "Test",
        "aliases": aliases or [],
    }


def taxonomy_data(*skills: TaxonomyData) -> TaxonomyData:
    """Build a minimal taxonomy document."""
    return {
        "taxonomy_version": "0.1",
        "level_scale": "1-3",
        "notes": "Test taxonomy",
        "skills": list(skills) or [skill("python", "Python", aliases=["py"])],
    }


def write_taxonomy(tmp_path: Path, data: TaxonomyData) -> Path:
    """Write a temporary taxonomy document and return its path."""
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def repository() -> JsonTaxonomyRepository:
    """Return the repository backed by the packaged taxonomy."""
    return JsonTaxonomyRepository()


def test_packaged_taxonomy_loads(repository: JsonTaxonomyRepository) -> None:
    assert repository.list_skills()


def test_packaged_taxonomy_version(repository: JsonTaxonomyRepository) -> None:
    assert repository.version == "0.1"


def test_packaged_taxonomy_level_scale(repository: JsonTaxonomyRepository) -> None:
    assert repository.level_scale == "1-3"


def test_missing_file_raises_load_error(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.json"

    with pytest.raises(TaxonomyLoadError) as error_info:
        JsonTaxonomyRepository(missing_path)

    assert isinstance(error_info.value.__cause__, FileNotFoundError)


def test_malformed_json_raises_load_error(tmp_path: Path) -> None:
    path = tmp_path / "taxonomy.json"
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(TaxonomyLoadError) as error_info:
        JsonTaxonomyRepository(path)

    assert isinstance(error_info.value.__cause__, json.JSONDecodeError)


def test_structurally_invalid_json_raises_validation_error(tmp_path: Path) -> None:
    path = write_taxonomy(tmp_path, {"taxonomy_version": "0.1"})

    with pytest.raises(TaxonomyValidationError) as error_info:
        JsonTaxonomyRepository(path)

    assert isinstance(error_info.value.__cause__, ValidationError)


def test_get_skill_by_id(repository: JsonTaxonomyRepository) -> None:
    result = repository.get_by_id("python")

    assert result is not None
    assert result.canonical_name == "Python"


def test_unknown_id_returns_none(repository: JsonTaxonomyRepository) -> None:
    assert repository.get_by_id("unknown") is None


def test_canonical_name_lookup(repository: JsonTaxonomyRepository) -> None:
    result = repository.find_by_canonical_name("Python")

    assert result is not None
    assert result.skill_id == "python"


def test_canonical_name_lookup_is_case_insensitive(
    repository: JsonTaxonomyRepository,
) -> None:
    result = repository.find_by_canonical_name("PYTHON")

    assert result is not None
    assert result.skill_id == "python"


def test_canonical_name_lookup_normalizes_whitespace(
    repository: JsonTaxonomyRepository,
) -> None:
    result = repository.find_by_canonical_name("  Machine   Learning  ")

    assert result is not None
    assert result.skill_id == "machine-learning"


def test_alias_lookup(repository: JsonTaxonomyRepository) -> None:
    result = repository.find_by_alias("py")

    assert result is not None
    assert result.canonical_name == "Python"


def test_alias_lookup_is_case_insensitive(
    repository: JsonTaxonomyRepository,
) -> None:
    result = repository.find_by_alias("ML")

    assert result is not None
    assert result.canonical_name == "Machine Learning"


def test_unknown_alias_returns_none(repository: JsonTaxonomyRepository) -> None:
    assert repository.find_by_alias("unknown skill") is None


def test_resolve_exact_identifies_canonical_name(
    repository: JsonTaxonomyRepository,
) -> None:
    result = repository.resolve_exact(" Python ")

    assert result is not None
    assert result.query == " Python "
    assert result.skill.skill_id == "python"
    assert result.match_source is ExactMatchSource.CANONICAL_NAME


def test_resolve_exact_identifies_alias(repository: JsonTaxonomyRepository) -> None:
    result = repository.resolve_exact("python3")

    assert result is not None
    assert result.skill.skill_id == "python"
    assert result.match_source is ExactMatchSource.ALIAS


def test_canonical_name_match_takes_precedence(
    tmp_path: Path,
) -> None:
    path = write_taxonomy(
        tmp_path,
        taxonomy_data(skill("python", "Python", aliases=["python"])),
    )
    repository = JsonTaxonomyRepository(path)

    result = repository.resolve_exact("python")

    assert result is not None
    assert result.match_source is ExactMatchSource.CANONICAL_NAME


@pytest.mark.parametrize(
    ("query", "expected_skill_id", "expected_source"),
    [
        ("Python", "python", ExactMatchSource.CANONICAL_NAME),
        ("py", "python", ExactMatchSource.ALIAS),
        ("ML", "machine-learning", ExactMatchSource.ALIAS),
        ("reactjs", "react", ExactMatchSource.ALIAS),
        ("FastAPI", "flask-fastapi", ExactMatchSource.ALIAS),
        ("C++", "c-cpp", ExactMatchSource.ALIAS),
        ("C#", "csharp", ExactMatchSource.CANONICAL_NAME),
        (".NET", "csharp", ExactMatchSource.ALIAS),
        ("Node.js", "nodejs", ExactMatchSource.CANONICAL_NAME),
        ("Next.js", "nextjs", ExactMatchSource.CANONICAL_NAME),
        ("unknown skill", None, None),
    ],
)
def test_important_real_lookup_examples(
    repository: JsonTaxonomyRepository,
    query: str,
    expected_skill_id: str | None,
    expected_source: ExactMatchSource | None,
) -> None:
    result = repository.resolve_exact(query)

    if expected_skill_id is None:
        assert result is None
        return
    assert result is not None
    assert result.skill.skill_id == expected_skill_id
    assert result.match_source is expected_source


def duplicate_id_data() -> TaxonomyData:
    """Return taxonomy data with duplicate skill IDs."""
    return taxonomy_data(skill("python", "Python"), skill("python", "Python 2"))


def duplicate_name_data() -> TaxonomyData:
    """Return taxonomy data with case-insensitive duplicate names."""
    return taxonomy_data(skill("python", "Python"), skill("python-2", "PYTHON"))


def duplicate_alias_data() -> TaxonomyData:
    """Return taxonomy data with a cross-skill duplicate alias."""
    return taxonomy_data(
        skill("first", "First", aliases=["shared"]),
        skill("second", "Second", aliases=["SHARED"]),
    )


def duplicate_local_alias_data() -> TaxonomyData:
    """Return taxonomy data with a duplicate alias on one skill."""
    return taxonomy_data(skill("first", "First", aliases=["same", "SAME"]))


def conflicting_alias_data() -> TaxonomyData:
    """Return taxonomy data with an alias matching another canonical name."""
    return taxonomy_data(
        skill("python", "Python"),
        skill("other", "Other", aliases=["PYTHON"]),
    )


def blank_alias_data() -> TaxonomyData:
    """Return taxonomy data with a blank alias."""
    return taxonomy_data(skill("python", "Python", aliases=["   "]))


def invalid_scale_data() -> TaxonomyData:
    """Return taxonomy data with an unsupported v0.1 level scale."""
    data = taxonomy_data()
    data["level_scale"] = "0-5"
    return data


def empty_skills_data() -> TaxonomyData:
    """Return taxonomy data with no skills."""
    data = taxonomy_data()
    data["skills"] = []
    return data


@pytest.mark.parametrize(
    ("data_factory", "message_fragment"),
    [
        (duplicate_id_data, "duplicate skill ID"),
        (duplicate_name_data, "duplicate canonical name"),
        (duplicate_alias_data, "duplicate alias"),
        (duplicate_local_alias_data, "duplicate alias"),
        (conflicting_alias_data, "conflicts with another canonical name"),
        (blank_alias_data, "at least 1 character"),
        (invalid_scale_data, "requires level_scale"),
        (empty_skills_data, "at least 1 item"),
    ],
)
def test_invalid_taxonomy_is_rejected(
    tmp_path: Path,
    data_factory: Callable[[], TaxonomyData],
    message_fragment: str,
) -> None:
    path = write_taxonomy(tmp_path, data_factory())

    with pytest.raises(TaxonomyValidationError, match=message_fragment):
        JsonTaxonomyRepository(path)


def test_skill_collection_and_objects_do_not_expose_internal_state(
    repository: JsonTaxonomyRepository,
) -> None:
    skills = repository.list_skills()
    first_skill_id = skills[0].skill_id
    original_name = skills[0].canonical_name
    skills[0].canonical_name = "Changed"
    skills[0].aliases.append("new alias")

    fresh_skill = repository.get_by_id(first_skill_id)

    assert isinstance(skills, tuple)
    assert fresh_skill is not None
    assert fresh_skill.canonical_name == original_name
    assert "new alias" not in fresh_skill.aliases


def test_repeated_lookup_returns_consistent_detached_results(
    repository: JsonTaxonomyRepository,
) -> None:
    first = repository.find_by_alias("py")
    second = repository.find_by_alias("py")

    assert first == second
    assert first is not second


def test_packaged_resource_does_not_depend_on_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    repository = JsonTaxonomyRepository()

    assert repository.version == "0.1"
    assert repository.get_by_id("python") is not None
