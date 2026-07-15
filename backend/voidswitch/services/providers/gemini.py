"""Google Gemini OpenAI-compatible adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class GeminiProvider(OpenAIProvider):
    type = "gemini"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
    default_models = ("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash", "*")
