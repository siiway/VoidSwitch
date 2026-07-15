"""Together AI adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class TogetherProvider(OpenAIProvider):
    type = "together"
    default_base_url = "https://api.together.xyz/v1"
    default_models = ("deepseek-ai/DeepSeek-V3", "meta-llama/Llama-3.3-70B-Instruct-Turbo", "*")
