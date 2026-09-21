"""Repository interface for deterministic taxonomy access."""

from typing import Protocol

from project_catalog_agent.catalog.contracts.taxonomy import (
    ExactTaxonomyMatch,
    TaxonomySkill,
)


class TaxonomyRepository(Protocol):
    """Read-only access to a validated skill taxonomy."""

    @property
    def version(self) -> str:
        """Return the taxonomy version."""
        ...

    @property
    def level_scale(self) -> str:
        """Return the proficiency level scale."""
        ...

    def list_skills(self) -> tuple[TaxonomySkill, ...]:
        """Return all taxonomy skills."""
        ...

    def get_by_id(self, skill_id: str) -> TaxonomySkill | None:
        """Find a skill by its stable ID."""
        ...

    def find_by_canonical_name(self, name: str) -> TaxonomySkill | None:
        """Find a skill by normalized canonical name."""
        ...

    def find_by_alias(self, alias: str) -> TaxonomySkill | None:
        """Find a skill by normalized alias."""
        ...

    def resolve_exact(self, value: str) -> ExactTaxonomyMatch | None:
        """Resolve a canonical name or alias without fuzzy matching."""
        ...
