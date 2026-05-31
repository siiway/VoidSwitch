"""OpenAI-compatible adapters (OpenAI, and any /v1/chat/completions provider)."""

from __future__ import annotations

from voidswitch.constants import ApiStyle

from .base import BaseProvider


class OpenAIProvider(BaseProvider):
    type = "openai"
    style = ApiStyle.OPENAI
    default_base_url = "https://api.openai.com/v1"
    default_models = ("gpt-4o", "gpt-4o-mini", "gpt-4.1", "o3", "o4-mini")


class SiliconFlowProvider(OpenAIProvider):
    type = "siliconflow"
    default_base_url = "https://api.siliconflow.cn/v1"
    default_models = ("deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct")


class OpenRouterProvider(OpenAIProvider):
    type = "openrouter"
    default_base_url = "https://openrouter.ai/api/v1"
    default_models = ("*",)


class GroqProvider(OpenAIProvider):
    type = "groq"
    default_base_url = "https://api.groq.com/openai/v1"
    default_models = ("llama-3.3-70b-versatile", "*")


class XAIProvider(OpenAIProvider):
    type = "xai"
    default_base_url = "https://api.x.ai/v1"
    default_models = ("grok-2", "grok-beta", "*")


class MoonshotProvider(OpenAIProvider):
    type = "moonshot"
    default_base_url = "https://api.moonshot.cn/v1"
    default_models = ("moonshot-v1-8k", "kimi-k2", "*")


class GenericOpenAIProvider(OpenAIProvider):
    """Catch-all for any self-hosted / unlisted OpenAI-compatible endpoint."""

    type = "generic"
    default_base_url = ""
    default_models = ("*",)
