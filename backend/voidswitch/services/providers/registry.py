"""Registry mapping a provider ``type`` string to its adapter class."""

from __future__ import annotations

from voidswitch.models.db import Provider

from .anthropic import AnthropicProvider, ClaudeCodeProvider
from .base import BaseProvider
from .deepseek import DeepSeekProvider
from .openai import (
    CerebrasProvider,
    CloudflareProvider,
    DeepInfraProvider,
    FireworksProvider,
    GeminiProvider,
    GenericOpenAIProvider,
    GitHubModelsProvider,
    GroqProvider,
    HyperbolicProvider,
    MiMoProvider,
    MiniMaxProvider,
    MistralProvider,
    MoonshotProvider,
    NebiusProvider,
    NovitaProvider,
    NvidiaProvider,
    OpenAIProvider,
    OpenAIResponsesProvider,
    OpenRouterProvider,
    PerplexityProvider,
    QwenProvider,
    SambaNovaProvider,
    SiliconFlowProvider,
    TogetherProvider,
    VolcengineProvider,
    XAIProvider,
    ZhipuProvider,
)

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
            }
        )
    return catalog
