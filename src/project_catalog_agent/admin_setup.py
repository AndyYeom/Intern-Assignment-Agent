"""Interactive Argon2id hash setup command for terminal administrators."""

import argparse
import getpass
from collections.abc import Callable, Sequence

from argon2 import PasswordHasher

from project_catalog_agent.admin import AdminRole

InputReader = Callable[[str], str]
OutputWriter = Callable[[str], None]
_MINIMUM_PASSWORD_LENGTH = 12
_RETIRED_DEVELOPMENT_PASSWORD = "show" + "meyouragent"


def generate_password_hash(
    *,
    role: AdminRole,
    password_reader: InputReader = getpass.getpass,
    output_writer: OutputWriter = print,
    password_hasher: PasswordHasher | None = None,
) -> str | None:
    """Read and confirm a hidden password, then print only its Argon2id hash."""
    try:
        password = password_reader("New password: ")
        confirmation = password_reader("Confirm password: ")
    except (EOFError, KeyboardInterrupt):
        output_writer("Password setup cancelled.")
        return None
    if password != confirmation:
        output_writer("Passwords do not match.")
        return None
    if len(password) < _MINIMUM_PASSWORD_LENGTH:
        output_writer("Password must contain at least 12 characters.")
        return None
    if password == _RETIRED_DEVELOPMENT_PASSWORD:
        output_writer("That password is not permitted.")
        return None
    generated_hash = (password_hasher or PasswordHasher()).hash(password)
    variable_name = (
        "CLARIFIER_PASSWORD_HASH"
        if role is AdminRole.CLARIFIER
        else "ESCALATOR_PASSWORD_HASH"
    )
    output_writer(f"Store this value as {variable_name}:")
    output_writer(generated_hash)
    return generated_hash


def main(
    argv: Sequence[str] | None = None,
    *,
    input_reader: InputReader = input,
    password_reader: InputReader = getpass.getpass,
    output_writer: OutputWriter = print,
) -> int:
    """Run the interactive setup command without accepting secret arguments."""
    parser = argparse.ArgumentParser(
        description="Generate an administrator Argon2id password hash interactively."
    )
    parsed = parser.parse_args(argv)
    del parsed
    try:
        selected = input_reader("Account (clarifier/escalator): ").strip()
    except (EOFError, KeyboardInterrupt):
        output_writer("Password setup cancelled.")
        return 1
    try:
        role = AdminRole(selected)
    except ValueError:
        output_writer("Unknown administrator account.")
        return 1
    return (
        0
        if generate_password_hash(
            role=role,
            password_reader=password_reader,
            output_writer=output_writer,
        )
        is not None
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
