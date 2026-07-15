"""Xiaomi MiMo adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class MiMoProvider(OpenAIProvider):
    type = "mimo"
    default_base_url = "https://api.xiaomimimo.com/v1"
    default_models = ("mimo-v2.5-pro", "mimo-v2-pro", "mimo-v2-flash", "mimo-v2-omni")
