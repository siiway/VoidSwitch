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


async def _add_key_pool(db, provider_id: int, raw: str, pool: str) -> int:
    async with db.session() as session:
        key = ApiKey(
            provider_id=provider_id,
            key_ciphertext=encrypt_secret(raw, secret=get_settings().server.secret_key),
            key_hash=hash_token(raw),
            key_preview=raw[:4],
            status=KeyStatus.ACTIVE.value,
            pool=pool,
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


async def test_dispatch_model_route_targets_key_pool(db, seeded):
    from voidswitch.models.db import Provider

    # A "leaked"-pooled key, plus an alias route to the deepseek upstream on it.
    leaked_id = await _add_key_pool(db, seeded["provider_id"], "sk-leaked-1", "leaked")
    async with db.session() as session:
        prov = await session.get(Provider, seeded["provider_id"])
        prov.model_routes = [{"alias": "ds-lkd", "upstream": "deepseek-chat", "pool": "leaked"}]
        await session.flush()

    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(return_value=httpx.Response(200, json=OAI_RESPONSE))
        result = await dispatch(
            DispatchRequest(
                inbound_style=ApiStyle.OPENAI,
                model="ds-lkd",
                payload={"model": "ds-lkd", "messages": [{"role": "user", "content": "hi"}]},
                stream=False,
                token_id=seeded["token_id"],
            )
        )

    assert result.status_code == 200
    log = await _last_log(db)
    # Used the leaked-pool key, not the seeded untagged one.
    assert log is not None and log.key_id == leaked_id


async def _enable_debug(db, token_id: int) -> None:
    from voidswitch.models.db import VoidToken

    async with db.session() as session:
        tok = await session.get(VoidToken, token_id)
        tok.debug_enabled = True
        await session.flush()


async def test_dispatch_records_upstream_model_for_route(db, seeded):
    """A model route records both the inbound alias and the routed upstream id."""
    from voidswitch.models.db import Provider

    await _add_key_pool(db, seeded["provider_id"], "sk-leaked-1", "leaked")
    async with db.session() as session:
        prov = await session.get(Provider, seeded["provider_id"])
        prov.model_routes = [{"alias": "ds-lkd", "upstream": "deepseek-chat", "pool": "leaked"}]
        await session.flush()

    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(return_value=httpx.Response(200, json=OAI_RESPONSE))
        result = await dispatch(
            DispatchRequest(
                inbound_style=ApiStyle.OPENAI,
                model="ds-lkd",
                payload={"model": "ds-lkd", "messages": [{"role": "user", "content": "hi"}]},
                stream=False,
                token_id=seeded["token_id"],
            )
        )

    assert result.status_code == 200
    log = await _last_log(db)
    assert log is not None
    assert log.model == "ds-lkd"
    assert log.upstream_model == "deepseek-chat"


async def test_dispatch_upstream_500_exhaustion_is_traceable(db, seeded):
    """A total failover on repeated upstream 500s still attributes the failing
    row to the provider / route / upstream model it last tried (not "provider —").
    With a debug token the last upstream body + a full per-attempt trail are kept."""
    from voidswitch.models.db import Provider

    await _enable_debug(db, seeded["token_id"])
    async with db.session() as session:
        prov = await session.get(Provider, seeded["provider_id"])
        prov.model_routes = [{"alias": "codex-gpt-5.5", "upstream": "gpt-5.5", "pool": ""}]
        await session.flush()

    err = {"error": {"message": "internal boom", "type": "server_error"}}
    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(return_value=httpx.Response(500, json=err))
        result = await dispatch(
            DispatchRequest(
                inbound_style=ApiStyle.ANTHROPIC,
                model="codex-gpt-5.5",
                payload={
                    "model": "codex-gpt-5.5",
                    "messages": [{"role": "user", "content": "hi"}],
                },
                stream=False,
                token_id=seeded["token_id"],
                debug_enabled=True,
            )
        )

    assert result.status_code == 500
    log = await _last_log(db)
    assert log is not None
    # Traceability: the exhausted-everything row remembers what it last tried.
    assert log.provider_name == "deepseek"
    assert log.model == "codex-gpt-5.5"
    assert log.upstream_model == "gpt-5.5"
    assert log.upstream_style is not None
    assert log.key_id == seeded["key_id"]
    # Debug capture: the last upstream response + a per-attempt trail are present,
    # so an upstream 500 is diagnosable instead of a two-word message.
    assert log.debug is True
    assert log.status_code == 500
    assert log.resp_body == err
    assert log.debug_attempts and len(log.debug_attempts) >= 1
    first = log.debug_attempts[0]
    assert first["status_code"] == 500
    assert first["error_class"] == "server_error"
    assert first["url"] == DS_URL
    assert first["method"] == "POST"
    assert first["resp_body"] == err
    # The auth header is masked (only the credential is redacted).
    hdr = {k.lower(): v for k, v in (first["req_headers"] or {}).items()}
    assert "authorization" in hdr
    assert "sk-test-1" not in hdr["authorization"]
    assert hdr["authorization"].startswith("Bearer ***")


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


async def test_dispatch_rate_limit_recovery(db, seeded):
    """A rate-limited key is retried after recovery interval and reset to ACTIVE on success."""
    import datetime as dt

    from voidswitch.models.db import ApiKey
    from voidswitch.services import settings_store

    # Set recovery interval to 180 seconds (3 minutes)
    async with db.session() as session:
        await settings_store.update(session, {"rate_limit_recovery_seconds": 180})

    # Mark the key as rate-limited, disabled 4 minutes ago (past recovery)
    async with db.session() as session:
        key = await session.get(ApiKey, seeded["key_id"])
        key.status = KeyStatus.RATE_LIMITED.value
        key.disabled_since = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=4)
        await session.flush()

    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(return_value=httpx.Response(200, json=OAI_RESPONSE))
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
    # Key should be reset to ACTIVE after successful request
    async with db.session() as session:
        key = await session.get(ApiKey, seeded["key_id"])
    assert key.status == KeyStatus.ACTIVE.value
    assert key.disabled_since is None


