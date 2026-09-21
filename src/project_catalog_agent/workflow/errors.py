"""Workflow facade boundary errors."""


class WorkflowNotFoundError(LookupError):
    """No checkpoint exists for the requested workflow thread."""


class WorkflowThreadMismatchError(ValueError):
    """A checkpoint thread belongs to a different catalog request."""


class WorkflowNotAwaitingClarificationError(ValueError):
    """A resume was attempted for a workflow that is not interrupted."""
