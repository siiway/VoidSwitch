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

from .base import ErrorClass
from .openai import OpenAIProvider

if TYPE_CHECKING:
    from voidswitch.models.db import ApiKey


# Substrings that mark a genuinely bad/expired credential in an xAI error body.
# ``api.x.ai`` returns "Incorrect API key provided" as an HTTP *400* (not 401/403)
# and "No credentials presented." as a 401, so we detect the real key failure by
# body content rather than trusting the status code alone.
_KEY_INVALID_MARKERS = (
    "incorrect api key",
    "invalid api key",
    "api key is invalid",
    "no credentials",
    "unauthenticated",
    "invalid authentication",
)


def _error_body_text(body: Any) -> str:
    """Lower-cased haystack of an xAI error body (``code`` + ``error`` fields).

    xAI wraps errors as ``{"code": "...", "error": "..."}`` but tolerates the
    OpenAI ``{"error": {"message": "..."}}`` shape too; fall back to ``str`` for
    anything else so a plain-text body still matches.
    """
    if isinstance(body, dict):
        parts: list[str] = []
        for field in ("code", "error", "message", "detail"):
            value = body.get(field)
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, dict):
                nested = value.get("message") or value.get("type")
                if isinstance(nested, str):
                    parts.append(nested)
        if parts:
            return " ".join(parts).lower()
    if body is None:
        return ""
    return str(body).lower()


class XAIProvider(OpenAIProvider):
    type = "xai"
    default_base_url = "https://api.x.ai/v1"
    # grok-2 / grok-beta were retired by xAI (``api.x.ai`` now answers "Model not
    # found") — advertise current model ids plus ``*`` so any live model passes.
    default_models = (
        "grok-4",
        "grok-4-fast-reasoning",
        "grok-3",
        "grok-3-mini",
        "grok-code-fast-1",
        "*",
    )
    refresh_on_invalid_key = True
    supports_import = True
    supports_refresh = True

    def classify(self, status_code: int, body: Any) -> ErrorClass:
        """Classify xAI upstream responses.

        Unlike the OpenAI-style default, a bare HTTP **403** from ``api.x.ai`` is
        *not* treated as an invalid key: xAI signals a bad/expired credential
        with a 400/401 whose body says so (e.g. "Incorrect API key provided"),
        while a 403 typically means a transient block — region/geo restriction,
        Cloudflare bot-protection, or a per-model/team permission gate. Mapping
        such a 403 to ``KEY_INVALID`` would disable a perfectly good key on the
        first hiccup, so we:

        * detect the real credential failure by body content (any status), and
        * downgrade an otherwise-unexplained 403 to a transient ``SERVER_ERROR``
          so the key is rotated/retried instead of being disabled.
        """
        text = _error_body_text(body)
        if any(marker in text for marker in _KEY_INVALID_MARKERS):
            return ErrorClass.KEY_INVALID
        if status_code == 403:
            return ErrorClass.SERVER_ERROR
        return super().classify(status_code, body)

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
