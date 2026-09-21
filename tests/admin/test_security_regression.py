"""Security regression checks for administrator credentials."""

from pathlib import Path

from project_catalog_agent.catalog.contracts import (
    CreateProjectRequest,
    create_initial_catalog_state,
)

ROOT = Path(__file__).parents[2]


def test_production_source_has_no_retired_plaintext_credential() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "src").rglob("*.py")
    )

    assert "showmeyouragent" not in source.casefold()
    assert "plaintext_password =" not in source


def test_state_serialization_has_no_credential_fields() -> None:
    state = create_initial_catalog_state(
        CreateProjectRequest(
            request_id="SEC-001",
            project_name="Security Test",
            project_description="No credentials belong in state.",
        )
    )
    serialized = state.model_dump_json().casefold()

    assert "password" not in serialized
    assert "authorization" not in serialized
    assert "token" not in serialized


def test_environment_example_and_ignore_rules_are_safe() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "CLARIFIER_PASSWORD_HASH=\n" in example
    assert "ESCALATOR_PASSWORD_HASH=\n" in example
    assert "$argon2" not in example
    assert ".env\n" in ignore
    assert ".env.*" in ignore
    assert "!.env.example" in ignore
