"""
Custom Exception Classes for the Mini AI Business Intelligence Assistant
------------------------------------------------------------------------
Provides domain-specific exceptions for clear, actionable error handling
across data loading, SQL analytics, AI interpretation, and tool execution.
"""


class AssistantBaseException(Exception):
    """Base exception for all domain-specific assistant errors."""
    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class DataValidationError(AssistantBaseException):
    """Raised when data records fail business eligibility or validation rules."""
    pass


class AmbiguousQueryError(AssistantBaseException):
    """Raised when user natural language question lacks required parameters."""
    pass


class UnsupportedQueryError(AssistantBaseException):
    """Raised when user asks about topics outside the business domain or unsupported metrics."""
    pass


class ToolExecutionError(AssistantBaseException):
    """Raised when an approved analytical tool fails during database calculation."""
    pass


class LLMProviderError(AssistantBaseException):
    """Raised when the external LLM API encounters network, auth, or parsing failures."""
    pass


class DatasetNotFoundError(AssistantBaseException):
    """Raised when the primary CSV sales dataset cannot be found on disk."""
    pass
