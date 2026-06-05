"""Unit tests: security, transform, providers, network, database init."""

from __future__ import annotations

import json

import pytest
from voidswitch.constants import DEFAULT_SETTINGS, ApiStyle
from voidswitch.core.security import (
    create_session_token,
    decode_session_token,
    decrypt_secret,
    encrypt_secret,
    hash_token,
)
from voidswitch.models.db import Provider
from voidswitch.services import transform
from voidswitch.services.network import Route, build_transport
from voidswitch.services.providers.base import ErrorClass
from voidswitch.services.providers.deepseek import DeepSeekProvider
from voidswitch.services.providers.registry import adapter_catalog, get_adapter

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- #
# Security
# --------------------------------------------------------------------------- #


async def test_token_hash_stable():
    assert hash_token("abc") == hash_token("abc")
    assert hash_token("abc") != hash_token("abd")


async def test_secret_roundtrip():
    cipher = encrypt_secret("sk-secret", secret="app-secret")
    assert cipher != "sk-secret"
    assert decrypt_secret(cipher, secret="app-secret") == "sk-secret"
    # Plaintext fallback when value was never encrypted.
    assert decrypt_secret("not-encrypted", secret="app-secret") == "not-encrypted"


async def test_session_jwt_roundtrip():
    token = create_session_token(secret="s", subject="user-1", extra={"role": "owner"})
    claims = decode_session_token(token, secret="s")
    assert claims["sub"] == "user-1"
    assert claims["role"] == "owner"


# --------------------------------------------------------------------------- #
# Transform — requests
# --------------------------------------------------------------------------- #


async def test_openai_request_to_anthropic_system_and_tools():
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hi"},
        ],
        "max_tokens": 100,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "w",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        "tool_choice": "auto",
    }
    out = transform.openai_request_to_anthropic(payload)
    assert out["system"] == "be brief"
    assert out["messages"] == [{"role": "user", "content": "hi"}]
    assert out["tools"][0]["name"] == "get_weather"
    assert out["tool_choice"] == {"type": "auto"}
    assert out["max_tokens"] == 100


async def test_anthropic_request_to_openai_roundtrips_system():
    payload = {
        "model": "claude-3-5-haiku-latest",
        "system": "be brief",
        "max_tokens": 50,
        "messages": [{"role": "user", "content": "hi"}],
    }
    out = transform.anthropic_request_to_openai(payload)
    assert out["messages"][0] == {"role": "system", "content": "be brief"}
    assert out["messages"][1] == {"role": "user", "content": "hi"}
    assert out["max_tokens"] == 50


# --------------------------------------------------------------------------- #
# Transform — responses
# --------------------------------------------------------------------------- #


async def test_anthropic_response_to_openai():
    resp = {
        "id": "msg_1",
        "model": "claude-3-5-haiku-latest",
        "content": [{"type": "text", "text": "hello"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 5, "output_tokens": 3},
    }
    out = transform.anthropic_response_to_openai(resp, model="x")
    assert out["choices"][0]["message"]["content"] == "hello"
    assert out["choices"][0]["finish_reason"] == "stop"
    assert out["usage"] == {
        "prompt_tokens": 5,
        "completion_tokens": 3,
        "total_tokens": 8,
    }


async def test_openai_response_to_anthropic_with_tool_call():
    resp = {
        "id": "chatcmpl_1",
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "f", "arguments": '{"a":1}'},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 4},
    }
    out = transform.openai_response_to_anthropic(resp, model="x")
    assert out["stop_reason"] == "tool_use"
    tool_block = next(b for b in out["content"] if b["type"] == "tool_use")
    assert tool_block["name"] == "f"
    assert tool_block["input"] == {"a": 1}


# --------------------------------------------------------------------------- #
# Transform — streaming
# --------------------------------------------------------------------------- #


async def _collect(aiter):
    chunks = []
    async for piece in aiter:
        chunks.append(piece.decode())
    return "".join(chunks)


async def _byte_iter(parts):
    for p in parts:
        yield p.encode()


async def test_anthropic_stream_to_openai():
    events = [
        'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":3}}}\n\n',
        'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n',
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hi"}}\n\n',
        'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":1}}\n\n',
        'event: message_stop\ndata: {"type":"message_stop"}\n\n',
    ]
    out = await _collect(transform.anthropic_stream_to_openai(_byte_iter(events), model="gpt-4o"))
    assert '"role": "assistant"' in out
    assert '"content": "Hi"' in out
    assert "data: [DONE]" in out
    assert '"finish_reason": "stop"' in out


