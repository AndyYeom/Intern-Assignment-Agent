"""Packaged data resources for Project Catalog Agent."""

from project_catalog_agent.resources.loaders import (
    load_proficiency_taxonomy,
    load_proficiency_taxonomy_version,
)

__all__ = ["load_proficiency_taxonomy", "load_proficiency_taxonomy_version"]
