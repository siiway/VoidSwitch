"""NVIDIA AI adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class NvidiaProvider(OpenAIProvider):
    type = "nvidia"
    default_base_url = "https://integrate.api.nvidia.com/v1"
    default_models = (
        "meta/llama-3.3-70b-instruct",
        "nvidia/llama-3.1-nemotron-70b-instruct",
        "*",
    )
