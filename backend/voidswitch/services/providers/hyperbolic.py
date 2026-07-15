"""Hyperbolic adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class HyperbolicProvider(OpenAIProvider):
    type = "hyperbolic"
    default_base_url = "https://api.hyperbolic.xyz/v1"
    default_models = ("*",)
