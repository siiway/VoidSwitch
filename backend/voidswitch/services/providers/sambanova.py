"""SambaNova adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class SambaNovaProvider(OpenAIProvider):
    type = "sambanova"
    default_base_url = "https://api.sambanova.ai/v1"
    default_models = ("Meta-Llama-3.3-70B-Instruct", "*")
