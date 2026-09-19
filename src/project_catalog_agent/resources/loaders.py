"""Load packaged text resources without relying on the working directory."""

from importlib.resources import files


def load_proficiency_taxonomy() -> str:
    """Return the shared proficiency taxonomy unchanged."""
    resource = files("project_catalog_agent.resources").joinpath(
        "proficiency_taxonomy.md"
    )
    return resource.read_text(encoding="utf-8")


def load_proficiency_taxonomy_version() -> str:
    """Read the version from the shared proficiency resource heading."""
    heading = load_proficiency_taxonomy().splitlines()[0]
    prefix = "# Proficiency Levels (v"
    if not heading.startswith(prefix) or not heading.endswith(")"):
        msg = "shared proficiency taxonomy has no recognized version heading"
        raise ValueError(msg)
    return heading[len(prefix) : -1]
