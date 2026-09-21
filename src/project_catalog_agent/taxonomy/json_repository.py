"""Read-only JSON-backed taxonomy repository."""

import json
from importlib.resources import files
from pathlib import Path
from typing import IO

from pydantic import ValidationError

from project_catalog_agent.catalog.contracts.taxonomy import (
    ExactMatchSource,
    ExactTaxonomyMatch,
    TaxonomySkill,
)
from project_catalog_agent.taxonomy.document import (
    TaxonomyDocument,
    normalize_lookup_value,
)
from project_catalog_agent.taxonomy.errors import (
    TaxonomyLoadError,
    TaxonomyValidationError,
)


def _validation_message(error: ValidationError) -> str:
    """Render validation locations and messages without raw input values."""
    details: list[str] = []
    for item in error.errors(include_input=False, include_url=False):
        location = ".".join(str(part) for part in item["loc"]) or "document"
        details.append(f"{location}: {item['msg']}")
    return "; ".join(details)


class JsonTaxonomyRepository:
    """Taxonomy repository backed by validated JSON loaded once at startup."""

    def __init__(self, path: Path | None = None) -> None:
        """Load packaged taxonomy data or an explicitly supplied JSON file."""
        document = self._load_document(path)
        self._version = document.taxonomy_version
        self._level_scale = document.level_scale
        self._skills = tuple(skill.to_contract() for skill in document.skills)
        self._skills_by_id = {skill.skill_id: skill for skill in self._skills}
        self._skills_by_canonical_name = {
            normalize_lookup_value(skill.canonical_name): skill
            for skill in self._skills
        }
        self._skills_by_alias = {
            normalize_lookup_value(alias): skill
            for skill in self._skills
            for alias in skill.aliases
        }

    @staticmethod
    def _load_document(path: Path | None) -> TaxonomyDocument:
        try:
            if path is None:
                resource = files("project_catalog_agent.resources").joinpath(
                    "taxonomy.json"
                )
                with resource.open("r", encoding="utf-8") as handle:
                    return JsonTaxonomyRepository._parse_document(handle)
            with path.open("r", encoding="utf-8") as handle:
                return JsonTaxonomyRepository._parse_document(handle)
        except json.JSONDecodeError as error:
            msg = "taxonomy resource contains malformed JSON"
            raise TaxonomyLoadError(msg) from error
        except (OSError, ModuleNotFoundError) as error:
            msg = "taxonomy resource could not be loaded"
            raise TaxonomyLoadError(msg) from error

    @staticmethod
    def _parse_document(handle: IO[str]) -> TaxonomyDocument:
        raw_data: object = json.load(handle)
        try:
            return TaxonomyDocument.model_validate(raw_data)
        except ValidationError as error:
            msg = f"taxonomy validation failed: {_validation_message(error)}"
            raise TaxonomyValidationError(msg) from error

    @staticmethod
    def _copy_skill(skill: TaxonomySkill | None) -> TaxonomySkill | None:
        if skill is None:
            return None
        return skill.model_copy(deep=True)

    @property
    def version(self) -> str:
        """Return the loaded taxonomy version."""
        return self._version

    @property
    def level_scale(self) -> str:
        """Return the loaded proficiency scale."""
        return self._level_scale

    def list_skills(self) -> tuple[TaxonomySkill, ...]:
        """Return detached copies of all skills in source order."""
        return tuple(skill.model_copy(deep=True) for skill in self._skills)

    def get_by_id(self, skill_id: str) -> TaxonomySkill | None:
        """Find a skill by its exact stable ID."""
        return self._copy_skill(self._skills_by_id.get(skill_id.strip()))

    def find_by_canonical_name(self, name: str) -> TaxonomySkill | None:
        """Find a skill by normalized canonical name."""
        key = normalize_lookup_value(name)
        return self._copy_skill(self._skills_by_canonical_name.get(key))

    def find_by_alias(self, alias: str) -> TaxonomySkill | None:
        """Find a skill by normalized alias."""
        key = normalize_lookup_value(alias)
        return self._copy_skill(self._skills_by_alias.get(key))

    def resolve_exact(self, value: str) -> ExactTaxonomyMatch | None:
        """Resolve canonical names before aliases and report the match source."""
        key = normalize_lookup_value(value)
        canonical_skill = self._skills_by_canonical_name.get(key)
        if canonical_skill is not None:
            return ExactTaxonomyMatch(
                query=value,
                skill=canonical_skill.model_copy(deep=True),
                match_source=ExactMatchSource.CANONICAL_NAME,
            )

        alias_skill = self._skills_by_alias.get(key)
        if alias_skill is not None:
            return ExactTaxonomyMatch(
                query=value,
                skill=alias_skill.model_copy(deep=True),
                match_source=ExactMatchSource.ALIAS,
            )
        return None
