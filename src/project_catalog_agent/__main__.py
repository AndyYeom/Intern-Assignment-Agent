"""Command-line entry point for Project Catalog Agent."""

import json

from project_catalog_agent.app import create_app_info


def main() -> None:
    """Print application metadata as indented JSON."""
    print(json.dumps(create_app_info(), indent=2))


if __name__ == "__main__":
    main()
