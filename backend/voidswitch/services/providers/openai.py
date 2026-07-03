"""OpenAI-compatible adapters (OpenAI, and any /v1/chat/completions provider)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from voidswitch.constants import ApiStyle

from .base import BaseProvider

if TYPE_CHECKING:
    from voidswitch.models.db import Provider


class OpenAIProvider(BaseProvider):
    type = "openai"
    style = ApiStyle.OPENAI
    default_base_url = "https://api.openai.com/v1"
    default_models = ("gpt-4o", "gpt-4o-mini", "gpt-4.1", "o3", "o4-mini")


class OpenAIResponsesProvider(OpenAIProvider):
    """OpenAI provider that speaks the newer **Responses API** (``/v1/responses``).

    Same base URL and Bearer auth as :class:`OpenAIProvider`, but the upstream is
    called with the Responses request/response/stream shape (OpenAI's recommended
    primary API). The gateway translates inbound OpenAI-chat / Anthropic requests
    to and from the Responses format transparently.
    """

    type = "openai-resp"
    style = ApiStyle.OPENAI_RESPONSES
    default_base_url = "https://api.openai.com/v1"
    default_models = ("gpt-5", "gpt-5-mini", "gpt-4.1", "o3", "o4-mini")


class SiliconFlowProvider(OpenAIProvider):
    type = "siliconflow"
    default_base_url = "https://api.siliconflow.cn/v1"
    default_models = ("deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct")


class OpenRouterProvider(OpenAIProvider):
    type = "openrouter"
    default_base_url = "https://openrouter.ai/api/v1"
    default_models = ("*",)


class GroqProvider(OpenAIProvider):
    type = "groq"
    default_base_url = "https://api.groq.com/openai/v1"
    default_models = ("llama-3.3-70b-versatile", "*")


class XAIProvider(OpenAIProvider):
    type = "xai"
    default_base_url = "https://api.x.ai/v1"
    default_models = ("grok-2", "grok-beta", "*")


class MoonshotProvider(OpenAIProvider):
    type = "moonshot"
    default_base_url = "https://api.moonshot.cn/v1"
    default_models = ("moonshot-v1-8k", "kimi-k2", "*")


class MiMoProvider(OpenAIProvider):
    """Xiaomi MiMo Open Platform (the "Token Plan" offering).

    OpenAI-compatible chat at /v1/chat/completions; standard Bearer auth. There is
    no programmatic balance/quota endpoint (usage is web-console only), so balance
    probing is unsupported — invalid keys are caught at dispatch via classify().
    Ref: https://platform.xiaomimimo.com/docs/en-US/api/chat/openai-api
    """

    type = "mimo"
    default_base_url = "https://api.xiaomimimo.com/v1"
    default_models = ("mimo-v2.5-pro", "mimo-v2-pro", "mimo-v2-flash", "mimo-v2-omni")


class NvidiaProvider(OpenAIProvider):
    """NVIDIA AI (NIM / API catalog at build.nvidia.com).

    OpenAI-compatible inference for 80+ hosted models; standard Bearer auth. No
    OpenAI-format balance endpoint (free credits are tracked account-side only),
    so balance probing is unsupported. Ref: https://integrate.api.nvidia.com
    """

    type = "nvidia"
    default_base_url = "https://integrate.api.nvidia.com/v1"
    default_models = ("meta/llama-3.3-70b-instruct", "nvidia/llama-3.1-nemotron-70b-instruct", "*")


# --------------------------------------------------------------------------- #
# More OpenAI-compatible presets. All speak /chat/completions with Bearer auth
# and expose no OpenAI-format balance endpoint, so balance probing is off and bad
# keys are caught by classify() (401/403 → KEY_INVALID) at dispatch. base_url and
# the model list are editable per-provider in the dashboard; "*" = allow any model.
# --------------------------------------------------------------------------- #


class MistralProvider(OpenAIProvider):
    type = "mistral"
    default_base_url = "https://api.mistral.ai/v1"
    default_models = ("mistral-large-latest", "mistral-small-latest", "codestral-latest", "*")


class TogetherProvider(OpenAIProvider):
    type = "together"
    default_base_url = "https://api.together.xyz/v1"
    default_models = (
        "deepseek-ai/DeepSeek-V3",
        "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "*",
    )


class FireworksProvider(OpenAIProvider):
    type = "fireworks"
    default_base_url = "https://api.fireworks.ai/inference/v1"
    default_models = ("accounts/fireworks/models/llama-v3p3-70b-instruct", "*")


class PerplexityProvider(OpenAIProvider):
    type = "perplexity"
    default_base_url = "https://api.perplexity.ai"
    default_models = ("sonar", "sonar-pro", "sonar-reasoning", "*")


class CerebrasProvider(OpenAIProvider):
    type = "cerebras"
    default_base_url = "https://api.cerebras.ai/v1"
    default_models = ("llama-3.3-70b", "llama3.1-8b", "*")


class DeepInfraProvider(OpenAIProvider):
    type = "deepinfra"
    default_base_url = "https://api.deepinfra.com/v1/openai"
    default_models = ("meta-llama/Llama-3.3-70B-Instruct", "*")


class GeminiProvider(OpenAIProvider):
    """Google Gemini via its OpenAI-compatibility endpoint."""

    type = "gemini"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
    default_models = ("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash", "*")


class NovitaProvider(OpenAIProvider):
    type = "novita"
    default_base_url = "https://api.novita.ai/v3/openai"
    default_models = ("*",)


class SambaNovaProvider(OpenAIProvider):
    type = "sambanova"
    default_base_url = "https://api.sambanova.ai/v1"
    default_models = ("Meta-Llama-3.3-70B-Instruct", "*")


class HyperbolicProvider(OpenAIProvider):
    type = "hyperbolic"
    default_base_url = "https://api.hyperbolic.xyz/v1"
    default_models = ("*",)


class NebiusProvider(OpenAIProvider):
    type = "nebius"
    default_base_url = "https://api.studio.nebius.com/v1"
    default_models = ("*",)


class GitHubModelsProvider(OpenAIProvider):
    """GitHub Models — authenticate with a GitHub PAT as the Bearer token."""

    type = "github-models"
    default_base_url = "https://models.github.ai/inference"
    default_models = ("gpt-4o", "gpt-4o-mini", "*")


class ZhipuProvider(OpenAIProvider):
    """Zhipu AI / GLM (open.bigmodel.cn; overseas: api.z.ai/api/paas/v4)."""

    type = "zhipu"
    default_base_url = "https://open.bigmodel.cn/api/paas/v4"
    default_models = ("glm-4.6", "glm-4.5", "glm-4-flash", "*")


class QwenProvider(OpenAIProvider):
    """Alibaba Qwen via DashScope OpenAI-compatible mode (Beijing region)."""

    type = "qwen"
    default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_models = ("qwen-max", "qwen-plus", "qwen-turbo", "*")


class VolcengineProvider(OpenAIProvider):
    """Volcengine Ark (ByteDance Doubao). Models are Ark endpoint IDs."""

    type = "volcengine"
    default_base_url = "https://ark.cn-beijing.volces.com/api/v3"
    default_models = ("*",)


class MiniMaxProvider(OpenAIProvider):
    """MiniMax OpenAI-compatible endpoint (international; CN: api.minimaxi.com)."""

    type = "minimax"
    default_base_url = "https://api.minimax.io/v1"
    default_models = ("MiniMax-M2", "*")


class CloudflareProvider(OpenAIProvider):
    """Cloudflare Workers AI — OpenAI-compatible endpoint.

    API keys support the ``account_id@api_token`` format to pool multiple
    accounts under one provider. If ``@`` is absent the key is treated as a
    plain token and the ``{account_id}`` placeholder in the base URL is left
    as-is (the user must supply the full URL without a placeholder).
    Ref: https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/
    """

    type = "cloudflare"
    default_base_url = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"
    default_models = ("*",)

    def __init__(self, record: Provider) -> None:
        super().__init__(record)
        self._cf_account_id: str | None = None
        self._cf_token: str | None = None

    @staticmethod
    def _parse_key(plaintext: str) -> tuple[str | None, str]:
        if "@" in plaintext:
            account_id, token = plaintext.split("@", 1)
            return account_id, token
        return None, plaintext

    @property
    def base_url(self) -> str:
        raw = (self.record.base_url or self.default_base_url).rstrip("/")
        if self._cf_account_id:
            raw = raw.replace("{account_id}", self._cf_account_id)
        return raw

    def headers(self, api_key: str, extra: dict[str, str] | None = None) -> dict[str, str]:
        self._cf_account_id, self._cf_token = self._parse_key(api_key)
        return super().headers(self._cf_token, extra)


class GenericOpenAIProvider(OpenAIProvider):
    """Catch-all for any self-hosted / unlisted OpenAI-compatible endpoint."""

    type = "generic"
    default_base_url = ""
    default_models = ("*",)
