"""Anthropic API adapter."""

from __future__ import annotations

from voidswitch.constants import ApiStyle

from .base import BaseProvider


class AnthropicProvider(BaseProvider):
    type = "anthropic"
    style = ApiStyle.ANTHROPIC
    default_base_url = "https://api.anthropic.com"
    default_models = (
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
    )
    messages_suffix = "/v1/messages"
    models_suffix = "/v1/models"
