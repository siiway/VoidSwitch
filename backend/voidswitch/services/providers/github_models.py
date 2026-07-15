"""GitHub Models adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class GitHubModelsProvider(OpenAIProvider):
    type = "github-models"
    default_base_url = "https://models.github.ai/inference"
    default_models = ("gpt-4o", "gpt-4o-mini", "*")
