"""Cloudflare Workers AI adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .openai import OpenAIProvider

if TYPE_CHECKING:
    from voidswitch.models.db import Provider


class CloudflareProvider(OpenAIProvider):
    """Cloudflare Workers AI — OpenAI-compatible endpoint.

    API keys use the ``account_id@api_token`` format so multiple accounts can be
    pooled under one provider. The account id fills the ``{account_id}``
    placeholder in the base URL; the token is sent as the bearer credential. If
    ``@`` is absent the whole value is treated as the token and the base URL must
    already contain a concrete account id.
    Ref: https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/
    """

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

    def _base_url_for(self, account_id: str | None) -> str:
        raw = (self.record.base_url or self.default_base_url).rstrip("/")
        if account_id:
            raw = raw.replace("{account_id}", account_id)
        return raw

    @property
    def base_url(self) -> str:
        return self._base_url_for(self._cf_account_id)

    def headers(self, api_key: str, extra: dict[str, str] | None = None) -> dict[str, str]:
        self._cf_account_id, self._cf_token = self._parse_key(api_key)
        return super().headers(self._cf_token, extra)

    def build_request(
        self,
        api_key: str,
        body: dict[str, Any],
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        # Parse the composite key up front so ``{account_id}`` is substituted into
        # the URL. The base implementation evaluates ``upstream_url`` before
        # ``headers()``, which would leave the placeholder unresolved (Cloudflare
        # then 404s with error 7003) because only ``headers()`` sets the account id.
        self._cf_account_id, self._cf_token = self._parse_key(api_key)
        headers = super().headers(self._cf_token, extra_headers)
        return self.upstream_url, headers, self.prepare_body(body)
