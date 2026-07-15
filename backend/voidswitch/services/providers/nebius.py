"""Nebius adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class NebiusProvider(OpenAIProvider):
    type = "nebius"
    default_base_url = "https://api.studio.nebius.com/v1"
    default_models = ("*",)
