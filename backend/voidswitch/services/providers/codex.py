"""OpenAI Codex CLI subscription adapter."""

from __future__ import annotations

import base64
import json
from typing import Any

from voidswitch.constants import ApiStyle
from voidswitch.services import codex_oauth

from .openai import OpenAIProvider


class CodexProvider(OpenAIProvider):
    type = "codex"
    style = ApiStyle.OPENAI_RESPONSES
    default_base_url = "https://chatgpt.com/backend-api/codex"
    default_models = (
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "*",
    )
    supports_oauth = True
    supports_refresh = True
    supports_import = True
    refresh_on_invalid_key = True

    # The ChatGPT Codex backend only speaks SSE and rejects every other shape:
    # ``stream: false`` or ``store: true`` are answered with HTTP 400
    # (``{"detail": "Store must be set to false"}``). These constraints are
    # absolute — they apply no matter what the client (or a generic
    # transformer default) asked for, so they live on the adapter and are
    # enforced last, after every other transform.
    upstream_requires_streaming = True
    upstream_requires_store_false = True

    # The Codex backend only accepts a narrow Responses request shape. Keep
    # only known-good wire fields and drop everything else. The endpoint
    # currently rejects both temperature/top_p and max_output_tokens; the
    # client-facing token limit must not be forwarded as that field.
    _WIRE_FIELDS = frozenset(
        {
            "model",
            "instructions",
            "input",
            "tools",
            "tool_choice",
            "parallel_tool_calls",
            "reasoning",
            "store",
            "stream",
            "include",
            "service_tier",
            "prompt_cache_key",
            "text",
            "truncation",
            "metadata",
            "background",
            "conversation",
            "previous_response_id",
            "user",
        }
    )

    async def resolve_credential(
        self, session: Any, key: Any, secret_key: str, *, force_refresh: bool = False
    ) -> str:
        return await codex_oauth.resolve_access_token(
            session, key, secret_key=secret_key, force_refresh=force_refresh
        )

    @staticmethod
    def _account_id(access_token: str) -> str | None:
        try:
            part = access_token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
            auth = claims.get("https://api.openai.com/auth", {})
            value = auth.get("chatgpt_account_id") if isinstance(auth, dict) else None
            return str(value) if value else None
        except Exception:
            return None

    # -- Outbound body hook ----------------------------------------------- #
    def prepare_body(self, body: dict[str, Any]) -> dict[str, Any]:
        """Enforce the Codex backend's wire contract.

        This runs last (after style translation and the generic stream
        handling), so a client-supplied ``store: true`` — or any default
        injected upstream of the adapter — can never reach chatgpt.com.
        Unknown/unsupported parameters (``max_output_tokens``, ``temperature``,
        ``stop``, ``stream_options``, …) are dropped: the backend 400s on them.
        ``include: reasoning.encrypted_content`` is defaulted like codex-cli
        so reasoning sessions round-trip.
        """
        body = {k: v for k, v in body.items() if k in self._WIRE_FIELDS}
        body["store"] = False
        body["stream"] = True
        include = body.get("include")
        if not isinstance(include, list):
            include = []
        if "reasoning.encrypted_content" not in include:
            include.append("reasoning.encrypted_content")
        body["include"] = include
        return body

    def aggregate_stream_body(self, body: dict[str, Any]) -> dict[str, Any]:
        """A ``stream=false`` client got its reply folded from the upstream
        SSE stream; describe it accordingly (ephemeral, not stored)."""
        body = dict(body)
        body["store"] = False
        return body

    # -- Headers ---------------------------------------------------------- #
    def headers(self, api_key: str, extra: dict[str, str] | None = None) -> dict[str, str]:
        base = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
            "accept": "text/event-stream",
            "originator": "codex_cli_rs",
            "User-Agent": "codex_cli_rs",
        }
        account_id = self._account_id(api_key)
        if account_id:
            base["ChatGPT-Account-Id"] = account_id
        if self.record.extra_headers:
            base.update({str(k): str(v) for k, v in self.record.extra_headers.items()})
        if extra:
            base.update(extra)
        return base