async def test_openai_stream_to_anthropic():
    chunks = [
        'data: {"choices":[{"index":0,"delta":{"role":"assistant"}}]}\n\n',
        'data: {"choices":[{"index":0,"delta":{"content":"Hi"}}]}\n\n',
        'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":3,"completion_tokens":1}}\n\n',
        "data: [DONE]\n\n",
    ]
    out = await _collect(transform.openai_stream_to_anthropic(_byte_iter(chunks), model="claude"))
    assert "event: message_start" in out
    assert "text_delta" in out
    assert "event: message_stop" in out
    assert '"stop_reason": "end_turn"' in out


# --------------------------------------------------------------------------- #
# Transform — reasoning / thinking round-trip
# --------------------------------------------------------------------------- #


async def test_anthropic_request_thinking_becomes_reasoning_content():
    """A replayed thinking block must reach an OpenAI upstream as reasoning_content
    so DeepSeek-style thinking mode accepts the follow-up turn."""
    payload = {
        "model": "deepseek-v4-pro",
        "max_tokens": 64,
        "messages": [
            {"role": "user", "content": "weather?"},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "let me check", "signature": "sig"},
                    {"type": "tool_use", "id": "tu_1", "name": "get_weather", "input": {"q": "x"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu_1", "content": "sunny"}
                ],
            },
        ],
    }
    out = transform.anthropic_request_to_openai(payload)
    assistant = next(m for m in out["messages"] if m["role"] == "assistant")
    assert assistant["reasoning_content"] == "let me check"
    assert assistant["tool_calls"][0]["function"]["name"] == "get_weather"


async def test_openai_response_reasoning_becomes_thinking_block():
    resp = {
        "id": "chatcmpl_1",
        "model": "deepseek-v4-pro",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "the answer",
                    "reasoning_content": "thinking hard",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 4},
    }
    out = transform.openai_response_to_anthropic(resp, model="x")
    assert out["content"][0]["type"] == "thinking"
    assert out["content"][0]["thinking"] == "thinking hard"
    assert out["content"][0]["signature"]  # signed so clients replay it
    assert out["content"][1] == {"type": "text", "text": "the answer"}


async def test_openai_stream_reasoning_becomes_thinking_block():
    chunks = [
        'data: {"choices":[{"index":0,"delta":{"role":"assistant"}}]}\n\n',
        'data: {"choices":[{"index":0,"delta":{"reasoning_content":"hmm"}}]}\n\n',
        'data: {"choices":[{"index":0,"delta":{"content":"Hi"}}]}\n\n',
        'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":3,"completion_tokens":1}}\n\n',
        "data: [DONE]\n\n",
    ]
    out = await _collect(transform.openai_stream_to_anthropic(_byte_iter(chunks), model="ds"))
    assert '"type": "thinking"' in out
    assert "thinking_delta" in out
    assert "signature_delta" in out  # thinking block sealed before text starts
    assert "text_delta" in out
    # thinking block (index 0) precedes the text block (index 1)
    assert out.index('"thinking"') < out.index("text_delta")


async def test_anthropic_response_thinking_becomes_reasoning_content():
    resp = {
        "id": "msg_1",
        "model": "claude-x",
        "content": [
            {"type": "thinking", "thinking": "deep thought", "signature": "s"},
            {"type": "text", "text": "answer"},
        ],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 5, "output_tokens": 3},
    }
    out = transform.anthropic_response_to_openai(resp, model="x")
    msg = out["choices"][0]["message"]
    assert msg["reasoning_content"] == "deep thought"
    assert msg["content"] == "answer"


async def test_anthropic_stream_thinking_becomes_reasoning_content():
    events = [
        'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":3}}}\n\n',
        'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":""}}\n\n',
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"hmm"}}\n\n',
        'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":1}}\n\n',
        'event: message_stop\ndata: {"type":"message_stop"}\n\n',
    ]
    out = await _collect(transform.anthropic_stream_to_openai(_byte_iter(events), model="gpt-4o"))
    assert "reasoning_content" in out
    assert "hmm" in out


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #


