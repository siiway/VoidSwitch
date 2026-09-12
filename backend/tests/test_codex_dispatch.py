"""Codex OAuth upstream contract: ``store=false``/``stream=true`` enforcement and
``stream=false -> stream=true`` protocol conversion (SSE aggregation).

The ChatGPT Codex backend (``/backend-api/codex/responses``) only speaks SSE and
rejects ``store: true`` with ``400 {"detail": "Store must be set to false"}``.
These tests pin the wire payload dispatched upstream and the client-visible
behaviour in both streaming modes.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from voidswitch.constants import ApiStyle
from voidswitch.models.db import Provider
from voidswitch.services.dispatcher import DispatchRequest, _prepare_body, dispatch
from voidswitch.services.providers.registry import get_adapter

pytestmark = pytest.mark.asyncio

CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"

_SSE_HEADERS = {"content-type": "text/event-stream"}

# A realistic Codex Responses SSE stream: created → item/part lifecycle → deltas
# → done → completed. The terminal response.completed carries the full object.
CODEX_SSE = (
    b"event: response.created\n"
    b'data: {"type":"response.created","sequence_number":0,'
    b'"response":{"id":"resp_9","object":"response","created_at":1700000000,'
    b'"model":"gpt-5.6-sol","status":"in_progress","output":[]}}\n\n'
    b"event: response.in_progress\n"
    b'data: {"type":"response.in_progress","sequence_number":1,'
    b'"response":{"id":"resp_9","status":"in_progress"}}\n\n'
    b"event: response.output_item.added\n"
    b'data: {"type":"response.output_item.added","sequence_number":2,"output_index":0,'
    b'"item":{"id":"msg_1","type":"message","status":"in_progress","role":"assistant","content":[]}}\n\n'
    b"event: response.content_part.added\n"
    b'data: {"type":"response.content_part.added","sequence_number":3,"item_id":"msg_1",'
    b'"output_index":0,"content_index":0,"part":{"type":"output_text","text":"","annotations":[]}}\n\n'
    b"event: response.output_text.delta\n"
    b'data: {"type":"response.output_text.delta","sequence_number":4,"item_id":"msg_1",'
    b'"output_index":0,"content_index":0,"delta":"Hel"}\n\n'
    b"event: response.output_text.delta\n"
    b'data: {"type":"response.output_text.delta","sequence_number":5,"item_id":"msg_1",'
    b'"output_index":0,"content_index":0,"delta":"lo"}\n\n'
    b"event: response.output_text.done\n"
    b'data: {"type":"response.output_text.done","sequence_number":6,"item_id":"msg_1",'
    b'"output_index":0,"content_index":0,"text":"Hello"}\n\n'
    b"event: response.output_item.done\n"
    b'data: {"type":"response.output_item.done","sequence_number":7,"output_index":0,'
    b'"item":{"id":"msg_1","type":"message","status":"completed","role":"assistant",'
    b'"content":[{"type":"output_text","text":"Hello","annotations":[]}]}}\n\n'
    b"event: response.completed\n"
    b'data: {"type":"response.completed","sequence_number":8,'
    b'"response":{"id":"resp_9","object":"response","created_at":1700000000,'
    b'"model":"gpt-5.6-sol","status":"completed",'
    b'"output":[{"id":"msg_1","type":"message","status":"completed","role":"assistant",'
    b'"content":[{"type":"output_text","text":"Hello","annotations":[]}]}],'
    b'"usage":{"input_tokens":5,"output_tokens":2,"total_tokens":7}}}\n\n'
)


async def _add_codex_provider(db) -> int:
    """A Codex provider with one static-token key and an exposed model route."""
    from tests.test_dispatcher import _add_key, _expose_route

    async with db.session() as session:
        provider = Provider(name="Codex", slug="codex", type="codex", base_url="", models=["*"])
        session.add(provider)
        await session.flush()
        pid = provider.id
    await _add_key(db, pid, "static-codex-token")
    await _expose_route(db, "codex-gpt", pid, "gpt-5.6-sol")
    return pid


def _codex_req(*, stream: bool, **payload) -> DispatchRequest:
    return DispatchRequest(
        inbound_style=ApiStyle.OPENAI_RESPONSES,
        model="codex-gpt",
        payload={"model": "codex-gpt", "input": "hi", **payload},
        stream=stream,
    )


async def test_codex_stream_true_passes_through_sse(db, seeded):
    """Client stream=true → upstream stream=true+store=false, downstream SSE."""
    await _add_codex_provider(db)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(CODEX_URL).mock(
            return_value=httpx.Response(200, content=CODEX_SSE, headers=_SSE_HEADERS)
        )
        result = await dispatch(_codex_req(stream=True))

    sent = json.loads(route.calls.last.request.content)
    assert sent["stream"] is True
    assert sent["store"] is False

    assert result.status_code == 200
    assert result.is_stream
    assert result.media_type == "text/event-stream"
    assert result.stream is not None
    collected = b""
    async for piece in result.stream:
        collected += piece
    # The Responses event stream flows through untouched (style passthrough).
    assert b"response.output_text.delta" in collected
    assert b"Hello" in collected
    assert b"response.completed" in collected


async def test_codex_stream_false_is_aggregated_to_json(db, seeded):
    """Client stream=false → upstream still stream=true+store=false; the SSE is
    consumed and folded into a single Responses JSON object."""
    await _add_codex_provider(db)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(CODEX_URL).mock(
            return_value=httpx.Response(200, content=CODEX_SSE, headers=_SSE_HEADERS)
        )
        result = await dispatch(_codex_req(stream=False))

    sent = json.loads(route.calls.last.request.content)
    # The upstream ALWAYS sees streaming + store=false.
    assert sent["stream"] is True
    assert sent["store"] is False

    # The client gets a complete, non-streamed Responses object.
    assert result.status_code == 200
    assert not result.is_stream
    assert result.media_type == "application/json"
    body = json.loads(result.content or b"{}")
    assert body["object"] == "response"
    assert body["status"] == "completed"
    assert body["model"] == "gpt-5.6-sol"
    assert body["store"] is False  # adapter describes the folded reply
    texts = [
        part.get("text")
        for item in body["output"]
        if isinstance(item, dict) and item.get("type") == "message"
        for part in item.get("content", [])
        if isinstance(part, dict)
    ]
    assert "Hello" in texts
    assert body["usage"] == {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}


async def test_codex_client_store_true_is_forced_false(db, seeded):
    """A client-supplied store=true never reaches the wire."""
    await _add_codex_provider(db)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(CODEX_URL).mock(
            return_value=httpx.Response(200, content=CODEX_SSE, headers=_SSE_HEADERS)
        )
        result = await dispatch(_codex_req(stream=True, store=True))

    sent = json.loads(route.calls.last.request.content)
    assert sent["store"] is False
    assert sent["stream"] is True
    assert result.status_code == 200
    if result.stream is not None:
        async for _ in result.stream:
            pass


async def test_codex_store_defaults_to_false_when_absent(db, seeded):
    """No client store → upstream still gets an explicit store=false."""
    await _add_codex_provider(db)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(CODEX_URL).mock(
            return_value=httpx.Response(200, content=CODEX_SSE, headers=_SSE_HEADERS)
        )
        result = await dispatch(_codex_req(stream=True))

    sent = json.loads(route.calls.last.request.content)
    assert sent["store"] is False
    assert result.status_code == 200
    if result.stream is not None:
        async for _ in result.stream:
            pass


async def test_codex_openai_inbound_store_true_also_forced(db, seeded):
    """The fix is independent of the inbound dialect: an OpenAI chat-completions
    client with stream=false + store=true still produces the Codex wire contract
    and gets a chat.completion back."""
    await _add_codex_provider(db)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(CODEX_URL).mock(
            return_value=httpx.Response(200, content=CODEX_SSE, headers=_SSE_HEADERS)
        )
        result = await dispatch(
            DispatchRequest(
                inbound_style=ApiStyle.OPENAI,
                model="codex-gpt",
                payload={
                    "model": "codex-gpt",
                    "stream": False,
                    "store": True,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                stream=False,
            )
        )

    sent = json.loads(route.calls.last.request.content)
    assert sent["stream"] is True
    assert sent["store"] is False
    # Responses-shaped request (input, not messages) — style was translated.
    assert "input" in sent and "messages" not in sent

    assert result.status_code == 200
    assert not result.is_stream
    body = json.loads(result.content or b"{}")
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "Hello"
    assert body["usage"]["total_tokens"] == 7


async def test_regular_openai_provider_stream_store_untouched(db, seeded):
    """Non-Codex providers are unaffected: store is never injected, and
    stream=false stays a plain non-streaming upstream request."""
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://api.deepseek.com/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "chatcmpl-1",
                    "object": "chat.completion",
                    "model": "deepseek-chat",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "hi"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )
        )
        result = await dispatch(
            DispatchRequest(
                inbound_style=ApiStyle.OPENAI,
                model="deepseek-chat",
                payload={
                    "model": "deepseek-chat",
                    "stream": False,
                    "store": True,  # must pass through untouched
                    "messages": [{"role": "user", "content": "hi"}],
                },
                stream=False,
            )
        )

    sent = json.loads(route.calls.last.request.content)
    assert "stream" not in sent  # non-streaming request drops the flag
    assert sent["store"] is True  # never overridden for non-Codex providers
    assert result.status_code == 200
    assert not result.is_stream


async def test_codex_upstream_error_event_is_an_error(db, seeded):
    """An upstream ``error`` SSE event must surface as an error — never as a
    hung request, an empty 200, or a partial success."""
    await _add_codex_provider(db)
    sse = (
        b'data: {"type":"response.created","response":{"id":"resp_e","status":"in_progress"}}\n\n'
        b"event: error\n"
        b'data: {"type":"error","code":"rate_limit","message":"slow down"}\n\n'
    )
    with respx.mock(assert_all_called=True) as mock:
        mock.post(CODEX_URL).mock(
            return_value=httpx.Response(200, content=sse, headers=_SSE_HEADERS)
        )
        result = await dispatch(_codex_req(stream=False))

    assert result.status_code >= 400
    assert not result.is_stream
    content = result.content or b""
    assert b"slow down" in content


async def test_codex_empty_max_output_incomplete_is_an_error(db, seeded):
    await _add_codex_provider(db)
    sse = (
        b"event: response.incomplete\n"
        b'data: {"type":"response.incomplete","response":{"status":"incomplete",'
        b'"output":[],"usage":{"input_tokens":0,"output_tokens":0},'
        b'"incomplete_details":{"reason":"max_output_tokens"}}}\n\n'
    )
    with respx.mock(assert_all_called=True) as mock:
        mock.post(CODEX_URL).mock(
            return_value=httpx.Response(200, content=sse, headers=_SSE_HEADERS)
        )
        result = await dispatch(_codex_req(stream=False))

    assert result.status_code >= 400
    assert b"max_output_tokens" in (result.content or b"")


async def test_codex_interrupted_stream_is_an_error(db, seeded):
    """EOF before ``response.completed`` must not be served as a success."""
    await _add_codex_provider(db)
    truncated = (
        b'data: {"type":"response.created","response":{"id":"resp_t","status":"in_progress"}}\n\n'
        b'data: {"type":"response.output_text.delta","item_id":"m","output_index":0,'
        b'"content_index":0,"delta":"Hel"}\n\n'
        # … connection drops here; no response.completed.
    )
    with respx.mock(assert_all_called=True) as mock:
        mock.post(CODEX_URL).mock(
            return_value=httpx.Response(200, content=truncated, headers=_SSE_HEADERS)
        )
        result = await dispatch(_codex_req(stream=False))

    assert result.status_code >= 400
    assert not result.is_stream
    # The partial "Hel" text must never be presented as a completed response.
    assert result.content is None or b'"status": "completed"' not in result.content


async def test_codex_aggregation_client_disconnect_cancels_upstream(db, seeded):
    """A client disconnect mid-aggregation cancels the upstream read instead of
    consuming the whole Codex response for nothing."""
    await _add_codex_provider(db)
    import asyncio

    gate = asyncio.Event()

    async def stalled_stream(request: httpx.Request) -> httpx.Response:
        async def body():
            yield b'data: {"type":"response.created","response":{"id":"r","status":"in_progress"}}\n\n'
            await gate.wait()  # never released — simulates a stalled upstream
            yield b"data: [DONE]\n\n"  # pragma: no cover

        return httpx.Response(200, content=body(), headers=_SSE_HEADERS)

    with respx.mock(assert_all_called=False) as mock:
        mock.post(CODEX_URL).mock(side_effect=stalled_stream)
        task = asyncio.create_task(dispatch(_codex_req(stream=False)))
        await asyncio.sleep(0.2)  # let the aggregation begin
        task.cancel()  # client went away
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_codex_store_and_stream_flags_at_adapter_level():
    """_prepare_body applies the capabilities for Codex and leaves others alone."""
    from voidswitch.models.db import Provider as P

    codex = get_adapter(P(name="c", type="codex", base_url=""))
    req = DispatchRequest(
        inbound_style=ApiStyle.OPENAI_RESPONSES,
        model="m",
        payload={"model": "m", "input": "hi", "store": True, "stream": False},
        stream=False,
    )
    _, _, body = _prepare_body(req, codex, ApiStyle.OPENAI_RESPONSES, "gpt-5.6-sol", "tok")
    assert body["store"] is False
    assert body["stream"] is True

    oai = get_adapter(P(name="o", type="openai-resp", base_url="https://api.openai.com/v1"))
    _, _, body = _prepare_body(req, oai, ApiStyle.OPENAI_RESPONSES, "gpt-5", "tok")
    assert body["store"] is True  # untouched
    assert "stream" not in body  # client asked non-streaming; provider allows it


async def test_codex_drops_unsupported_params(db, seeded):
    """The Codex backend 400s on parameters it doesn't know (e.g.
    ``Unsupported parameter: temperature``). prepare_body keeps only the
    known-good wire fields, whatever the client or translator produced."""
    await _add_codex_provider(db)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(CODEX_URL).mock(
            return_value=httpx.Response(200, content=CODEX_SSE, headers=_SSE_HEADERS)
        )
        result = await dispatch(
            _codex_req(
                stream=True,
                store=True,
                max_output_tokens=32000,
                stop=["\n"],
                top_k=40,
                stream_options={"include_usage": True},
                n=2,
                seed=42,
            )
        )

    sent = json.loads(route.calls.last.request.content)
    for banned in (
        "max_output_tokens",
        "temperature",
        "top_p",
        "stop",
        "top_k",
        "stream_options",
        "n",
        "seed",
    ):
        assert banned not in sent, banned
    assert sent["store"] is False
    assert sent["stream"] is True
    assert sent["include"] == ["reasoning.encrypted_content"]
    # Supported fields pass through untouched.
    assert sent["model"] == "gpt-5.6-sol"
    assert sent["input"] == "hi"
    assert result.status_code == 200
    if result.stream is not None:
        async for _ in result.stream:
            pass
