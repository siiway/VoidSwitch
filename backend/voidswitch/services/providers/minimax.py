"""MiniMax adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class MiniMaxProvider(OpenAIProvider):
    type = "minimax"
    default_base_url = "https://api.minimax.io/v1"
    default_models = ("MiniMax-M2", "*")
