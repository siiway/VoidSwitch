"""Grok (console.x.ai) SSO-cookie adapter.

Unlike :class:`~voidswitch.services.providers.xai.XAIProvider`, which targets the
official ``api.x.ai`` REST API with a Bearer API key, this adapter talks to the
``console.x.ai`` web backend the way https://github.com/jiujiu532/grok2api does:
it authenticates with an ``sso`` cookie token and speaks the OpenAI *Responses*
API that console.x.ai natively serves, unlocking the free Grok console models.

The provider "key" secret stores the SSO token — the value of the ``sso`` cookie
from a logged-in console.x.ai browser session, with or without a leading
``sso=`` prefix. When the network requires a ``cf_clearance`` cookie it can be
supplied through the provider's **extra headers** as a ``Cookie`` entry
(e.g. ``Cookie: cf_clearance=...``); it is appended to the SSO cookie rather
than replacing it.
"""

from __future__ import annotations

from typing import Any

from voidswitch.constants import ApiStyle

from .base import ErrorClass
from .openai import OpenAIProvider

# Exposed model name -> real console.x.ai model id. The exposed names carry the
# reasoning effort as a suffix so callers can pin it without a request field.
CONSOLE_MODELS: dict[str, str] = {
    "grok-4.3-console": "grok-4.3",
    "grok-4.3-low": "grok-4.3",
    "grok-4.3-medium": "grok-4.3",
    "grok-4.3-high": "grok-4.3",
    "grok-4.20-0309-reasoning-console": "grok-4.20-0309-reasoning",
    "grok-4.20-0309-console": "grok-4.20-0309",
    "grok-4.20-0309-non-reasoning-console": "grok-4.20-0309-non-reasoning",
    "grok-4.20-multi-agent-console": "grok-4.20-multi-agent-0309",
    "grok-4.20-multi-agent-low": "grok-4.20-multi-agent-0309",
    "grok-4.20-multi-agent-medium": "grok-4.20-multi-agent-0309",
    "grok-4.20-multi-agent-high": "grok-4.20-multi-agent-0309",
    "grok-4.20-multi-agent-xhigh": "grok-4.20-multi-agent-0309",
    "grok-build-console": "grok-build-0.1",
}

# Exposed model name -> forced reasoning effort (overrides any caller effort).
_MODEL_FIXED_EFFORT: dict[str, str] = {
    "grok-4.3-low": "low",
    "grok-4.3-medium": "medium",
    "grok-4.3-high": "high",
    "grok-4.20-multi-agent-low": "low",
    "grok-4.20-multi-agent-medium": "medium",
    "grok-4.20-multi-agent-high": "high",
    "grok-4.20-multi-agent-xhigh": "xhigh",
}

# console model -> default max_output_tokens (a caller-supplied value wins).
_MODEL_MAX_TOKENS: dict[str, int] = {
    "grok-4.20-multi-agent-0309": 2_000_000,
    "grok-build-0.1": 256_000,
}
_DEFAULT_MAX_TOKENS = 1_000_000

# console models that accept a ``reasoning.effort`` field.
_REASONING_MODELS = frozenset({"grok-4.3", "grok-4.20-multi-agent-0309"})

# console models that get the web_search / x_search tools.
_SEARCH_MODELS = frozenset(
    {
        "grok-4.20-multi-agent-0309",
        "grok-4.20-0309",
        "grok-4.20-0309-reasoning",
        "grok-4.20-0309-non-reasoning",
        "grok-4.3",
        "grok-build-0.1",
    }
)

# OpenAI reasoning_effort -> console effort.
_EFFORT_MAP: dict[str, str] = {
    "none": "none",
    "minimal": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
}
_DEFAULT_EFFORT = "low"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


def _normalize_effort(effort: str) -> str:
    return _EFFORT_MAP.get(effort.strip().lower(), "medium")


class GrokProvider(OpenAIProvider):
    type = "grok"
    style = ApiStyle.OPENAI_RESPONSES
    default_base_url = "https://console.x.ai/v1"
    default_models = (*CONSOLE_MODELS, "*")
    supports_import = True

    # -- Headers ---------------------------------------------------------- #
    def headers(self, api_key: str, extra: dict[str, str] | None = None) -> dict[str, str]:
        token = api_key.strip()
        if token.startswith("sso="):
            token = token[4:]
        base: dict[str, str] = {
            "Authorization": "Bearer anonymous",
            "Cookie": f"sso={token}; sso-rw={token}",
            "content-type": "application/json",
            "accept": "*/*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "origin": "https://console.x.ai",
            "referer": "https://console.x.ai/",
            "user-agent": _USER_AGENT,
            "x-cluster": "https://us-east-1.api.x.ai",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }
        if self.record.extra_headers:
            _merge_headers(base, {str(k): str(v) for k, v in self.record.extra_headers.items()})
        if extra:
            _merge_headers(base, extra)
        return base

    # -- Outbound body hook ----------------------------------------------- #
    def prepare_body(self, body: dict[str, Any]) -> dict[str, Any]:
        body = dict(body)
        exposed = str(body.get("model") or "")
        console_model = CONSOLE_MODELS.get(exposed, exposed)
        body["model"] = console_model
        body["store"] = False
        body["include"] = ["reasoning.encrypted_content"]
        body.setdefault(
            "max_output_tokens",
            _MODEL_MAX_TOKENS.get(console_model, _DEFAULT_MAX_TOKENS),
        )
        body.setdefault("temperature", 0.7)
        body.setdefault("top_p", 0.95)

        if console_model in _REASONING_MODELS:
            body["reasoning"] = {"effort": self._resolve_effort(exposed, body)}
        else:
            body.pop("reasoning", None)

        # Give search-capable models web/X access, but never clobber a caller
        # that brought its own tool set (function calling).
        if console_model in _SEARCH_MODELS and not body.get("tools"):
            body["tools"] = [
                {"type": "web_search", "enable_image_understanding": True},
                {"type": "x_search", "enable_video_understanding": True},
            ]
            body["tool_choice"] = "auto"
        return body

    @staticmethod
    def _resolve_effort(exposed: str, body: dict[str, Any]) -> str:
        fixed = _MODEL_FIXED_EFFORT.get(exposed)
        if fixed is not None:
            return fixed
        reasoning = body.get("reasoning")
        if isinstance(reasoning, dict) and reasoning.get("effort"):
            return _normalize_effort(str(reasoning["effort"]))
        return _DEFAULT_EFFORT

    # -- Error classification --------------------------------------------- #
    def classify(self, status_code: int, body: Any) -> ErrorClass:
        # An expired / invalid SSO token surfaces as 401/403; console.x.ai also
        # returns 429 once the anonymous quota (~30 req / 15 min) is exhausted.
        if status_code in (401, 403):
            return ErrorClass.KEY_INVALID
        if status_code == 429:
            return ErrorClass.RATE_LIMITED
        return super().classify(status_code, body)


def _merge_headers(base: dict[str, str], incoming: dict[str, str]) -> None:
    """Merge caller/record headers, appending (not replacing) any Cookie."""
    for key, value in incoming.items():
        if key.lower() == "cookie":
            existing = base.get("Cookie", "")
            base["Cookie"] = f"{existing}; {value}" if existing else value
        else:
            base[key] = value
