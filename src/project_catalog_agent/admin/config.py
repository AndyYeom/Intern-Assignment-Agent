"""Environment-backed administrator credential configuration."""

import os
from collections.abc import Mapping
from dataclasses import dataclass

from argon2 import Type, extract_parameters
from argon2.exceptions import InvalidHashError
from dotenv import load_dotenv

from project_catalog_agent.admin.roles import AdminRole
from project_catalog_agent.errors import AdminCredentialConfigurationError


@dataclass(frozen=True)
class AdminCredential:
    """One immutable configured username, hash, and role binding."""

    username: str
    password_hash: str
    role: AdminRole


@dataclass(frozen=True)
class AdminCredentialConfig:
    """Complete fail-closed V1 administrator credential configuration."""

    clarifier: AdminCredential
    escalator: AdminCredential

    @property
    def credentials(self) -> tuple[AdminCredential, ...]:
        """Return credentials in stable role order."""
        return (self.clarifier, self.escalator)

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "AdminCredentialConfig":
        """Load both role bindings without exposing configured hash values."""
        if environment is None:
            load_dotenv()
            values: Mapping[str, str] = os.environ
        else:
            values = environment
        clarifier = AdminCredential(
            username=values.get("CLARIFIER_USERNAME", "clarifier").strip(),
            password_hash=values.get("CLARIFIER_PASSWORD_HASH", "").strip(),
            role=AdminRole.CLARIFIER,
        )
        escalator = AdminCredential(
            username=values.get("ESCALATOR_USERNAME", "escalator").strip(),
            password_hash=values.get("ESCALATOR_PASSWORD_HASH", "").strip(),
            role=AdminRole.ESCALATOR,
        )
        cls._validate(clarifier, escalator)
        return cls(clarifier=clarifier, escalator=escalator)

    @staticmethod
    def _validate(*credentials: AdminCredential) -> None:
        usernames: set[str] = set()
        for credential in credentials:
            if not credential.username:
                raise AdminCredentialConfigurationError(
                    "administrator username is required"
                )
            if credential.username in usernames:
                raise AdminCredentialConfigurationError(
                    "administrator usernames must be different"
                )
            usernames.add(credential.username)
            validate_argon2id_hash(credential.password_hash)


def validate_argon2id_hash(password_hash: str) -> None:
    """Reject missing, malformed, or non-Argon2id configured hashes."""
    if not password_hash:
        raise AdminCredentialConfigurationError(
            "administrator password hash is required"
        )
    try:
        parameters = extract_parameters(password_hash)
    except (InvalidHashError, ValueError) as error:
        raise AdminCredentialConfigurationError(
            "administrator password hash is invalid"
        ) from error
    if parameters.type is not Type.ID:
        raise AdminCredentialConfigurationError(
            "administrator password hash must use Argon2id"
        )
