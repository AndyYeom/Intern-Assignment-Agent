"""Errors raised while extracting project requirements."""


class RequirementExtractionError(Exception):
    """Base exception for structured requirement extraction."""


class RequirementExtractionConfigurationError(RequirementExtractionError):
    """Raised when the configured extraction provider cannot be initialized."""


class RequirementExtractionResponseError(RequirementExtractionError):
    """Raised when a provider response cannot produce a valid result."""