async def test_deepseek_classify():
    provider = Provider(name="ds", type="deepseek", base_url="https://api.deepseek.com")
    adapter = DeepSeekProvider(provider)
    assert adapter.classify(401, {"error": {"type": "authentication_error"}}) == (
        ErrorClass.KEY_INVALID
    )
    assert adapter.classify(402, {}) == ErrorClass.INSUFFICIENT_BALANCE
    assert adapter.classify(429, {}) == ErrorClass.RATE_LIMITED
    assert adapter.classify(200, {}) == ErrorClass.OK
    assert adapter.classify(500, {}) == ErrorClass.SERVER_ERROR
    assert adapter.classify(400, {}) == ErrorClass.BAD_REQUEST


async def test_adapter_urls_and_style():
    provider = Provider(name="ds", type="deepseek", base_url="https://api.deepseek.com")
    adapter = get_adapter(provider)
    assert adapter.style is ApiStyle.OPENAI
    assert adapter.upstream_url == "https://api.deepseek.com/chat/completions"
    assert adapter.balance_url == "https://api.deepseek.com/user/balance"


async def test_anthropic_adapter_headers():
    provider = Provider(name="an", type="anthropic", base_url="https://api.anthropic.com")
    adapter = get_adapter(provider)
    assert adapter.style is ApiStyle.ANTHROPIC
    headers = adapter.headers("sk-ant")
    assert headers["x-api-key"] == "sk-ant"
    assert "anthropic-version" in headers
    assert adapter.upstream_url == "https://api.anthropic.com/v1/messages"


async def test_routes_for_provider_proxy_modes():
    from voidswitch.constants import ProxyMode
    from voidswitch.models.db import Proxy
    from voidswitch.services.selector import routes_for_provider

    p1 = Proxy(url="http://a:1", status="active")
    p1.id = 1
    p2 = Proxy(url="http://b:2", status="active")
    p2.id = 2
    pool = [p1, p2]

    # all → whole pool (both proxies, no direct).
    routes = routes_for_provider(Provider(name="x", proxy_mode=ProxyMode.ALL.value), pool)
    assert [pr.id for _, pr in routes if pr] == [1, 2]

    # all with empty pool → single direct route.
    routes = routes_for_provider(Provider(name="x", proxy_mode=ProxyMode.ALL.value), [])
    assert routes == [(routes[0][0], None)] and routes[0][0].proxy_url is None

    # direct → always direct, ignores the pool.
    routes = routes_for_provider(Provider(name="x", proxy_mode=ProxyMode.DIRECT.value), pool)
    assert len(routes) == 1 and routes[0][1] is None and routes[0][0].proxy_url is None

    # selected → only the assigned proxy, no direct fallback.
    prov = Provider(name="x", proxy_mode=ProxyMode.SELECTED.value, proxy_ids=[2])
    routes = routes_for_provider(prov, pool)
    assert [pr.id for _, pr in routes if pr] == [2]
    assert routes[0][0].proxy_url == "http://b:2"

    # selected with no active assigned proxy → empty (caller skips the provider).
    prov = Provider(name="x", proxy_mode=ProxyMode.SELECTED.value, proxy_ids=[99])
    assert routes_for_provider(prov, pool) == []


async def test_model_routes_and_key_pools():
    from voidswitch.models.db import ApiKey
    from voidswitch.services.selector import (
        provider_serves_model,
        resolve_model,
        select_keys,
    )

    prov = Provider(
        name="ds",
        type="deepseek",
        models=["deepseek-v4-flash"],
        model_map={},
        model_routes=[
            {"alias": "deepseek-v4-flash-lkd", "upstream": "deepseek-v4-flash", "pool": "leaked"},
            {"alias": "deepseek-v4-flash", "upstream": "deepseek-v4-flash", "pool": "members"},
        ],
    )
    # An alias is served even if it isn't in `models`.
    assert provider_serves_model(prov, "deepseek-v4-flash-lkd")
    # Route resolution → (upstream, pool).
    assert resolve_model(prov, "deepseek-v4-flash-lkd") == ("deepseek-v4-flash", "leaked")
    assert resolve_model(prov, "deepseek-v4-flash") == ("deepseek-v4-flash", "members")
    # No route → unchanged model, no pool.
    assert resolve_model(prov, "other") == ("other", "")

    def _key(h: str, pool: str) -> ApiKey:
        return ApiKey(
            provider_id=1,
            key_ciphertext="x",
            key_hash=h,
            pool=pool,
            status="active",
            weight=1,
            failed_count=0,
            total_requests=0,
        )

    prov.keys = [_key("leaked-1", "leaked"), _key("member-1", "members")]
    assert [k.key_hash for k in select_keys(prov, "leaked")] == ["leaked-1"]
    assert [k.key_hash for k in select_keys(prov, "members")] == ["member-1"]
    assert {k.key_hash for k in select_keys(prov, "")} == {"leaked-1", "member-1"}


