"""Integration tests for the failover dispatcher (upstreams mocked with respx)."""

from __future__ import annotations

import httpx
import pytest
import respx
from sqlalchemy import select
from voidswitch.constants import ApiStyle, KeyStatus, ProxyStatus
from voidswitch.core.config import get_settings
from voidswitch.core.security import encrypt_secret, hash_token
from voidswitch.models.db import ApiKey, Proxy
from voidswitch.services.dispatcher import DispatchRequest, dispatch

pytestmark = pytest.mark.asyncio

DS_URL = "https://api.deepseek.com/chat/completions"

OAI_RESPONSE = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "model": "deepseek-chat",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
}


async def _add_key(db, provider_id: int, raw: str) -> int:
    async with db.session() as session:
        key = ApiKey(
            provider_id=provider_id,
            key_ciphertext=encrypt_secret(raw, secret=get_settings().server.secret_key),
            key_hash=hash_token(raw),
            key_preview=raw[:4],
            status=KeyStatus.ACTIVE.value,
        )
        session.add(key)
        await session.flush()
        return key.id


async def _add_proxy(db, url: str) -> int:
    async with db.session() as session:
        proxy = Proxy(url=url, status=ProxyStatus.ACTIVE.value)
        session.add(proxy)
        await session.flush()
        return proxy.id