async def test_dispatch_429_sets_retry_after_cooldown(db, seeded):
    """A 429 with Retry-After parks the key out of the pool for that long, and a
    second active key serves the request (rate-limited key ranked last)."""
    import datetime as dt

    from voidswitch.models.db import ApiKey
    from voidswitch.services.selector import reset_selection_state

    first = seeded["key_id"]
    second = await _add_key(db, seeded["provider_id"], "sk-second")
    reset_selection_state()

    with respx.mock(assert_all_called=False) as mock:
        # First key → 429 with a 2-minute Retry-After; second key → success.
        mock.post(DS_URL).mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "120"}, json={"error": "slow down"}),
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
    async with db.session() as session:
        k1 = await session.get(ApiKey, first)
        k2 = await session.get(ApiKey, second)
    # First key parked ~120s out (give scheduling slack); second key served + active.
    assert k1.status == KeyStatus.RATE_LIMITED.value
    assert k1.rate_limit_until is not None
    until = k1.rate_limit_until
    if until.tzinfo is None:
        until = until.replace(tzinfo=dt.UTC)
    remaining = (until - dt.datetime.now(dt.UTC)).total_seconds()
    assert 110 <= remaining <= 125
    assert k2.status == KeyStatus.ACTIVE.value
    assert k2.total_requests == 1


async def test_dispatch_429_provider_cooldown_when_no_header(db, seeded):
    """Without a Retry-After header, the provider's cooldown is used (over global)."""
    import datetime as dt

    from voidswitch.models.db import ApiKey, Provider
    from voidswitch.services import settings_store

    async with db.session() as session:
        await settings_store.update(session, {"rate_limit_recovery_seconds": 180})
        provider = await session.get(Provider, seeded["provider_id"])
        provider.rate_limit_cooldown_seconds = 45  # provider overrides the 180s global
        await session.flush()

    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(return_value=httpx.Response(429, json={"error": "slow down"}))
        await dispatch(
            DispatchRequest(
                inbound_style=ApiStyle.OPENAI,
                model="deepseek-chat",
                payload={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
                stream=False,
                token_id=seeded["token_id"],
            )
        )

    async with db.session() as session:
        k = await session.get(ApiKey, seeded["key_id"])
    assert k.status == KeyStatus.RATE_LIMITED.value
    until = k.rate_limit_until
    if until.tzinfo is None:
        until = until.replace(tzinfo=dt.UTC)
    remaining = (until - dt.datetime.now(dt.UTC)).total_seconds()
    assert 38 <= remaining <= 50  # ~45s from the provider cooldown, not 180s global


async def test_dispatch_rate_limit_no_recovery_within_interval(db, seeded):
    """A rate-limited key is NOT retried if recovery interval hasn't elapsed."""
    import datetime as dt

    from voidswitch.models.db import ApiKey
    from voidswitch.services import settings_store

    # Set recovery interval to 180 seconds (3 minutes)
    async with db.session() as session:
        await settings_store.update(session, {"rate_limit_recovery_seconds": 180})

    # Mark the key as rate-limited, disabled 1 minute ago (within recovery window)
    async with db.session() as session:
        key = await session.get(ApiKey, seeded["key_id"])
        key.status = KeyStatus.RATE_LIMITED.value
        key.disabled_since = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
        await session.flush()

    result = await dispatch(
        DispatchRequest(
            inbound_style=ApiStyle.OPENAI,
            model="deepseek-chat",
            payload={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
            stream=False,
            token_id=seeded["token_id"],
        )
    )

    # No keys available → 502
    assert result.status_code == 502
