"""Tests for credential configuration and Argon2id authentication."""

from collections.abc import Mapping

import pytest
from argon2 import PasswordHasher

from project_catalog_agent.admin import (
    AdminAuthenticator,
    AdminCredential,
    AdminCredentialConfig,
    AdminRole,
    AuthenticationStatus,
)
from project_catalog_agent.errors import AdminCredentialConfigurationError

TEST_CLARIFIER_PASSWORD = "test-only-clarifier-password"
TEST_ESCALATOR_PASSWORD = "test-only-escalator-password"


@pytest.fixture(scope="module")
def password_hasher() -> PasswordHasher:
    """Use valid lower-cost Argon2 parameters for unit tests only."""
    return PasswordHasher(time_cost=1, memory_cost=8_192, parallelism=1)


@pytest.fixture(scope="module")
def environment(password_hasher: PasswordHasher) -> dict[str, str]:
    """Return complete test-only environment values."""
    return {
        "CLARIFIER_USERNAME": "clarifier",
        "CLARIFIER_PASSWORD_HASH": password_hasher.hash(TEST_CLARIFIER_PASSWORD),
        "ESCALATOR_USERNAME": "escalator",
        "ESCALATOR_PASSWORD_HASH": password_hasher.hash(TEST_ESCALATOR_PASSWORD),
    }


@pytest.fixture(scope="module")
def authenticator(
    environment: Mapping[str, str], password_hasher: PasswordHasher
) -> AdminAuthenticator:
    """Build an authenticator from validated test configuration."""
    config = AdminCredentialConfig.from_environment(environment)
    return AdminAuthenticator(
        credentials=config.credentials,
        password_hasher=password_hasher,
    )


def test_valid_environment_configuration_loads(
    environment: Mapping[str, str],
) -> None:
    config = AdminCredentialConfig.from_environment(environment)

    assert config.clarifier.username == "clarifier"
    assert config.clarifier.role is AdminRole.CLARIFIER
    assert config.escalator.role is AdminRole.ESCALATOR


@pytest.mark.parametrize(
    "updates",
    [
        {"CLARIFIER_PASSWORD_HASH": None},
        {"CLARIFIER_PASSWORD_HASH": ""},
        {"CLARIFIER_PASSWORD_HASH": "not-an-argon-hash"},
        {"ESCALATOR_USERNAME": "clarifier"},
        {"CLARIFIER_USERNAME": "   "},
    ],
)
def test_invalid_environment_fails_closed(
    environment: Mapping[str, str], updates: dict[str, str | None]
) -> None:
    values = dict(environment)
    for key, value in updates.items():
        if value is None:
            values.pop(key)
        else:
            values[key] = value

    with pytest.raises(AdminCredentialConfigurationError):
        AdminCredentialConfig.from_environment(values)


@pytest.mark.parametrize(
    ("username", "password", "role", "expected"),
    [
        (
            " clarifier ",
            TEST_CLARIFIER_PASSWORD,
            AdminRole.CLARIFIER,
            AuthenticationStatus.AUTHENTICATED,
        ),
        (
            "escalator",
            TEST_ESCALATOR_PASSWORD,
            AdminRole.ESCALATOR,
            AuthenticationStatus.AUTHENTICATED,
        ),
        (
            "clarifier",
            TEST_CLARIFIER_PASSWORD,
            AdminRole.ESCALATOR,
            AuthenticationStatus.REJECTED,
        ),
        (
            "escalator",
            TEST_ESCALATOR_PASSWORD,
            AdminRole.CLARIFIER,
            AuthenticationStatus.REJECTED,
        ),
        (
            "clarifier",
            "wrong-test-password",
            AdminRole.CLARIFIER,
            AuthenticationStatus.REJECTED,
        ),
        (
            "unknown",
            TEST_CLARIFIER_PASSWORD,
            AdminRole.CLARIFIER,
            AuthenticationStatus.REJECTED,
        ),
        (
            "",
            TEST_CLARIFIER_PASSWORD,
            AdminRole.CLARIFIER,
            AuthenticationStatus.REJECTED,
        ),
    ],
)
def test_authentication_and_exact_role_authorization(
    authenticator: AdminAuthenticator,
    username: str,
    password: str,
    role: AdminRole,
    expected: AuthenticationStatus,
) -> None:
    result = authenticator.authenticate(
        username=username,
        password=password,
        required_role=role,
    )

    assert result.status is expected
    serialized = result.model_dump_json()
    assert password not in serialized
    assert "password_hash" not in serialized
    if expected is AuthenticationStatus.REJECTED:
        assert result.message == "Authentication failed."


def test_malformed_direct_credential_is_rejected_at_startup() -> None:
    with pytest.raises(AdminCredentialConfigurationError):
        AdminAuthenticator(
            credentials=(
                AdminCredential(
                    username="clarifier",
                    password_hash="malformed",
                    role=AdminRole.CLARIFIER,
                ),
            )
        )


def test_role_authorizer_checks_exact_binding(
    authenticator: AdminAuthenticator,
) -> None:
    assert authenticator.is_authorized(
        actor_id="clarifier", required_role=AdminRole.CLARIFIER
    )
    assert not authenticator.is_authorized(
        actor_id="clarifier", required_role=AdminRole.ESCALATOR
    )
