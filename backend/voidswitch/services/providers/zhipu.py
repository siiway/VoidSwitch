"""Zhipu AI adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class ZhipuProvider(OpenAIProvider):
    type = "zhipu"
    default_base_url = "https://open.bigmodel.cn/api/paas/v4"
    default_models = ("glm-4.6", "glm-4.5", "glm-4-flash", "*")
