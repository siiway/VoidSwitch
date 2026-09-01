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
