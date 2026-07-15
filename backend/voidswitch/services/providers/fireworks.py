"""Fireworks adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class FireworksProvider(OpenAIProvider):
    type = "fireworks"
    default_base_url = "https://api.fireworks.ai/inference/v1"
    default_models = ("accounts/fireworks/models/llama-v3p3-70b-instruct", "*")
