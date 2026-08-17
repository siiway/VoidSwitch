"""Integration tests for the failover dispatcher (upstreams mocked with respx)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from sqlalchemy import select
from voidswitch.constants import ApiStyle, KeyStatus, NodeStatus
from voidswitch.core.config import get_settings
from voidswitch.core.security import encrypt_secret, hash_token
from voidswitch.models.db import ApiKey, Node
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


async def _add_node(db, url: str) -> int:
    """Add an active HTTP node to the default node group (provider egress)."""
    from voidswitch.models.db import NodeGroupMember
    from voidswitch.services import routing

    async with db.session() as session:
        node = Node(url=url, type="http", status=NodeStatus.ACTIVE.value)
        session.add(node)
        await session.flush()
        default = await routing.default_group(session)
        if default is not None:
            session.add(NodeGroupMember(group_id=default.id, node_id=node.id))
        await session.flush()
        return node.id


async def _expose_route(db, model_id: str, provider_id: int, upstream: str, *, pool: str = ""):
    """Create an exposed model with a 1:1 route to a provider (and optional pool)."""
    from voidswitch.models.db import ExposedModel, Route, RouteLayer, RoutePoolEntry

    async with db.session() as session:
        entry = ExposedModel(model_id=model_id)
        session.add(entry)
        await session.flush()
        route = Route(exposed_model_id=entry.id)
        session.add(route)
        await session.flush()
        layer = RouteLayer(route_id=route.id, position=0, max_attempts=1)
        session.add(layer)
        await session.flush()
        session.add(
            RoutePoolEntry(
                layer_id=layer.id,
                provider_id=provider_id,
                upstream_model=upstream,
                key_pool=pool,
            )
        )
        await session.flush()


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
    await _add_node(db, "http://127.0.0.1:38080")
    await _add_node(db, "http://127.0.0.1:38081")
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
        nodes = (await session.execute(select(Node))).scalars().all()
    assert any(n.failed_count >= 1 for n in nodes)


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
    # The provider's default node group routes egress. Two nodes exist; only the
    # first is active, so dispatch must pin to it (the "assigned" node), never the
    # disabled second one.
    p1 = await _add_node(db, "http://127.0.0.1:38080")
    p2 = await _add_node(db, "http://127.0.0.1:38081")
    async with db.session() as session:
        node = await session.get(Node, p2)
        node.status = NodeStatus.DISABLED.value
        await session.flush()

    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(return_value=httpx.Response(200, json=OAI_RESPONSE))
        result = await _dispatch_hi(seeded)

    assert result.status_code == 200
    log = await _last_log(db)
    assert log is not None and log.proxy_id == p1  # used the active node, not p2


async def test_dispatch_direct_proxy_mode_uses_no_proxy(db, seeded):
    # Even with a node in the default group, a provider assigned to an EMPTY node
    # group routes direct (an empty group = direct).
    await _add_node(db, "http://127.0.0.1:38080")
    from voidswitch.models.db import NodeGroup, Provider

    async with db.session() as session:
        empty = NodeGroup(name="Empty")
        session.add(empty)
        await session.flush()
        provider = await session.get(Provider, seeded["provider_id"])
        provider.node_group_id = empty.id
        await session.flush()

    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(return_value=httpx.Response(200, json=OAI_RESPONSE))
        result = await _dispatch_hi(seeded)

    assert result.status_code == 200
    log = await _last_log(db)
    assert log is not None and log.proxy_id is None  # went direct


# test_dispatch_selected_with_all_assigned_down_skips_provider is obsolete: under
# the routing model an empty node group (all nodes down) degrades to DIRECT rather
# than skipping the provider, so there is no "no usable route → skip → 502" path.


async def test_dispatch_model_route_targets_key_pool(db, seeded):
    # A "leaked"-pooled key, plus an exposed model routed to the deepseek upstream
    # through exactly that key pool.
    leaked_id = await _add_key_pool(db, seeded["provider_id"], "sk-leaked-1", "leaked")
    await _expose_route(
        db, "ds-lkd", seeded["provider_id"], "deepseek-chat", pool="leaked"
    )

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
    await _expose_route(db, "ds-lkd", seeded["provider_id"], "deepseek-chat")

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
    await _enable_debug(db, seeded["token_id"])
    await _expose_route(db, "codex-gpt-5.5", seeded["provider_id"], "gpt-5.5")

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


async def test_dispatch_error_captures_response_for_non_debug_token(db, seeded):
    """Even without a debug token, an upstream error (5xx/4xx) force-records the
    response headers + body (owner-only debug info) — but NOT the request
    headers/body or the per-attempt trail."""
    err = {"error": {"message": "internal boom", "type": "server_error"}}
    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(return_value=httpx.Response(500, json=err))
        result = await dispatch(
            DispatchRequest(
                inbound_style=ApiStyle.OPENAI,
                model="deepseek-chat",
                payload={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
                stream=False,
                token_id=seeded["token_id"],
                debug_enabled=False,
            )
        )
    assert result.status_code == 500
    log = await _last_log(db)
    assert log is not None
    # Treated as debug info: flagged debug so it's owner-only + pruned by the
    # debug retention window.
    assert log.debug is True
    # Response captured…
    assert log.resp_body == err
    assert log.resp_headers is not None
    # …but the request headers/body and the per-attempt trail are NOT.
    assert log.req_headers is None
    assert log.req_body is None
    assert log.debug_attempts is None


async def test_dispatch_success_non_debug_captures_nothing(db, seeded):
    """A successful non-debug request stays a plain summary row (no debug flag)."""
    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(return_value=httpx.Response(200, json=OAI_RESPONSE))
        result = await _dispatch_hi(seeded)
    assert result.status_code == 200
    log = await _last_log(db)
    assert log is not None
    assert log.debug is False
    assert log.resp_body is None
    assert log.resp_headers is None


async def test_dispatch_no_provider_returns_404(db, seeded):
    # A model id that is not exposed (e.g. a raw upstream id) is rejected.
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


RESP_URL = "https://api.openai.com/v1/responses"

RESPONSES_BODY = {
    "id": "resp_1",
    "object": "response",
    "model": "gpt-5",
    "status": "completed",
    "output": [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "hello"}],
        }
    ],
    "usage": {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7},
}


async def _add_responses_provider(db) -> int:
    from voidswitch.models.db import Provider

    async with db.session() as session:
        provider = Provider(
            name="oair",
            type="openai-resp",
            base_url="https://api.openai.com/v1",
            models=["gpt-5"],
            priority=1,
        )
        session.add(provider)
        await session.flush()
        pid = provider.id
    await _add_key(db, pid, "sk-resp-1")
    await _expose_route(db, "gpt-5", pid, "gpt-5")
    return pid


async def test_dispatch_openai_inbound_to_responses_upstream(db, seeded):
    """OpenAI-chat inbound is translated to a Responses upstream and the Responses
    reply is translated back into chat-completion shape for the client."""
    await _add_responses_provider(db)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(RESP_URL).mock(return_value=httpx.Response(200, json=RESPONSES_BODY))
        result = await dispatch(
            DispatchRequest(
                inbound_style=ApiStyle.OPENAI,
                model="gpt-5",
                payload={"model": "gpt-5", "messages": [{"role": "user", "content": "hi"}]},
                stream=False,
                token_id=seeded["token_id"],
            )
        )
    assert result.status_code == 200
    assert result.upstream_style == ApiStyle.OPENAI_RESPONSES.value
    # The upstream was called with a Responses-shaped body (input, not messages).
    sent = json.loads(route.calls.last.request.content)
    assert "input" in sent and "messages" not in sent
    # The client gets a chat.completion back.
    body = json.loads(result.content or b"{}")
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "hello"
    assert body["usage"]["total_tokens"] == 7


async def test_dispatch_responses_inbound_to_openai_upstream(db, seeded):
    """A /v1/responses (Responses) inbound request routes to a chat-completions
    upstream and the reply is translated back into Responses shape."""
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(DS_URL).mock(return_value=httpx.Response(200, json=OAI_RESPONSE))
        result = await dispatch(
            DispatchRequest(
                inbound_style=ApiStyle.OPENAI_RESPONSES,
                model="deepseek-chat",
                payload={"model": "deepseek-chat", "input": "hi"},
                stream=False,
                token_id=seeded["token_id"],
            )
        )
    assert result.status_code == 200
    # Upstream saw chat-completions shape (messages, not input).
    sent = json.loads(route.calls.last.request.content)
    assert "messages" in sent and "input" not in sent
    # Client gets a Responses object back.
    body = json.loads(result.content or b"{}")
    assert body["object"] == "response"
    assert body["output_text"] == "hello"
    assert body["usage"]["total_tokens"] == 7


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


async def _set_zero_token(db, provider_id, enabled=True):
    from voidswitch.models.db import Provider

    async with db.session() as session:
        provider = await session.get(Provider, provider_id)
        provider.retry_on_zero_token = enabled
        await session.flush()


EMPTY_RESPONSE = {
    "id": "chatcmpl-empty",
    "object": "chat.completion",
    "model": "deepseek-chat",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": ""},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
}


async def test_dispatch_zero_token_retry_non_stream(db, seeded):
    """A 200 OK + 0 tokens response is treated as a transient fault: the
    dispatcher retries on the next key instead of returning the empty reply."""
    await _set_zero_token(db, seeded["provider_id"], True)
    await _add_key(db, seeded["provider_id"], "sk-test-2")

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(DS_URL).mock(
            side_effect=[
                httpx.Response(200, json=EMPTY_RESPONSE),
                httpx.Response(200, json=OAI_RESPONSE),
            ]
        )
        result = await _dispatch_hi(seeded)

    assert result.status_code == 200
    assert result.attempts == 2
    assert len(route.calls) == 2
    assert b"hello" in (result.content or b"")


async def test_dispatch_zero_token_exhaustion_is_an_error(db, seeded):
    """Every attempt degenerate → the request fails as upstream_unavailable; the
    empty 200 reply is never delivered to the client."""
    await _set_zero_token(db, seeded["provider_id"], True)

    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(return_value=httpx.Response(200, json=EMPTY_RESPONSE))
        result = await _dispatch_hi(seeded)

    assert result.status_code == 502
    assert result.error == "upstream_unavailable"
    assert (result.content or b"").startswith(b"{")
    assert b"0 tokens" in (result.content or b"")


async def test_dispatch_streaming_zero_token_retries_in_flight(db, seeded):
    """A streamed degenerate reply (ends with no content) is detected before
    delivery and retried on the next key — the client gets the good stream."""
    await _set_zero_token(db, seeded["provider_id"], True)
    await _add_key(db, seeded["provider_id"], "sk-test-2")

    empty_sse = (
        b'data: {"choices":[{"index":0,"delta":{"content":""}}]}\n\n'
        b"data: [DONE]\n\n"
    )

    def _req():
        return DispatchRequest(
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

    sse = (
        b'data: {"choices":[{"index":0,"delta":{"content":"Hi"}}]}\n\n'
        b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],'
        b'"usage":{"prompt_tokens":1,"completion_tokens":1}}\n\n'
        b"data: [DONE]\n\n"
    )
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(DS_URL).mock(
            side_effect=[
                httpx.Response(200, content=empty_sse, headers={"content-type": "text/event-stream"}),
                httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"}),
            ]
        )
        result = await dispatch(_req())
        assert result.stream is not None
        collected = b""
        async for piece in result.stream:
            collected += piece

    assert result.status_code == 200
    assert len(route.calls) == 2  # degenerate first attempt → retried
    assert b"Hi" in collected
    # The final row is a clean success.
    log = await _last_log(db)
    assert log is not None and log.error is None


async def test_dispatch_streaming_zero_token_exhaustion_is_error(db, seeded):
    """Every streamed attempt degenerate → the request fails; no empty stream is
    ever delivered to the client."""
    await _set_zero_token(db, seeded["provider_id"], True)

    empty_sse = (
        b'data: {"choices":[{"index":0,"delta":{"content":""}}]}\n\n'
        b"data: [DONE]\n\n"
    )

    def _req():
        return DispatchRequest(
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

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(DS_URL).mock(
            return_value=httpx.Response(
                200, content=empty_sse, headers={"content-type": "text/event-stream"}
            )
        )
        result = await dispatch(_req())

    assert result.status_code == 502
    assert result.error == "upstream_unavailable"
    assert len(route.calls) >= 1




async def test_build_stream_response_timeout_marks_terminated(db, seeded):
    """A stream past the response timeout is force-cut: connection closed and
    the log row marked ``terminated`` (已切断)."""
    import asyncio
    import time

    from voidswitch.models.db import RequestLog, VoidToken
    from voidswitch.services import settings_store
    from voidswitch.services.dispatcher import _build_stream

    async with db.session() as session:
        await settings_store.update(session, {"response_timeout_seconds": 1})

    async with db.session() as session:
        token = VoidToken(user_id=seeded["user_id"], name="t", token_hash="tokhash")
        session.add(token)
        await session.flush()
        row = RequestLog(token_id=token.id, user_sub=seeded["user_sub"], stream=True, req_status="pending")
        session.add(row)
        await session.flush()
        log_id = row.id

    class FakeResponse:
        def __init__(self):
            self.closed = False

        async def aiter_bytes(self):
            yield b'data: {"choices":[{"index":0,"delta":{"content":"hi"}}]}\n\n'
            await asyncio.sleep(10)
            yield b"data: [DONE]\n\n"

        async def aclose(self):
            self.closed = True

    resp = FakeResponse()
    gen = _build_stream(
        response=resp,  # ty: ignore[invalid-argument-type]  # FakeResponse mocks httpx.Response
        inbound=ApiStyle.OPENAI,
        upstream=ApiStyle.OPENAI,
        model="deepseek-chat",
        log_id=log_id,
        token_id=token.id,
        response_timeout=1,
    )
    started = time.monotonic()
    collected = b""
    async for piece in gen:
        collected += piece
    elapsed = time.monotonic() - started
    assert elapsed < 5
    assert resp.closed
    assert b"hi" in collected

    async with db.session() as session:
        row = await session.get(RequestLog, log_id)
        assert row.req_status == "terminated"
        assert row.finished_at is not None
        assert "response timeout" in (row.error or "")


async def test_build_stream_first_token_is_ttft_not_ttfb(db, seeded):
    """TTFT is measured from the upstream request start to the first real
    content token — not to the first raw byte (which only reflects the
    upstream's connection/header latency)."""
    import asyncio
    import time

    from voidswitch.models.db import RequestLog, VoidToken
    from voidswitch.services.dispatcher import _build_stream

    async with db.session() as session:
        token = VoidToken(user_id=seeded["user_id"], name="t", token_hash="tokhash")
        session.add(token)
        await session.flush()
        row = RequestLog(token_id=token.id, user_sub=seeded["user_sub"], stream=True, req_status="pending")
        session.add(row)
        await session.flush()
        log_id = row.id

    class FakeResponse:
        def __init__(self):
            self.closed = False

        async def aiter_bytes(self):
            # Simulate the upstream latency before any SSE frame arrives:
            # several seconds pass before the first (content-less) frame, and
            # more still before the first content-bearing token.
            await asyncio.sleep(0.05)
            yield b'data: {"choices":[{"index":0,"delta":{"role":"assistant"}}]}\n\n'
            await asyncio.sleep(0.05)
            yield b'data: {"choices":[{"index":0,"delta":{"content":""}}]}\n\n'
            await asyncio.sleep(0.05)
            yield b'data: {"choices":[{"index":0,"delta":{"content":"Hi"}}]}\n\n'
            yield b"data: [DONE]\n\n"

        async def aclose(self):
            self.closed = True

    resp = FakeResponse()
    # ``start_mono`` is the moment the upstream request was initiated — e.g.
    # 100ms before the generator starts being consumed.
    start_mono = time.monotonic() - 0.1
    gen = _build_stream(
        response=resp,  # ty: ignore[invalid-argument-type]
        inbound=ApiStyle.OPENAI,
        upstream=ApiStyle.OPENAI,
        model="deepseek-chat",
        log_id=log_id,
        token_id=token.id,
        start_mono=start_mono,
    )
    async for _ in gen:
        pass

    async with db.session() as session:
        row = await session.get(RequestLog, log_id)
        # ~150ms (two content-less frames at 50ms each) + 100ms (pre-start
        # offset): TTFT must reflect the real content token, NOT the first byte
        # (which would be ~150ms earlier). And it must never include the full
        # stream duration.
        assert row.first_token_ms is not None
        assert row.first_token_ms >= 190.0
        assert row.first_token_ms < 300.0
        assert row.req_status == "completed"


async def test_reconcile_pending_logs_marks_orphaned_terminated(db):
    import datetime as dt

    from voidswitch.models.db import RequestLog
    from voidswitch.services import settings_store
    from voidswitch.services.dispatcher import reconcile_pending_request_logs

    async with db.session() as session:
        await settings_store.update(session, {"response_timeout_seconds": 3600})
    async with db.session() as session:
        old = RequestLog(
            req_status="pending",
            started_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=2),
        )
        recent = RequestLog(
            req_status="pending",
            started_at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5),
        )
        session.add_all([old, recent])
        await session.flush()

    count = await reconcile_pending_request_logs()
    assert count == 1

    async with db.session() as session:
        rows = (await session.execute(select(RequestLog))).scalars().all()
    statuses = {r.req_status for r in rows}
    assert "terminated" in statuses


async def test_dispatch_non_dict_json_body_passthrough(db, seeded):
    """A 2xx upstream body that parses as JSON but is not an object (e.g. a bare
    list) must be relayed verbatim instead of crashing the cross-style
    translator."""
    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(return_value=httpx.Response(200, json=["a", "b"]))
        result = await _dispatch_hi(seeded)

    assert result.status_code == 200
    assert json.loads(result.content or b"{}") == ["a", "b"]


async def test_dispatch_non_dict_json_anthropic_body_passthrough(db, seeded):
    """Same passthrough holds when the inbound style differs (Anthropic) — the
    translator would crash on a non-dict upstream reply."""
    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(return_value=httpx.Response(200, content=b"42"))
        result = await dispatch(
            DispatchRequest(
                inbound_style=ApiStyle.ANTHROPIC,
                model="deepseek-chat",
                payload={
                    "model": "deepseek-chat",
                    "max_tokens": 8,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                stream=False,
                token_id=seeded["token_id"],
            )
        )
    assert result.status_code == 200
    assert (result.content or b"").strip() == b"42"