async def test_deleting_proxy_scrubs_provider_references(db):
    from starlette.requests import Request
    from voidswitch.api.admin.proxies import delete_proxy
    from voidswitch.models.db import Provider, Proxy, User

    request = Request({"type": "http", "client": ("test", 0), "headers": []})

    async with db.session() as session:
        proxy = Proxy(url="http://gone:1", status="active")
        session.add(proxy)
        prov = Provider(name="p", type="openai", proxy_mode="selected")
        session.add(prov)
        await session.flush()
        pid, provider_id = proxy.id, prov.id
        prov.proxy_ids = [pid, 999]  # 999 is an already-dangling ref
        await session.flush()

    async with db.session() as session:
        await delete_proxy(
            pid, request=request, session=session, user=User(sub="admin", role="owner")
        )

    async with db.session() as session:
        prov = await session.get(Provider, provider_id)
        assert pid not in prov.proxy_ids  # the deleted proxy is scrubbed
        assert prov.proxy_ids == [999]  # other entries are left untouched


async def test_adapter_catalog_nonempty():
    catalog = adapter_catalog()
    types = {c["type"] for c in catalog}
    assert {"openai", "anthropic", "deepseek", "claude-code", "mimo", "nvidia"} <= types


async def test_openai_compatible_presets():
    # OpenAI-style presets, standard Bearer auth, no balance endpoint (so the
    # balance probe skips them); invalid keys fall back to KEY_INVALID via classify.
    presets = {
        "mimo": "https://api.xiaomimimo.com/v1",
        "nvidia": "https://integrate.api.nvidia.com/v1",
        "mistral": "https://api.mistral.ai/v1",
        "together": "https://api.together.xyz/v1",
        "fireworks": "https://api.fireworks.ai/inference/v1",
        "perplexity": "https://api.perplexity.ai",
        "cerebras": "https://api.cerebras.ai/v1",
        "deepinfra": "https://api.deepinfra.com/v1/openai",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
        "novita": "https://api.novita.ai/v3/openai",
        "sambanova": "https://api.sambanova.ai/v1",
        "hyperbolic": "https://api.hyperbolic.xyz/v1",
        "nebius": "https://api.studio.nebius.com/v1",
        "github-models": "https://models.github.ai/inference",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4",
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "volcengine": "https://ark.cn-beijing.volces.com/api/v3",
        "minimax": "https://api.minimax.io/v1",
    }
    catalog = {c["type"]: c for c in adapter_catalog()}
    for ptype, base in presets.items():
        adapter = get_adapter(Provider(name=ptype, type=ptype))
        assert adapter.style is ApiStyle.OPENAI, ptype
        assert adapter.base_url == base, ptype
        assert adapter.upstream_url == base + "/chat/completions", ptype
        assert adapter.balance_url is None, ptype
        assert adapter.default_models, ptype
        assert adapter.headers("k")["Authorization"] == "Bearer k", ptype
        assert adapter.classify(401, {}) == ErrorClass.KEY_INVALID, ptype
        assert adapter.classify(200, {}) == ErrorClass.OK, ptype
        assert catalog[ptype]["type"] == ptype
        assert catalog[ptype]["supports_balance"] is False, ptype


