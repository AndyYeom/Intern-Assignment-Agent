"""Tests for the hidden interactive password-hash setup command."""

import pytest
from argon2 import PasswordHasher

from project_catalog_agent.admin import AdminRole
from project_catalog_agent.admin_setup import generate_password_hash, main


def test_matching_hidden_inputs_produce_argon2id_hash_without_plaintext() -> None:
    secret = "test-only-setup-password"
    prompts: list[str] = []
    outputs: list[str] = []
    answers = iter([secret, secret])

    generated = generate_password_hash(
        role=AdminRole.CLARIFIER,
        password_reader=lambda prompt: (prompts.append(prompt), next(answers))[1],
        output_writer=outputs.append,
        password_hasher=PasswordHasher(time_cost=1, memory_cost=8_192, parallelism=1),
    )

    assert generated is not None
    assert generated.startswith("$argon2id$")
    assert len(prompts) == 2
    assert secret not in "\n".join(outputs)
    assert "CLARIFIER_PASSWORD_HASH" in outputs[0]


@pytest.mark.parametrize(
    "answers",
    [
        ("test-only-long-password", "different-long-password"),
        ("too-short", "too-short"),
        ("showmeyouragent", "showmeyouragent"),
    ],
)
def test_unsafe_password_inputs_are_rejected(answers: tuple[str, str]) -> None:
    values = iter(answers)
    outputs: list[str] = []

    generated = generate_password_hash(
        role=AdminRole.ESCALATOR,
        password_reader=lambda _prompt: next(values),
        output_writer=outputs.append,
    )

    assert generated is None
    assert answers[0] not in "\n".join(outputs)


def test_setup_command_does_not_accept_password_arguments() -> None:
    with pytest.raises(SystemExit):
        main(["--password", "not-accepted"])
