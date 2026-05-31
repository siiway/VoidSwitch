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


class DeepSeekProvider(BaseProvider):
    type = "deepseek"
    style = ApiStyle.OPENAI  # DeepSeek speaks the OpenAI Chat Completions dialect.
    default_base_url = "https://api.deepseek.com"
    default_models = ("deepseek-chat", "deepseek-reasoner")
    chat_suffix = "/chat/completions"
    models_suffix = "/models"
    balance_suffix = "/user/balance"

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
