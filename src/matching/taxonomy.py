"""Taxonomy traversal and comparison helpers."""

from collections.abc import Mapping


def get_ancestor_path(
    skill_id: str,
    parent_by_id: Mapping[str, str | None],
) -> tuple[str, ...]:
    path: list[str] = []
    seen: set[str] = set()
    current: str | None = skill_id

    while current is not None:
        if current in seen:
            raise ValueError(f"Cycle detected in taxonomy at skill '{current}'")
        if current not in parent_by_id:
            raise KeyError(f"Skill '{current}' is not in the taxonomy")

        seen.add(current)
        path.append(current)
        current = parent_by_id[current]

    return tuple(path)


def get_skill_depth(
    skill_id: str,
    parent_by_id: Mapping[str, str | None],
) -> int:
    return len(get_ancestor_path(skill_id, parent_by_id)) - 1


def find_lowest_common_ancestor(
    first_skill_id: str,
    second_skill_id: str,
    parent_by_id: Mapping[str, str | None],
) -> str | None:
    first_path = get_ancestor_path(first_skill_id, parent_by_id)
    second_ancestors = set(get_ancestor_path(second_skill_id, parent_by_id))
    return next(
        (ancestor for ancestor in first_path if ancestor in second_ancestors),
        None,
    )


def get_lca_depth(
    first_skill_id: str,
    second_skill_id: str,
    parent_by_id: Mapping[str, str | None],
) -> int | None:
    ancestor = find_lowest_common_ancestor(
        first_skill_id, second_skill_id, parent_by_id
    )
    if ancestor is None:
        return None
    return get_skill_depth(ancestor, parent_by_id)


def are_taxonomically_related(
    first_skill_id: str,
    second_skill_id: str,
    parent_by_id: Mapping[str, str | None],
    minimum_lca_depth: int,
) -> bool:
    if minimum_lca_depth < 0:
        raise ValueError("minimum_lca_depth must be nonnegative")

    if first_skill_id == second_skill_id:
        get_ancestor_path(first_skill_id, parent_by_id)
        return True

    depth = get_lca_depth(first_skill_id, second_skill_id, parent_by_id)
    return depth is not None and depth >= minimum_lca_depth
