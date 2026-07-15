"""OpenRouter adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class OpenRouterProvider(OpenAIProvider):
    type = "openrouter"
    default_base_url = "https://openrouter.ai/api/v1"
    default_models = ("*",)