async def test_dispatch_success_non_stream(db, seeded):
    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(return_value=httpx.Response(200, json=OAI_RESPONSE))
        result = await dispatch(
            DispatchRequest(
                inbound_style=ApiStyle.OPENAI,
                model="deepseek-chat",
                payload={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
                stream=False,
                token_id=seeded["token_id"],
                user_sub=seeded["user_sub"],
            )
        )
    assert result.status_code == 200
    assert b"hello" in (result.content or b"")
    assert result.attempts == 1


async def test_dispatch_key_failover_on_401(db, seeded):
    """A 401 invalid-key disables the key and retries with a fresh one."""
    await _add_key(db, seeded["provider_id"], "sk-test-2")
    invalid = {"error": {"message": "key invalid", "type": "authentication_error"}}
    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(
            side_effect=[
                httpx.Response(401, json=invalid),
                httpx.Response(200, json=OAI_RESPONSE),
            ]
        )
        result = await dispatch(
            DispatchRequest(
                inbound_style=ApiStyle.OPENAI,
                model="deepseek-chat",
                payload={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
                stream=False,
                token_id=seeded["token_id"],
            )
        )
    assert result.status_code == 200
    assert result.attempts == 2
    async with db.session() as session:
        disabled = (
            (await session.execute(select(ApiKey).where(ApiKey.status == KeyStatus.INVALID.value)))
            .scalars()
            .all()
        )
    assert len(disabled) == 1


async def test_dispatch_insufficient_balance_disables_key(db, seeded):
    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(
            return_value=httpx.Response(402, json={"error": {"message": "no balance"}})
        )
        result = await dispatch(
            DispatchRequest(
                inbound_style=ApiStyle.OPENAI,
                model="deepseek-chat",
                payload={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
                stream=False,
                token_id=seeded["token_id"],
            )
        )
    assert result.status_code >= 400
    async with db.session() as session:
        key = await session.get(ApiKey, seeded["key_id"])
    assert key.status == KeyStatus.INSUFFICIENT_BALANCE.value


async def test_dispatch_proxy_failover_on_network_error(db, seeded):
    await _add_proxy(db, "http://127.0.0.1:38080")
    await _add_proxy(db, "http://127.0.0.1:38081")
    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(
            side_effect=[
                httpx.ConnectError("boom"),
                httpx.Response(200, json=OAI_RESPONSE),
            ]
        )
        result = await dispatch(
            DispatchRequest(
                inbound_style=ApiStyle.OPENAI,
                model="deepseek-chat",
                payload={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
                stream=False,
                token_id=seeded["token_id"],
            )
        )
    assert result.status_code == 200
    assert result.attempts == 2
    async with db.session() as session:
        proxies = (await session.execute(select(Proxy))).scalars().all()
    assert any(p.failed_count >= 1 for p in proxies)


async def _set_provider_proxy(db, provider_id, mode, proxy_ids):
    from voidswitch.models.db import Provider

    async with db.session() as session:
        provider = await session.get(Provider, provider_id)
        provider.proxy_mode = mode
        provider.proxy_ids = proxy_ids
        await session.flush()


async def _last_log(db):
    from voidswitch.models.db import RequestLog

    async with db.session() as session:
        return (
            (await session.execute(select(RequestLog).order_by(RequestLog.id.desc())))
            .scalars()
            .first()
        )


async def _dispatch_hi(seeded):
    return await dispatch(
        DispatchRequest(
            inbound_style=ApiStyle.OPENAI,
            model="deepseek-chat",
            payload={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
            stream=False,
            token_id=seeded["token_id"],
        )
    )


async def test_dispatch_selected_proxy_mode_pins_to_assigned_proxy(db, seeded):
    await _add_proxy(db, "http://127.0.0.1:38080")
    p2 = await _add_proxy(db, "http://127.0.0.1:38081")
    await _set_provider_proxy(db, seeded["provider_id"], "selected", [p2])

    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(return_value=httpx.Response(200, json=OAI_RESPONSE))
        result = await _dispatch_hi(seeded)

    assert result.status_code == 200
    log = await _last_log(db)
    assert log is not None and log.proxy_id == p2  # used the assigned proxy, not p1


async def test_dispatch_direct_proxy_mode_uses_no_proxy(db, seeded):
    await _add_proxy(db, "http://127.0.0.1:38080")  # exists but must be ignored
    await _set_provider_proxy(db, seeded["provider_id"], "direct", [])

    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(return_value=httpx.Response(200, json=OAI_RESPONSE))
        result = await _dispatch_hi(seeded)

    assert result.status_code == 200
    log = await _last_log(db)
    assert log is not None and log.proxy_id is None  # went direct


async def test_dispatch_selected_with_all_assigned_down_skips_provider(db, seeded):
    # Assign a proxy, then disable it: no active assigned proxy remains, and a
    # "selected" provider must NOT fall back to direct — it is skipped → 502.
    pid = await _add_proxy(db, "http://127.0.0.1:38080")
    async with db.session() as session:
        proxy = await session.get(Proxy, pid)
        proxy.status = ProxyStatus.DISABLED.value
        await session.flush()
    await _set_provider_proxy(db, seeded["provider_id"], "selected", [pid])

    result = await _dispatch_hi(seeded)
    assert result.status_code == 502
    assert result.attempts == 0  # never attempted — no route available


async def test_dispatch_no_provider_returns_404(db, seeded):
    # Narrow the seeded provider so it no longer matches via the "*" wildcard.
    from voidswitch.models.db import Provider

    async with db.session() as session:
        provider = await session.get(Provider, seeded["provider_id"])
        provider.models = ["deepseek-chat"]
        await session.flush()

    result = await dispatch(
        DispatchRequest(
            inbound_style=ApiStyle.OPENAI,
            model="no-such-model-xyz",
            payload={"model": "no-such-model-xyz", "messages": []},
            stream=False,
            token_id=seeded["token_id"],
        )
    )
    assert result.status_code == 404


async def test_dispatch_translates_anthropic_inbound_to_openai_upstream(db, seeded):
    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(return_value=httpx.Response(200, json=OAI_RESPONSE))
        result = await dispatch(
            DispatchRequest(
                inbound_style=ApiStyle.ANTHROPIC,
                model="deepseek-chat",
                payload={
                    "model": "deepseek-chat",
                    "max_tokens": 64,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                stream=False,
                token_id=seeded["token_id"],
            )
        )
    assert result.status_code == 200
    # Response must be in Anthropic shape for an Anthropic client.
    assert b'"type": "message"' in (result.content or b"")


async def test_dispatch_streaming_passthrough(db, seeded):
    sse = (
        b'data: {"choices":[{"index":0,"delta":{"content":"Hi"}}]}\n\n'
        b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],'
        b'"usage":{"prompt_tokens":1,"completion_tokens":1}}\n\n'
        b"data: [DONE]\n\n"
    )
    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(
            return_value=httpx.Response(
                200, content=sse, headers={"content-type": "text/event-stream"}
            )
        )
        result = await dispatch(
            DispatchRequest(
                inbound_style=ApiStyle.OPENAI,
                model="deepseek-chat",
                payload={
                    "model": "deepseek-chat",
                    "stream": True,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                stream=True,
                token_id=seeded["token_id"],
            )
        )
        assert result.is_stream
        assert result.stream is not None
        collected = b""
        async for piece in result.stream:
            collected += piece
    assert b"Hi" in collected
    assert b"[DONE]" in collected
