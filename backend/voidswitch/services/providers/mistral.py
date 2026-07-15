"""Mistral adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class MistralProvider(OpenAIProvider):
    type = "mistral"
    default_base_url = "https://api.mistral.ai/v1"
    default_models = ("mistral-large-latest", "mistral-small-latest", "codestral-latest", "*")
