"""Moonshot adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class MoonshotProvider(OpenAIProvider):
    type = "moonshot"
    default_base_url = "https://api.moonshot.cn/v1"
    default_models = ("moonshot-v1-8k", "kimi-k2", "*")
