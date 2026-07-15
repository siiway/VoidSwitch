"""OpenAI adapter and base class for OpenAI-compatible providers."""

from __future__ import annotations

from voidswitch.constants import ApiStyle

from .base import BaseProvider


class OpenAIProvider(BaseProvider):
    type = "openai"
    style = ApiStyle.OPENAI
    default_base_url = "https://api.openai.com/v1"
    default_models = ("gpt-4o", "gpt-4o-mini", "gpt-4.1", "o3", "o4-mini")
