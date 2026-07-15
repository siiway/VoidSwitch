"""Volcengine Ark adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class VolcengineProvider(OpenAIProvider):
    type = "volcengine"
    default_base_url = "https://ark.cn-beijing.volces.com/api/v3"
    default_models = ("*",)
