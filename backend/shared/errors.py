"""Custom exception classes for the application."""
from __future__ import annotations


class MetaNotFoundError(Exception):
    """Raised when category metadata is not found."""


class SessionNotFoundError(Exception):
    """Raised when a session is not found."""


class ValidationError(Exception):
    """Raised when field validation fails."""
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code
