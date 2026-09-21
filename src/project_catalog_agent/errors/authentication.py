"""Authentication configuration and infrastructure errors."""


class AdminCredentialConfigurationError(RuntimeError):
    """Configured administrator credentials are missing or malformed."""


class AuthenticationInfrastructureError(RuntimeError):
    """Password verification failed for a non-credential reason."""
