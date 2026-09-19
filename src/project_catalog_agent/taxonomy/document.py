"""Private file-format models for the packaged taxonomy document."""

from typing import Annotated, Self

from pydantic import Field, model_validator

from project_catalog_agent.catalog.contracts.common import ContractModel
from project_catalog_agent.catalog.contracts.taxonomy import TaxonomySkill

NonEmptyString = Annotated[str, Field(min_length=1)]


def normalize_lookup_value(value: str) -> str:
    """Normalize surrounding, repeated, and case differences for lookup."""
    return " ".join(value.split()).casefold()


class TaxonomySkillDocument(ContractModel):
    """Taxonomy skill as represented in the JSON resource."""

    id: NonEmptyString
    name: NonEmptyString
    category: NonEmptyString
    aliases: list[NonEmptyString] = Field(default_factory=list)
    active: bool = True

    def to_contract(self) -> TaxonomySkill:
        """Convert the file representation to the public domain contract."""
        return TaxonomySkill(
            skill_id=self.id,
            canonical_name=self.name,
            aliases=self.aliases,
            category=self.category,
            active=self.active,
        )


class TaxonomyDocument(ContractModel):
    """Validated representation of the complete taxonomy resource."""

    taxonomy_version: NonEmptyString
    level_scale: NonEmptyString
    notes: str
    skills: Annotated[list[TaxonomySkillDocument], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_document_integrity(self) -> Self:
        """Reject unsupported scales and ambiguous identifiers or names."""
        if self.taxonomy_version == "0.1" and self.level_scale != "1-3":
            msg = 'taxonomy version 0.1 requires level_scale "1-3"'
            raise ValueError(msg)

        skill_ids: set[str] = set()
        canonical_owners: dict[str, str] = {}
        for skill in self.skills:
            if skill.id in skill_ids:
                msg = f"duplicate skill ID: {skill.id}"
                raise ValueError(msg)
            skill_ids.add(skill.id)

            canonical_key = normalize_lookup_value(skill.name)
            if canonical_key in canonical_owners:
                msg = f"duplicate canonical name: {skill.name}"
                raise ValueError(msg)
            canonical_owners[canonical_key] = skill.id

        alias_owners: dict[str, str] = {}
        for skill in self.skills:
            aliases_for_skill: set[str] = set()
            for alias in skill.aliases:
                alias_key = normalize_lookup_value(alias)
                if alias_key in aliases_for_skill:
                    msg = f"duplicate alias for skill {skill.id}: {alias}"
                    raise ValueError(msg)
                aliases_for_skill.add(alias_key)

                canonical_owner = canonical_owners.get(alias_key)
                if canonical_owner is not None and canonical_owner != skill.id:
                    msg = f"alias conflicts with another canonical name: {alias}"
                    raise ValueError(msg)

                if alias_key in alias_owners:
                    msg = f"duplicate alias: {alias}"
                    raise ValueError(msg)
                alias_owners[alias_key] = skill.id

        return self
