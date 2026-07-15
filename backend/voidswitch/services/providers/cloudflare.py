"""Cloudflare Workers AI adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .openai import OpenAIProvider

if TYPE_CHECKING:
    from voidswitch.models.db import Provider


class CloudflareProvider(OpenAIProvider):
    type = "cloudflare"
    default_base_url = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"
    default_models = ("*",)

    def __init__(self, record: Provider) -> None:
        super().__init__(record)
        self._cf_account_id: str | None = None
        self._cf_token: str | None = None

    @staticmethod
    def _parse_key(plaintext: str) -> tuple[str | None, str]:
        if "@" in plaintext:
            account_id, token = plaintext.split("@", 1)
            return account_id, token
        return None, plaintext

    @property
    def base_url(self) -> str:
        raw = (self.record.base_url or self.default_base_url).rstrip("/")
        if self._cf_account_id:
            raw = raw.replace("{account_id}", self._cf_account_id)
        return raw

    def headers(self, api_key: str, extra: dict[str, str] | None = None) -> dict[str, str]:
        self._cf_account_id, self._cf_token = self._parse_key(api_key)
        return super().headers(self._cf_token, extra)
