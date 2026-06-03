"""DeepSeek adapter with strict balance / auth edge-case handling.

References:
- Chat completion: https://api-docs.deepseek.com/api/create-chat-completion
- User balance:   https://api-docs.deepseek.com/api/get-user-balance
"""

from __future__ import annotations

from typing import Any

import httpx

from voidswitch.constants import ApiStyle
from voidswitch.core.logging import get_logger

from .base import BaseProvider, ErrorClass

log = get_logger("provider.deepseek")

# DeepSeek's thinking-mode models (e.g. deepseek-v4-pro) reject a multi-turn
# request when a *tool-calling* assistant turn arrives without its
# ``reasoning_content`` ("The reasoning_content in the thinking mode must be
# passed back to the API."). The gateway already round-trips real reasoning when
# the client preserves it (see ``transform._THINKING_SIGNATURE``), but Anthropic-
# dialect clients routinely drop reasoning blocks during multi-step tool loops
# (vercel/ai#11602) — by then the original chain-of-thought is gone and cannot be
# recovered by us or the client. Backfill a neutral placeholder on every
# tool-calling assistant turn that is missing one so the upstream accepts the
# turn. Turns without tool calls — and non-thinking models — ignore
# ``reasoning_content``, so applying this unconditionally is safe.
_REASONING_PLACEHOLDER = "(reasoning omitted)"


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


class DeepSeekProvider(BaseProvider):
    type = "deepseek"
    style = ApiStyle.OPENAI  # DeepSeek speaks the OpenAI Chat Completions dialect.
    default_base_url = "https://api.deepseek.com"
    # V4 model IDs. The legacy deepseek-chat / deepseek-reasoner aliases are retired
    # after 2026-07-24 (they map to deepseek-v4-flash non-thinking / thinking).
    default_models = ("deepseek-v4-flash", "deepseek-v4-pro")
    chat_suffix = "/chat/completions"
    models_suffix = "/models"
    balance_suffix = "/user/balance"

    def prepare_body(self, body: dict[str, Any]) -> dict[str, Any]:
        # Guarantee every tool-calling assistant turn carries reasoning_content so
        # thinking-mode models don't 400 (see ``_REASONING_PLACEHOLDER``). Real
        # reasoning the client preserved is left untouched; only missing/empty
        # ones are backfilled. Copies on write so the shared inbound payload (a
        # passthrough body is a shallow copy of it) is never mutated in place.
        messages = body.get("messages")
        if not isinstance(messages, list):
            return body
        patched: list[Any] = []
        changed = False
        for msg in messages:
            if (
                isinstance(msg, dict)
                and msg.get("role") == "assistant"
                and msg.get("tool_calls")
                and not _has_text(msg.get("reasoning_content"))
            ):
                msg = {**msg, "reasoning_content": _REASONING_PLACEHOLDER}
                changed = True
            patched.append(msg)
        return {**body, "messages": patched} if changed else body

    def classify(self, status_code: int, body: Any) -> ErrorClass:
        # DeepSeek returns 401 with an explicit authentication_error for a bad key.
        if status_code == 401:
            return ErrorClass.KEY_INVALID
        if status_code == 402:
            return ErrorClass.INSUFFICIENT_BALANCE
        if status_code == 422:
            # Insufficient balance is sometimes surfaced as 422 with a code.
            text = _error_text(body)
            if "insufficient" in text or "balance" in text:
                return ErrorClass.INSUFFICIENT_BALANCE
            return ErrorClass.BAD_REQUEST
        if status_code == 403:
            return ErrorClass.KEY_INVALID
        # Body-level auth signal even on unexpected codes.
        if isinstance(body, dict):
            err = body.get("error") or {}
            if isinstance(err, dict) and err.get("type") == "authentication_error":
                return ErrorClass.KEY_INVALID
        return super().classify(status_code, body)

    async def fetch_balance(
        self, client: httpx.AsyncClient, api_key: str
    ) -> tuple[bool, dict[str, Any]] | None:
        url = self.balance_url
        if not url:
            return None
        resp = await client.get(url, headers=self.headers(api_key))
        if resp.status_code == 401:
            # Key itself is invalid — surface as unavailable.
            return False, {"error": "authentication_error", "status": 401}
        resp.raise_for_status()
        data = resp.json()
        is_available = bool(data.get("is_available", False))
        return is_available, data


def _error_text(body: Any) -> str:
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return str(err.get("message", "")).lower()
        return str(err or body).lower()
    return str(body or "").lower()
