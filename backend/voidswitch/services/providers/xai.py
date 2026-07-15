"""xAI adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class XAIProvider(OpenAIProvider):
    type = "xai"
    default_base_url = "https://api.x.ai/v1"
    default_models = ("grok-2", "grok-beta", "*")
