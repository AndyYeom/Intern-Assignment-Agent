"""Tests for bounded credential-safe terminal login."""

from collections.abc import Iterator

import pytest
from argon2 import PasswordHasher

from project_catalog_agent.admin import (
    AdminAuthenticator,
    AdminCredential,
    AdminRole,
    AuthenticationStatus,
)
from project_catalog_agent.admin.terminal import TerminalAdminLogin
from tests.admin.test_authentication import TEST_CLARIFIER_PASSWORD


@pytest.fixture(scope="module")
def authenticator() -> AdminAuthenticator:
    """Create one test-only clarifier credential."""
    hasher = PasswordHasher(time_cost=1, memory_cost=8_192, parallelism=1)
    return AdminAuthenticator(
        credentials=(
            AdminCredential(
                username="clarifier",
                password_hash=hasher.hash(TEST_CLARIFIER_PASSWORD),
                role=AdminRole.CLARIFIER,
            ),
        ),
        password_hasher=hasher,
    )


def test_successful_login_uses_password_reader(
    authenticator: AdminAuthenticator,
) -> None:
    ordinary_prompts: list[str] = []
    password_prompts: list[str] = []
    login = TerminalAdminLogin(
        authenticator=authenticator,
        input_reader=lambda prompt: (ordinary_prompts.append(prompt), "clarifier")[1],
        password_reader=lambda prompt: (
            password_prompts.append(prompt),
            TEST_CLARIFIER_PASSWORD,
        )[1],
    )

    result = login.login(required_role=AdminRole.CLARIFIER)

    assert result.status is AuthenticationStatus.AUTHENTICATED
    assert result.actor_id == "clarifier"
    assert ordinary_prompts == ["Username: "]
    assert password_prompts == ["Password: "]


def test_failed_attempts_are_bounded_and_generic(
    authenticator: AdminAuthenticator,
) -> None:
    usernames: Iterator[str] = iter(["unknown", "clarifier", "unknown"])
    outputs: list[str] = []
    login = TerminalAdminLogin(
        authenticator=authenticator,
        input_reader=lambda _prompt: next(usernames),
        password_reader=lambda _prompt: "wrong-test-password",
        output_writer=outputs.append,
    )

    result = login.login(required_role=AdminRole.CLARIFIER)

    assert result.status is AuthenticationStatus.REJECTED
    assert result.error_code == "MAX_AUTHENTICATION_ATTEMPTS"
    assert outputs == ["Authentication failed."] * 3
    assert "wrong-test-password" not in "\n".join(outputs)


def test_unknown_username_and_wrong_password_have_same_output(
    authenticator: AdminAuthenticator,
) -> None:
    observed: list[list[str]] = []
    for username in ("unknown", "clarifier"):
        output: list[str] = []
        TerminalAdminLogin(
            authenticator=authenticator,
            max_attempts=1,
            input_reader=lambda _prompt, value=username: value,
            password_reader=lambda _prompt: "wrong-test-password",
            output_writer=output.append,
        ).login(required_role=AdminRole.CLARIFIER)
        observed.append(output)

    assert observed[0] == observed[1] == ["Authentication failed."]


def test_keyboard_interrupt_and_eof_cancel_safely(
    authenticator: AdminAuthenticator,
) -> None:
    for error in (KeyboardInterrupt(), EOFError()):
        outputs: list[str] = []

        def cancelled_reader(_prompt: str, failure: BaseException = error) -> str:
            raise failure

        result = TerminalAdminLogin(
            authenticator=authenticator,
            input_reader=cancelled_reader,
            output_writer=outputs.append,
        ).login(required_role=AdminRole.CLARIFIER)

        assert result.error_code == "AUTHENTICATION_CANCELLED"
        assert outputs == ["Authentication cancelled."]
