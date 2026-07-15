"""Cerebras adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class CerebrasProvider(OpenAIProvider):
    type = "cerebras"
    default_base_url = "https://api.cerebras.ai/v1"
    default_models = ("llama-3.3-70b", "llama3.1-8b", "*")
