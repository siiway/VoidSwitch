"""Generic OpenAI-compatible adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class GenericOpenAIProvider(OpenAIProvider):
    type = "generic"
    default_base_url = ""
    default_models = ("*",)
