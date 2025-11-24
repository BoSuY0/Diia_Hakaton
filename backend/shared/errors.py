from __future__ import annotations


class MetaNotFoundError(Exception):
    pass


class SessionNotFoundError(Exception):
    pass


class ValidationError(Exception):
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code
