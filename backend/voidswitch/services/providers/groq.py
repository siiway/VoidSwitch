"""Groq adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class GroqProvider(OpenAIProvider):
    type = "groq"
    default_base_url = "https://api.groq.com/openai/v1"
    default_models = ("llama-3.3-70b-versatile", "*")
