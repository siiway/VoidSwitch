"""DeepInfra adapter."""

from __future__ import annotations

from .openai import OpenAIProvider


class DeepInfraProvider(OpenAIProvider):
    type = "deepinfra"
    default_base_url = "https://api.deepinfra.com/v1/openai"
    default_models = ("meta-llama/Llama-3.3-70B-Instruct", "*")
