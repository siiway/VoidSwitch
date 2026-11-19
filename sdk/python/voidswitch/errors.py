"""Errors raised by the SDK."""

from __future__ import annotations

from typing import Any


class VoidSwitchError(Exception):
    """Base class for every SDK failure.

    ``status`` is the HTTP status code when the failure came from the server, and
    ``None`` for transport errors. ``detail`` is the server's message verbatim.
    """

    def __init__(self, message: str, *, status: int | None = None, detail: str | None = None):
        super().__init__(message)
        self.status = status
        self.detail = detail or message


class TransportError(VoidSwitchError):
    """The request never reached the server (DNS, TLS, timeout)."""


class UnauthorizedError(VoidSwitchError):
    """The API key is missing, unknown, disabled or expired."""


class PermissionError(VoidSwitchError):  # noqa: A001 - mirrors the HTTP name
    """The key's scopes do not cover this action, or the owner lost staff access."""


class NotFoundError(VoidSwitchError):
    """The addressed object does not exist (or is not visible to the key)."""


class RateLimitError(VoidSwitchError):
    """The per-key platform API rate limit was exceeded."""


class InvalidRequestError(VoidSwitchError):
    """The server rejected the payload."""


_STATUS_MAP = {
    401: UnauthorizedError,
    403: PermissionError,
    404: NotFoundError,
    422: InvalidRequestError,
    429: RateLimitError,
}


def error_for(status: int | None, message: str, payload: Any = None) -> VoidSwitchError:
    """Map an HTTP status to the matching error class."""
    detail = message
    if isinstance(payload, dict) and isinstance(payload.get("detail"), str):
        detail = payload["detail"]
    cls = _STATUS_MAP.get(status or 0, VoidSwitchError)
    return cls(detail, status=status, detail=detail)