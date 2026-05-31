"""Provider adapter interface.

Each adapter encapsulates everything provider-specific: which API style the
upstream speaks, how to build the request URL and auth headers, how to classify
error responses (so the dispatcher knows whether to rotate the key, the proxy,
or give up), and (optionally) how to read a balance endpoint.

Adapters are stateless logic bound to a :class:`Provider` row at call time.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

import httpx

from voidswitch.constants import ApiStyle

if TYPE_CHECKING:
    from voidswitch.models.db import Provider


class ErrorClass(StrEnum):
    OK = "ok"
    KEY_INVALID = "key_invalid"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    RATE_LIMITED = "rate_limited"
    BAD_REQUEST = "bad_request"  # client's fault — return as-is, do not rotate
    SERVER_ERROR = "server_error"  # upstream/transient — rotate key/proxy & retry


class BaseProvider:
    type: str = "base"
    style: ApiStyle = ApiStyle.OPENAI
    default_base_url: str = ""
    default_models: tuple[str, ...] = ()

    chat_suffix: str = "/chat/completions"
    messages_suffix: str = "/v1/messages"
    models_suffix: str = "/models"
    balance_suffix: str | None = None
    anthropic_version: str = "2023-06-01"

    def __init__(self, record: Provider) -> None:
        self.record = record

    # -- URLs ------------------------------------------------------------- #
    @property
    def base_url(self) -> str:
        return (self.record.base_url or self.default_base_url).rstrip("/")

    @property
    def upstream_url(self) -> str:
        """The endpoint to POST a completion request to (depends on style)."""
        if self.style is ApiStyle.ANTHROPIC:
            return self.base_url + self.messages_suffix
        return self.base_url + self.chat_suffix

    @property
    def models_url(self) -> str:
        return self.base_url + self.models_suffix

    @property
    def balance_url(self) -> str | None:
        if self.record.balance_url:
            return self.record.balance_url
        if self.balance_suffix:
            return self.base_url + self.balance_suffix
        return None

    # -- Headers ---------------------------------------------------------- #
    def headers(self, api_key: str, extra: dict[str, str] | None = None) -> dict[str, str]:
        if self.style is ApiStyle.ANTHROPIC:
            base = {
                "x-api-key": api_key,
                "anthropic-version": self.anthropic_version,
                "content-type": "application/json",
            }
        else:
            base = {
                "Authorization": f"Bearer {api_key}",
                "content-type": "application/json",
            }
        if self.record.extra_headers:
            base.update({str(k): str(v) for k, v in self.record.extra_headers.items()})
        if extra:
            base.update(extra)
        return base

    # -- Model mapping ---------------------------------------------------- #
    def map_model(self, model: str) -> str:
        return self.record.model_map.get(model, model) if self.record.model_map else model

    # -- Outbound body hook ----------------------------------------------- #
    def prepare_body(self, body: dict[str, Any]) -> dict[str, Any]:
        """Last-chance mutation of the upstream request body.

        Default is a no-op. Adapters override this to inject provider-specific
        requirements (e.g. the Claude Code identity system prompt for OAuth).
        """
        return body

    # -- Error classification --------------------------------------------- #
    def classify(self, status_code: int, body: Any) -> ErrorClass:
        if 200 <= status_code < 300:
            return ErrorClass.OK
        if status_code in (401, 403):
            return ErrorClass.KEY_INVALID
        if status_code == 402:
            return ErrorClass.INSUFFICIENT_BALANCE
        if status_code == 429:
            return ErrorClass.RATE_LIMITED
        if status_code in (408, 409, 425) or status_code >= 500:
            return ErrorClass.SERVER_ERROR
        if 400 <= status_code < 500:
            return ErrorClass.BAD_REQUEST
        return ErrorClass.SERVER_ERROR

    # -- Balance ---------------------------------------------------------- #
    async def fetch_balance(
        self, client: httpx.AsyncClient, api_key: str
    ) -> tuple[bool, dict[str, Any]] | None:
        """Return ``(is_available, detail)`` or ``None`` if unsupported."""
        return None