async def test_claude_code_oauth_headers_and_identity():
    from voidswitch.services.providers.anthropic import (
        CLAUDE_CODE_IDENTITY,
        ClaudeCodeProvider,
    )

    provider = Provider(name="cc", type="claude-code", base_url="https://api.anthropic.com")
    adapter = get_adapter(provider)
    assert isinstance(adapter, ClaudeCodeProvider)

    # Bearer OAuth, not x-api-key; the exact CLI fingerprint (UA, x-app, the SDK's
    # x-stainless-* telemetry) is sent verbatim.
    headers = adapter.headers("sk-ant-oat01-xyz", {"anthropic-beta": "context-1m-2025-08-07"})
    assert headers["Authorization"] == "Bearer sk-ant-oat01-xyz"
    assert "x-api-key" not in headers
    assert headers["user-agent"] == "claude-cli/2.1.158 (external, cli)"
    assert headers["x-app"] == "cli"
    assert headers["x-stainless-lang"] == "js"
    assert headers["x-stainless-runtime"] == "node"
    assert headers["x-stainless-package-version"] == "0.94.0"

    betas = headers["anthropic-beta"].split(",")
    assert "oauth-2025-04-20" in betas  # mandatory: enables Bearer OAuth
    assert "claude-code-20250219" in betas  # mandatory: marks the traffic as Claude Code
    assert "context-1m-2025-08-07" in betas  # passthrough beta preserved

    # System blocks: identity prefix first (cached), then caller content — exactly
    # Claude Code's splitSysPromptPrefix. No extra/billing block is injected.
    out = adapter.prepare_body({"system": "Be terse.", "messages": []})
    assert out["system"][0]["text"] == CLAUDE_CODE_IDENTITY
    assert out["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert out["system"][1]["text"] == "Be terse."

    # Identity isn't duplicated when the caller already leads with it.
    pre = {"system": [{"type": "text", "text": CLAUDE_CODE_IDENTITY + " extra"}]}
    blocks = adapter.prepare_body(pre)["system"]
    assert blocks[0]["text"].startswith(CLAUDE_CODE_IDENTITY)
    assert sum(1 for b in blocks if b["text"].startswith(CLAUDE_CODE_IDENTITY)) == 1


async def test_claude_code_caps_cache_control_at_four():
    # A client (via ANTHROPIC_BASE_URL) already using its full 4-breakpoint budget;
    # prepending our cached identity must not push the request to 5 (Anthropic:
    # "A maximum of 4 blocks with cache_control may be provided. Found 5.").
    from voidswitch.services.providers.anthropic import CLAUDE_CODE_IDENTITY

    provider = Provider(name="cc", type="claude-code", base_url="https://api.anthropic.com")
    adapter = get_adapter(provider)

    body = {
        "system": [
            {
                "type": "text",
                "text": "Project rules: be terse.",
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "a", "cache_control": {"type": "ephemeral"}}],
            },
            {
                "role": "user",
                "content": [{"type": "text", "text": "b", "cache_control": {"type": "ephemeral"}}],
            },
            {
                "role": "user",
                "content": [{"type": "text", "text": "c", "cache_control": {"type": "ephemeral"}}],
            },
        ],
    }
    out = adapter.prepare_body(body)

    def count(blocks):
        return sum(1 for b in blocks if isinstance(b, dict) and "cache_control" in b)

    total = count(out["system"]) + sum(count(m["content"]) for m in out["messages"])
    assert total == 4  # capped, not 5
    # Identity still leads (required for OAuth), but it's the breakpoint we dropped.
    assert out["system"][0]["text"] == CLAUDE_CODE_IDENTITY
    assert "cache_control" not in out["system"][0]
    # The client's own four breakpoints are preserved.
    assert "cache_control" in out["system"][1]
    assert all("cache_control" in m["content"][0] for m in out["messages"])


async def test_claude_code_strips_opencode_identity_line():
    # Anti-detection: OpenCode's system prompt (prompt/codex.txt) leads with
    # "You are OpenCode, the best coding agent on the planet." — a competing agent
    # identity a real Claude Code request never carries. Only that one line is
    # excised; the rest of OpenCode's prompt (the bulk of the block) survives.
    from voidswitch.services.providers.anthropic import CLAUDE_CODE_IDENTITY

    provider = Provider(name="cc", type="claude-code", base_url="https://api.anthropic.com")
    adapter = get_adapter(provider)

    codex = (
        "You are OpenCode, the best coding agent on the planet.\n\n"
        "You are an interactive CLI tool that helps users.\n\n"
        "## Tool usage\n- Use Read to view files."
    )
    blocks = adapter.prepare_body({"system": [{"type": "text", "text": codex}], "messages": []})[
        "system"
    ]
    assert blocks[0]["text"] == CLAUDE_CODE_IDENTITY  # our identity leads
    rest = blocks[1]["text"]
    assert "You are OpenCode, the best coding agent on the planet." not in rest
    # The instructions are kept verbatim, and the leading blank line is cleaned up.
    assert rest.startswith("You are an interactive CLI tool that helps users.")
    assert "## Tool usage" in rest


