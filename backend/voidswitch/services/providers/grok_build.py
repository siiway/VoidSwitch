"""Grok Build adapter (xAI's ``grok`` coding CLI subscription).

Grok Build is a distinct xAI product from both the pay-as-you-go ``api.x.ai``
API (the :class:`~voidswitch.services.providers.xai.XAIProvider`) and the
``console.x.ai`` web session (the ``grok`` adapter). It is the entitlement behind
xAI's ``grok`` CLI: authentication is an OAuth *subscription* login (no static
``xai-…`` key), and inference is served by a dedicated CLI-chat proxy at
``https://cli-chat-proxy.grok.com/v1`` — **not** ``api.x.ai``.

Two things make this host special and are handled here:

* **Auth** — credentials are always an xAI OAuth bundle, signed in interactively
  from the dashboard (see :mod:`voidswitch.services.xai_oauth`) and refreshed on
  demand. There is no plain-key path.
* **Client identity** — ``cli-chat-proxy.grok.com`` rejects requests that do not
  identify themselves as a supported Grok CLI build, so every request carries the
  ``grok-shell`` client headers (:meth:`headers`). The exact header set mirrors
  the official CLI (verified against the ``grok2api`` reference).

Error classification (bad-key detection by body, transient 403 handling) is
inherited unchanged from :class:`XAIProvider`.
"""

from __future__ import annotations

from .xai import XAIProvider

# Pinned to the Grok CLI build the proxy currently accepts. ``cli-chat-proxy``
# gates on a recognised client version; bump these together when xAI rotates it.
GROK_BUILD_CLIENT_VERSION = "0.2.111"
GROK_BUILD_CLIENT_IDENTIFIER = "grok-shell"
GROK_BUILD_USER_AGENT = f"grok-shell/{GROK_BUILD_CLIENT_VERSION} (linux; x86_64)"
# xAI's OAuth-token auth marker required by the CLI-chat proxy's billing gate.
GROK_BUILD_TOKEN_AUTH = "xai-grok-cli"


class GrokBuildProvider(XAIProvider):
    type = "grok-build"
    # Grok Build inference is served by the CLI-chat proxy, not api.x.ai.
    default_base_url = "https://cli-chat-proxy.grok.com/v1"
    default_models = ("grok-4.5", "grok-code-fast-1", "*")
    refresh_on_invalid_key = True
    # Credentials only ever arrive via interactive OAuth sign-in, never a
    # pasted key or a cpa/sub2api import bundle.
    supports_import = False
    supports_oauth = True

    def headers(self, api_key: str, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Build the ``grok-shell`` client headers the CLI-chat proxy requires.

        ``cli-chat-proxy.grok.com`` refuses requests that do not present a
        recognised Grok CLI client version and token-auth marker, so the default
        OpenAI header set is replaced with the full CLI identity. Any
        provider-configured ``extra_headers`` and per-request ``extra`` still
        win (applied last) so an operator can override or pin a client version.
        """
        base = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
            "X-XAI-Token-Auth": GROK_BUILD_TOKEN_AUTH,
            "x-grok-client-version": GROK_BUILD_CLIENT_VERSION,
            "x-grok-client-identifier": GROK_BUILD_CLIENT_IDENTIFIER,
            "x-grok-client-mode": "headless",
            "User-Agent": GROK_BUILD_USER_AGENT,
        }
        if self.record.extra_headers:
            base.update({str(k): str(v) for k, v in self.record.extra_headers.items()})
        if extra:
            base.update(extra)
        return base
