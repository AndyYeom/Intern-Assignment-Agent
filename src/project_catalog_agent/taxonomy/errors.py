"""Exceptions raised by taxonomy loading and validation."""


class TaxonomyError(Exception):
    """Base exception for taxonomy operations."""


class TaxonomyLoadError(TaxonomyError):
    """Raised when taxonomy data cannot be read or parsed."""


class TaxonomyValidationError(TaxonomyError):
    """Raised when taxonomy data violates its schema or integrity rules."""


class TaxonomyNormalizationError(TaxonomyError):
    """Raised when taxonomy normalization cannot be completed safely."""


class TaxonomySelectionError(TaxonomyNormalizationError):
    """Raised when a taxonomy selector cannot produce a proposal."""


class TaxonomySelectionResponseError(TaxonomySelectionError):
    """Raised when a selector proposal is malformed or references unknown IDs."""