async def test_claude_code_strips_opencode_identity_as_string():
    # The same when the inbound system prompt is a bare string, not a block list.
    from voidswitch.services.providers.anthropic import CLAUDE_CODE_IDENTITY

    provider = Provider(name="cc", type="claude-code", base_url="https://api.anthropic.com")
    out = get_adapter(provider).prepare_body(
        {
            "system": "You are OpenCode, the best coding agent on the planet.\n\nDo the thing.",
            "messages": [],
        }
    )
    assert [b["text"] for b in out["system"]] == [CLAUDE_CODE_IDENTITY, "Do the thing."]


async def test_claude_code_scrubs_all_opencode_fingerprints():
    # The identity line is only the first tell — OpenCode's anthropic.txt brands
    # itself again in the feedback/docs URLs, the "ask about OpenCode" guidance and
    # the skills footer. Every fingerprint must be gone (else Anthropic sees the
    # request isn't the real Claude Code CLI), not just line 1.
    from voidswitch.services.providers.anthropic import CLAUDE_CODE_IDENTITY

    provider = Provider(name="cc", type="claude-code", base_url="https://api.anthropic.com")
    adapter = get_adapter(provider)

    prompt = (
        "You are OpenCode, the best coding agent on the planet.\n\n"
        "You are an interactive CLI tool that helps users.\n\n"
        "If the user wants to give feedback, report the issue at\n"
        "  https://github.com/anomalyco/opencode\n\n"
        "When the user directly asks about OpenCode, use the WebFetch tool to "
        "answer from OpenCode docs at https://opencode.ai/docs\n\n"
        "It is best for the user if OpenCode honestly applies rigorous standards.\n\n"
        "<skill>customize-opencode: editing opencode.json or ~/.config/opencode/.</skill>"
    )
    blocks = adapter.prepare_body({"system": [{"type": "text", "text": prompt}], "messages": []})[
        "system"
    ]

    assert blocks[0]["text"] == CLAUDE_CODE_IDENTITY  # our identity leads
    joined = "\n".join(b["text"] for b in blocks)
    # No OpenCode tell of any kind survives — brand word, org, or docs/feedback URL.
    assert "opencode" not in joined.lower()
    assert "anomalyco" not in joined.lower()
    # Rewritten to the Claude Code equivalents, and the real instructions survive.
    assert "When the user directly asks about Claude Code" in joined
    assert "https://docs.claude.com/en/docs/claude-code" in joined
    assert "You are an interactive CLI tool that helps users." in joined


async def test_claude_code_scrubs_opencode_from_tools_and_model_id():
    # The fingerprints also live in the tool definitions (the OpenCode scratch path,
    # the customize-opencode skill text) and in the model id OpenCode echoes
    # ("voidswitch/…"). Every one must be scrubbed from the outbound body.
    provider = Provider(name="cc", type="claude-code", base_url="https://api.anthropic.com")
    adapter = get_adapter(provider)

    body = {
        "system": "You are powered by claude-opus-4-8. The exact model ID is voidswitch/claude-opus-4-8",
        "tools": [
            {
                "name": "bash",
                "description": "Use C:\\Users\\me\\AppData\\Local\\Temp\\opencode for scratch work.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "skill",
                "description": "## Available Skills\n- customize-opencode: editing opencode.json or ~/.config/opencode/.",
                "input_schema": {"type": "object", "properties": {}},
            },
        ],
        "messages": [],
    }
    out = adapter.prepare_body(body)

    blob = json.dumps(out)
    assert "opencode" not in blob.lower()  # nothing OpenCode survives anywhere
    assert "voidswitch/" not in blob  # gateway prefix stripped from the model id
    assert "The exact model ID is claude-opus-4-8" in out["system"][1]["text"]
    # Tool names are untouched so response routing still works.
    assert [t["name"] for t in out["tools"]] == ["bash", "skill"]


async def test_claude_code_drop_block_config_removes_whole_block():
    # With the provider opt-in, the entire identity-bearing block is dropped, so the
    # request carries only the injected Claude Code identity — none of the caller's
    # system prompt reaches Anthropic.
    from voidswitch.services.providers.anthropic import CLAUDE_CODE_IDENTITY

    provider = Provider(
        name="cc",
        type="claude-code",
        base_url="https://api.anthropic.com",
        drop_opencode_identity_block=True,
    )
    adapter = get_adapter(provider)

    codex = (
        "You are OpenCode, the best coding agent on the planet.\n\n"
        "You are an interactive CLI tool.\n\n## Tool usage\n- Use Read."
    )
    out = adapter.prepare_body({"system": [{"type": "text", "text": codex}], "messages": []})
    # Only our identity remains; the OpenCode block is gone entirely.
    assert [b["text"] for b in out["system"]] == [CLAUDE_CODE_IDENTITY]


