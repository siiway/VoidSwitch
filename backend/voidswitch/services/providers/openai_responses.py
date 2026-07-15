"""OpenAI Responses API adapter."""

from __future__ import annotations

from voidswitch.constants import ApiStyle

from .openai import OpenAIProvider


class OpenAIResponsesProvider(OpenAIProvider):
    type = "openai-resp"
    style = ApiStyle.OPENAI_RESPONSES
    default_base_url = "https://api.openai.com/v1"
    default_models = ("gpt-5", "gpt-5-mini", "gpt-4.1", "o3", "o4-mini")
