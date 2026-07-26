"""xAI (official ``api.x.ai``) adapter.

An ``xai`` key may be a plain ``xai-…`` API key or an xAI OAuth credential
bundle (``{"access_token"?, "refresh_token", "expires_at"?}``) — for example a
refresh token converted from an SSO cookie by sub2api. Bundles are auto-resolved
to a live access token (and refreshed on a 401) via
:mod:`voidswitch.services.xai_oauth`; plain keys are used verbatim. Either way
the resolved credential is sent as ``Authorization: Bearer <token>`` by the
inherited OpenAI header builder.

The separate console ``grok`` adapter (SSO cookie, ``console.x.ai``) is
unrelated: it authenticates with the raw browser ``sso`` cookie, not an OAuth
bundle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from voidswitch.services import xai_oauth

from .openai import OpenAIProvider

if TYPE_CHECKING:
    from voidswitch.models.db import ApiKey


class XAIProvider(OpenAIProvider):
    type = "xai"
    default_base_url = "https://api.x.ai/v1"
    default_models = ("grok-2", "grok-beta", "*")
    refresh_on_invalid_key = True
    supports_import = True
    supports_refresh = True

    async def resolve_credential(
        self,
        session: Any,
        key: ApiKey,
        secret_key: str,
        *,
        force_refresh: bool = False,
    ) -> str:
        return await xai_oauth.resolve_access_token(
            session,
            key,
            secret_key=secret_key,
            force_refresh=force_refresh,
        )