async def test_claude_code_drop_block_defaults_off_scrubs_in_place():
    # Default (flag unset) keeps the scrub-in-place behaviour: the caller's prompt is
    # preserved with fingerprints rewritten, not discarded.
    from voidswitch.services.providers.anthropic import CLAUDE_CODE_IDENTITY

    provider = Provider(name="cc", type="claude-code", base_url="https://api.anthropic.com")
    out = get_adapter(provider).prepare_body(
        {
            "system": [
                {
                    "type": "text",
                    "text": "You are OpenCode, the best coding agent on the planet.\n\nKeep this.",
                }
            ],
            "messages": [],
        }
    )
    assert out["system"][0]["text"] == CLAUDE_CODE_IDENTITY
    assert out["system"][1]["text"] == "Keep this."


async def test_claude_code_caches_identity_when_budget_free():
    # With no client breakpoints, the identity prefix is cached (matches the CLI).
    provider = Provider(name="cc", type="claude-code", base_url="https://api.anthropic.com")
    out = get_adapter(provider).prepare_body({"system": "Be terse.", "messages": []})
    assert out["system"][0]["cache_control"] == {"type": "ephemeral"}


async def test_redact_headers_masks_credentials():
    from voidswitch.core.logging import redact_headers

    masked = redact_headers(
        {
            "Authorization": "Bearer sk-ant-oat01-supersecretvalue",
            "x-api-key": "sk-ant-api03-anothersecret",
            "anthropic-beta": "oauth-2025-04-20",
            "user-agent": "claude-cli/2.1.158 (external, cli)",
        }
    )
    # Bearer scheme kept, secret masked but last 4 chars retained for triage.
    assert masked["Authorization"] == "Bearer ***alue"
    assert "supersecret" not in masked["Authorization"]
    assert masked["x-api-key"].startswith("***") and "anothersecret" not in masked["x-api-key"]
    # Non-sensitive headers pass through untouched.
    assert masked["anthropic-beta"] == "oauth-2025-04-20"
    assert masked["user-agent"] == "claude-cli/2.1.158 (external, cli)"


# --------------------------------------------------------------------------- #
# Network
# --------------------------------------------------------------------------- #


async def test_build_transport_direct_and_proxy():
    direct = build_transport(Route())
    assert direct is not None
    http_proxy = build_transport(Route(proxy_url="http://127.0.0.1:8888"))
    assert http_proxy is not None
    local_ip = build_transport(Route(local_address="127.0.0.1"))
    assert local_ip is not None


async def test_route_is_direct():
    assert Route().is_direct
    assert not Route(proxy_url="http://x").is_direct


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #


async def test_add_missing_columns_migrates_legacy_table(tmp_path):
    # A database created before `drop_opencode_identity_block` existed must gain the
    # column on boot (create_all only makes missing *tables*), without being dropped.
    from voidswitch.core.database import Database

    url = f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}"
    database = Database(url)
    async with database.engine.begin() as conn:
        await conn.exec_driver_sql("CREATE TABLE providers (id INTEGER PRIMARY KEY, name VARCHAR)")
        await conn.exec_driver_sql("INSERT INTO providers (id, name) VALUES (1, 'old')")

    await database.create_all()

    async with database.engine.begin() as conn:
        cols = await conn.exec_driver_sql("PRAGMA table_info(providers)")
        names = {row[1] for row in cols}
        # The pre-existing row survives the migration.
        count = (await conn.exec_driver_sql("SELECT COUNT(*) FROM providers")).scalar()
    await database.dispose()

    assert "drop_opencode_identity_block" in names
    assert count == 1


async def test_database_init_and_settings_defaults(db):
    from sqlalchemy import select
    from voidswitch.models.db import Setting

    async with db.session() as session:
        rows = (await session.execute(select(Setting))).scalars().all()
        keys = {r.key for r in rows}
    assert set(DEFAULT_SETTINGS).issubset(keys)
