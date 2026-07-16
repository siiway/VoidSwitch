"""Registry mapping a provider ``type`` string to its adapter class."""

from __future__ import annotations

from voidswitch.models.db import Provider

from .anthropic import AnthropicProvider
from .base import BaseProvider
from .cerebras import CerebrasProvider
from .claude_code import ClaudeCodeProvider
from .cloudflare import CloudflareProvider
from .deepinfra import DeepInfraProvider
from .deepseek import DeepSeekProvider
from .fireworks import FireworksProvider
from .gemini import GeminiProvider
from .generic import GenericOpenAIProvider
from .github_models import GitHubModelsProvider
from .grok import GrokProvider
from .groq import GroqProvider
from .hyperbolic import HyperbolicProvider
from .mimo import MiMoProvider
from .minimax import MiniMaxProvider
from .mistral import MistralProvider
from .moonshot import MoonshotProvider
from .nebius import NebiusProvider
from .novita import NovitaProvider
from .nvidia import NvidiaProvider
from .openai import OpenAIProvider
from .openai_responses import OpenAIResponsesProvider
from .openrouter import OpenRouterProvider
from .perplexity import PerplexityProvider
from .qwen import QwenProvider
from .sambanova import SambaNovaProvider
from .siliconflow import SiliconFlowProvider
from .together import TogetherProvider
from .volcengine import VolcengineProvider
from .xai import XAIProvider
from .zhipu import ZhipuProvider

_ADAPTERS: dict[str, type[BaseProvider]] = {
    cls.type: cls
    for cls in (
        OpenAIProvider,
        OpenAIResponsesProvider,
        AnthropicProvider,
        ClaudeCodeProvider,
        DeepSeekProvider,
        SiliconFlowProvider,
        OpenRouterProvider,
        GroqProvider,
        XAIProvider,
        GrokProvider,
        MoonshotProvider,
        MiMoProvider,
        NvidiaProvider,
        MistralProvider,
        TogetherProvider,
        FireworksProvider,
        PerplexityProvider,
        CerebrasProvider,
        CloudflareProvider,
        DeepInfraProvider,
        GeminiProvider,
        NovitaProvider,
        SambaNovaProvider,
        HyperbolicProvider,
        NebiusProvider,
        GitHubModelsProvider,
        ZhipuProvider,
        QwenProvider,
        VolcengineProvider,
        MiniMaxProvider,
        GenericOpenAIProvider,
    )
}


def adapter_types() -> list[str]:
    return sorted(_ADAPTERS)


def adapter_class(provider_type: str) -> type[BaseProvider]:
    return _ADAPTERS.get(provider_type, GenericOpenAIProvider)


def get_adapter(record: Provider) -> BaseProvider:
    return adapter_class(record.type)(record)


def adapter_catalog() -> list[dict[str, object]]:
    """Metadata used by the dashboard to populate the provider-type picker."""
    catalog: list[dict[str, object]] = []
    for name, cls in sorted(_ADAPTERS.items()):
        catalog.append(
            {
                "type": name,
                "style": cls.style.value,
                "default_base_url": cls.default_base_url,
                "default_models": list(cls.default_models),
                "supports_balance": cls.balance_suffix is not None,
                "supports_import": cls.supports_import,
            }
        )
    return catalog
