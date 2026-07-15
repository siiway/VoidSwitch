"""SiliconFlow adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class SiliconFlowProvider(OpenAIProvider):
    type = "siliconflow"
    default_base_url = "https://api.siliconflow.cn/v1"
    default_models = ("deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct")
