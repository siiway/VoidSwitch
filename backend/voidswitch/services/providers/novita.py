"""Novita adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class NovitaProvider(OpenAIProvider):
    type = "novita"
    default_base_url = "https://api.novita.ai/v3/openai"
    default_models = ("*",)
