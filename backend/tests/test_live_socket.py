"""Real-socket integration test.

Spins up a tiny upstream HTTP server in a background thread and routes a request
through the dispatcher over an actual TCP connection (no respx) — exercising the
real httpx client, streaming, and translation end to end.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from voidswitch.constants import ApiStyle, KeyStatus
from voidswitch.core.config import get_settings
from voidswitch.core.security import encrypt_secret, hash_token
from voidswitch.models.db import (
    ApiKey,
    ExposedModel,
    Provider,
    RouteLayer,
    RoutePoolEntry,
    User,
    VoidToken,
)
from voidswitch.services import model_routing
from voidswitch.services.dispatcher import DispatchRequest, dispatch

pytestmark = pytest.mark.asyncio

CHAT_JSON = {
    "id": "chatcmpl-live",
    "object": "chat.completion",
    "model": "mock-model",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "live-ok"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
}

SSE = (
    b'data: {"choices":[{"index":0,"delta":{"content":"live"}}]}\n\n'
    b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],'
    b'"usage":{"prompt_tokens":1,"completion_tokens":1}}\n\n'
    b"data: [DONE]\n\n"
)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if body.get("stream"):
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            self.wfile.write(SSE)
        else:
            payload = json.dumps(CHAT_JSON).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)


@pytest.fixture
def upstream():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


async def _seed(db, base_url: str) -> int:
    async with db.session() as session:
        user = User(sub="live-user", username="live", role="owner")
        session.add(user)
        await session.flush()
        token_secret = "vs-live"
        token = VoidToken(
            user_id=user.id,
            name="live",
            token_hash=hash_token(token_secret),
            token_prefix="live",
        )
        session.add(token)
        provider = Provider(
            name="mock", type="generic", base_url=base_url, models=["mock-model", "*"]
        )
        session.add(provider)
        await session.flush()
        session.add(
            ApiKey(
                provider_id=provider.id,
                key_ciphertext=encrypt_secret("k", secret=get_settings().server.secret_key),
                key_hash=hash_token("k-live"),
                key_preview="k",
                status=KeyStatus.ACTIVE.value,
            )
        )
        await session.flush()
        exposed = ExposedModel(model_id="mock-model")
        session.add(exposed)
        await session.flush()
        route = await model_routing.get_or_create_route(session, exposed)
        layer = RouteLayer(route_id=route.id, position=0, max_attempts=1)
        session.add(layer)
        await session.flush()
        session.add(
            RoutePoolEntry(
                layer_id=layer.id,
                provider_id=provider.id,
                upstream_model="mock-model",
            )
        )
        await session.flush()
        return token.id


async def test_live_non_stream(db, upstream):
    token_id = await _seed(db, upstream)
    result = await dispatch(
        DispatchRequest(
            inbound_style=ApiStyle.OPENAI,
            model="mock-model",
            payload={"model": "mock-model", "messages": [{"role": "user", "content": "hi"}]},
            stream=False,
            token_id=token_id,
        )
    )
    assert result.status_code == 200
    assert b"live-ok" in (result.content or b"")


async def test_live_streaming_over_real_socket(db, upstream):
    token_id = await _seed(db, upstream)
    result = await dispatch(
        DispatchRequest(
            inbound_style=ApiStyle.OPENAI,
            model="mock-model",
            payload={
                "model": "mock-model",
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            },
            stream=True,
            token_id=token_id,
        )
    )
    assert result.is_stream
    assert result.stream is not None
    collected = b""
    async for piece in result.stream:
        collected += piece
    assert b"live" in collected
    assert b"[DONE]" in collected
