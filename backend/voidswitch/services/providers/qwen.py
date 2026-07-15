"""Qwen adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class QwenProvider(OpenAIProvider):
    type = "qwen"
    default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_models = ("qwen-max", "qwen-plus", "qwen-turbo", "*")
