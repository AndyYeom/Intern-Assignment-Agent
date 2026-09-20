import pytest

from matching import (
    are_taxonomically_related,
    find_lowest_common_ancestor,
    get_ancestor_path,
    get_lca_depth,
    get_skill_depth,
)


@pytest.fixture
def parent_by_id() -> dict[str, str | None]:
    return {
        "technology": None,
        "programming": "technology",
        "python": "programming",
        "javascript": "programming",
        "data": "technology",
        "sql": "data",
        "databases": "data",
        "business": None,
        "marketing": "business",
    }


def test_root_ancestor_path(parent_by_id: dict[str, str | None]) -> None:
    assert get_ancestor_path("technology", parent_by_id) == ("technology",)


def test_nested_ancestor_path(parent_by_id: dict[str, str | None]) -> None:
    assert get_ancestor_path("python", parent_by_id) == (
        "python",
        "programming",
        "technology",
    )


@pytest.mark.parametrize(
    ("skill_id", "expected_depth"),
    [("technology", 0), ("programming", 1), ("python", 2)],
)
def test_skill_depths(
    parent_by_id: dict[str, str | None],
    skill_id: str,
    expected_depth: int,
) -> None:
    assert get_skill_depth(skill_id, parent_by_id) == expected_depth


def test_lca_of_siblings(parent_by_id: dict[str, str | None]) -> None:
    assert (
        find_lowest_common_ancestor("python", "javascript", parent_by_id)
        == "programming"
    )


def test_lca_of_ancestor_and_descendant(
    parent_by_id: dict[str, str | None],
) -> None:
    assert (
        find_lowest_common_ancestor("programming", "python", parent_by_id)
        == "programming"
    )


def test_lca_of_identical_skills(parent_by_id: dict[str, str | None]) -> None:
    assert (
        find_lowest_common_ancestor("python", "python", parent_by_id) == "python"
    )


def test_separate_roots_have_no_lca(parent_by_id: dict[str, str | None]) -> None:
    assert find_lowest_common_ancestor("python", "marketing", parent_by_id) is None
    assert get_lca_depth("python", "marketing", parent_by_id) is None


def test_lca_depth(parent_by_id: dict[str, str | None]) -> None:
    assert get_lca_depth("python", "javascript", parent_by_id) == 1
    assert get_lca_depth("python", "python", parent_by_id) == 2


@pytest.mark.parametrize("function", [get_ancestor_path, get_skill_depth])
def test_missing_skill_raises_key_error(
    parent_by_id: dict[str, str | None], function: object
) -> None:
    with pytest.raises(KeyError, match="missing"):
        function("missing", parent_by_id)  # type: ignore[operator]


def test_missing_lca_skill_raises_key_error(
    parent_by_id: dict[str, str | None],
) -> None:
    with pytest.raises(KeyError, match="missing"):
        find_lowest_common_ancestor("python", "missing", parent_by_id)


def test_cycle_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Cycle detected"):
        get_ancestor_path("first", {"first": "second", "second": "first"})


def test_identical_skills_are_related(parent_by_id: dict[str, str | None]) -> None:
    assert are_taxonomically_related("python", "python", parent_by_id, 99)


def test_related_skills_pass_threshold(
    parent_by_id: dict[str, str | None],
) -> None:
    assert are_taxonomically_related("python", "javascript", parent_by_id, 1)


def test_related_skills_fail_high_threshold(
    parent_by_id: dict[str, str | None],
) -> None:
    assert not are_taxonomically_related(
        "python", "javascript", parent_by_id, 2
    )


def test_negative_minimum_lca_depth_is_rejected(
    parent_by_id: dict[str, str | None],
) -> None:
    with pytest.raises(ValueError, match="nonnegative"):
        are_taxonomically_related("python", "javascript", parent_by_id, -1)
