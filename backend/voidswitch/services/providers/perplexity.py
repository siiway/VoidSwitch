"""Perplexity adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class PerplexityProvider(OpenAIProvider):
    type = "perplexity"
    default_base_url = "https://api.perplexity.ai"
    default_models = ("sonar", "sonar-pro", "sonar-reasoning", "*")
