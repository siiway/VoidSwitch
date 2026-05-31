"""Structured logging setup using structlog."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure_logging(level: str = "INFO", console: bool = True) -> None:
    """Configure structlog + stdlib logging once at startup."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
    ]

    renderer: structlog.typing.Processor
    if console:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging (uvicorn, sqlalchemy) through a consistent level.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=log_level,
    )
    for noisy in ("uvicorn.access", "httpx", "httpcore", "aiosqlite"):
        logging.getLogger(noisy).setLevel(max(log_level, logging.WARNING))


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


# Header names whose values are credentials/secrets — never logged in the clear,
# even in debug mode.
_SENSITIVE_HEADERS = frozenset(
    {"authorization", "x-api-key", "cookie", "set-cookie", "proxy-authorization"}
)


def redact_headers(headers: Any) -> dict[str, str]:
    """Return a copy of ``headers`` with credential values masked for logging.

    Accepts any mapping-like header container (a ``dict`` or ``httpx.Headers``).
    The leading scheme/prefix is kept (e.g. ``Bearer sk-…1234``) so the shape is
    still visible while the secret itself is not.
    """
    items_fn = getattr(headers, "items", None)
    if not callable(items_fn):
        return {}
    items = [(str(k), str(v)) for k, v in items_fn()]
    out: dict[str, str] = {}
    for name, value in items:
        if name.lower() in _SENSITIVE_HEADERS:
            out[name] = _mask(value)
        else:
            out[name] = value
    return out


def _mask(value: str) -> str:
    """Mask a secret, keeping any auth scheme prefix and the last 4 chars."""
    scheme, sep, secret = value.partition(" ")
    if sep and scheme.lower() in ("bearer", "basic", "token"):
        tail = secret[-4:] if len(secret) > 8 else ""
        return f"{scheme} ***{tail}"
    tail = value[-4:] if len(value) > 8 else ""
    return f"***{tail}"
