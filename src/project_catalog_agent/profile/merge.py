"""Shared deterministic merge calculations for profiles and validation."""

from collections.abc import Iterable

from project_catalog_agent.catalog.contracts import (
    ProficiencyLevel,
    RequirementImportance,
)

IMPORTANCE_RANK = {
    RequirementImportance.LEARNING_OPPORTUNITY: 1,
    RequirementImportance.PREFERRED: 2,
    RequirementImportance.HARD_REQUIREMENT: 3,
}


def strongest_importance(
    values: Iterable[RequirementImportance],
) -> RequirementImportance:
    """Return the strongest requirement importance using catalog precedence."""
    return max(values, key=IMPORTANCE_RANK.__getitem__)


def maximum_required_level(
    values: Iterable[ProficiencyLevel | None],
) -> ProficiencyLevel | None:
    """Return the maximum known level without treating None as level zero."""
    known_levels = [value for value in values if value is not None]
    return max(known_levels) if known_levels else None


def dominance_key(
    *,
    importance: RequirementImportance,
    required_level: ProficiencyLevel | None,
    confidence: float,
    source_requirement_index: int,
) -> tuple[int, int, float, int]:
    """Return the documented aggregate-source ordering key."""
    return (
        IMPORTANCE_RANK[importance],
        int(required_level) if required_level is not None else -1,
        confidence,
        -source_requirement_index,
    )
