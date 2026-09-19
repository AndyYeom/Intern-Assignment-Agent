"""Argon2id administrator authentication service."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from project_catalog_agent.admin.config import (
    AdminCredential,
    validate_argon2id_hash,
)
from project_catalog_agent.admin.contracts import (
    AuthenticationResult,
    AuthenticationStatus,
)
from project_catalog_agent.admin.roles import AdminRole
from project_catalog_agent.errors import (
    AdminCredentialConfigurationError,
    AuthenticationInfrastructureError,
)

_GENERIC_FAILURE = "Authentication failed."


class AdminAuthenticator:
    """Authenticate configured identities and authorize one exact role."""

    def __init__(
        self,
        *,
        credentials: tuple[AdminCredential, ...],
        password_hasher: PasswordHasher | None = None,
    ) -> None:
        for credential in credentials:
            if not credential.username.strip():
                raise AdminCredentialConfigurationError(
                    "administrator username is required"
                )
            validate_argon2id_hash(credential.password_hash)
        if len({item.username for item in credentials}) != len(credentials):
            raise AdminCredentialConfigurationError(
                "administrator usernames must be unique"
            )
        self._credentials = credentials
        self._password_hasher = password_hasher or PasswordHasher()

    def authenticate(
        self,
        *,
        username: str,
        password: str,
        required_role: AdminRole,
    ) -> AuthenticationResult:
        """Verify the exact password and role without returning credentials."""
        normalized_username = username.strip()
        credential = next(
            (
                item
                for item in self._credentials
                if item.username == normalized_username
            ),
            None,
        )
        if credential is None:
            return self._rejected("AUTHENTICATION_REJECTED")
        try:
            self._password_hasher.verify(credential.password_hash, password)
            self._password_hasher.check_needs_rehash(credential.password_hash)
        except VerifyMismatchError:
            return self._rejected("AUTHENTICATION_REJECTED")
        except (InvalidHashError, VerificationError) as error:
            raise AuthenticationInfrastructureError(
                "administrator credential verification failed"
            ) from error
        if credential.role is not required_role:
            return self._rejected("AUTHENTICATION_REJECTED")
        return AuthenticationResult(
            status=AuthenticationStatus.AUTHENTICATED,
            actor_id=credential.username,
            role=credential.role,
            message="Authenticated.",
        )

    def is_authorized(
        self,
        *,
        actor_id: str,
        required_role: AdminRole,
    ) -> bool:
        """Authorize only configured identities with the exact required role."""
        return any(
            item.username == actor_id and item.role is required_role
            for item in self._credentials
        )

    @staticmethod
    def _rejected(error_code: str) -> AuthenticationResult:
        return AuthenticationResult(
            status=AuthenticationStatus.REJECTED,
            message=_GENERIC_FAILURE,
            error_code=error_code,
        )
