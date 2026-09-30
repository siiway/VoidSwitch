from __future__ import annotations

import asyncio
from typing import cast

import httpx
import pytest
import respx
from voidswitch.services.network import (
    Deadline,
    NetworkExhausted,
    NetworkTarget,
    OwnedResponse,
    Route,
    execute_request,
    read_response_body,
)

pytestmark = pytest.mark.asyncio


async def test_pre_header_failure_rotates_to_unique_route():
    url = "https://example.test/v1"
    routes = [
        (Route(proxy_url="http://one.test"), None),
        (Route(proxy_url="http://two.test"), None),
    ]
    with respx.mock(assert_all_called=True) as mock:
        endpoint = mock.post(url).mock(
            side_effect=[httpx.ConnectError("down"), httpx.Response(200, json={"ok": True})]
        )
        owned = await execute_request(
            target=NetworkTarget.explicit(routes), method="POST", url=url, json_body={}
        )
        assert endpoint.call_count == 2
        assert owned.response.status_code == 200
        assert len(owned.attempts) == 2
        await owned.aclose()


async def test_http_response_never_rotates_inside_network_executor():
    url = "https://example.test/v1"
    routes = [
        (Route(proxy_url="http://one.test"), None),
        (Route(proxy_url="http://two.test"), None),
    ]
    with respx.mock(assert_all_called=True) as mock:
        endpoint = mock.post(url).mock(return_value=httpx.Response(503, text="unavailable"))
        owned = await execute_request(
            target=NetworkTarget.explicit(routes), method="POST", url=url, json_body={}
        )
        assert endpoint.call_count == 1
        assert owned.response.status_code == 503
        assert len(owned.attempts) == 1
        await owned.aclose()


async def test_single_route_is_not_repeated_to_fill_default_budget():
    url = "https://example.test/v1"
    route = Route()
    with respx.mock(assert_all_called=True) as mock:
        endpoint = mock.post(url).mock(return_value=httpx.Response(200, json={}))
        owned = await execute_request(
            target=NetworkTarget.explicit([(route, None), (route, None)]),
            method="POST",
            url=url,
            json_body={},
        )
        assert endpoint.call_count == 1
        assert len(owned.attempts) == 1
        await owned.aclose()


async def test_deadline_timeout_is_included_in_attempt_trace(monkeypatch):
    class SlowClient:
        def build_request(self, *args, **kwargs):
            return httpx.Request("POST", "https://example.test/v1")

        async def send(self, request, *, stream):
            import asyncio

            await asyncio.sleep(1)

    async def get(*args, **kwargs):
        return SlowClient()

    monkeypatch.setattr(
        "voidswitch.services.network.get_pool", lambda: type("P", (), {"get": get})()
    )
    with pytest.raises(NetworkExhausted) as caught:
        await execute_request(
            target=NetworkTarget.explicit([(Route(), None)]),
            method="POST",
            url="https://example.test/v1",
            deadline=Deadline.after(0.01),
        )
    assert len(caught.value.attempts) == 1
    assert caught.value.attempts[0].deadline_timeout is True


async def test_owned_response_cleanup_completes_when_caller_is_cancelled():
    import asyncio

    started = asyncio.Event()
    release = asyncio.Event()

    class SlowCloseResponse:
        async def aclose(self):
            started.set()
            await release.wait()

    owned = OwnedResponse(
        response=cast(httpx.Response, SlowCloseResponse()),
        route=Route(),
        node=None,
        started_at=0,
        headers_at=0,
        attempts=[],
    )
    task = asyncio.create_task(owned.aclose())
    await started.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_response_body_read_uses_remaining_deadline_and_is_cancellation_safe():
    import asyncio

    closed = asyncio.Event()

    async def body():
        try:
            await asyncio.sleep(1)
            yield b"late"
        finally:
            closed.set()

    response = httpx.Response(503, content=body())
    with pytest.raises(TimeoutError):
        await read_response_body(response, Deadline.after(0.01))
    await response.aclose()
    assert closed.is_set()


async def test_executor_resolves_provider_target_and_caller_does_not_select_nodes(monkeypatch):
    provider = object()
    route = Route(proxy_url="http://resolved.test")
    seen = {}

    async def resolve(target, session):
        seen["target"] = target
        seen["session"] = session
        return [(route, None)]

    monkeypatch.setattr("voidswitch.services.network.resolve_target", resolve)
    with respx.mock(assert_all_called=True) as mock:
        mock.post("https://example.test/v1").mock(return_value=httpx.Response(200, json={}))
        owned = await execute_request(
            target=NetworkTarget.for_provider(provider),
            session="db-session",
            method="POST",
            url="https://example.test/v1",
        )
    assert seen == {
        "target": NetworkTarget.for_provider(provider),
        "session": "db-session",
    }
    assert owned.route == route
    await owned.aclose()


async def test_retryable_http_then_network_failure_returns_last_http_response():
    routes = [
        (Route(proxy_url="http://one.test"), None),
        (Route(proxy_url="http://two.test"), None),
    ]
    with respx.mock(assert_all_called=True) as mock:
        endpoint = mock.post("https://example.test/v1").mock(
            side_effect=[
                httpx.Response(503, text="terminal upstream body"),
                httpx.ConnectError("down"),
            ]
        )
        owned = await execute_request(
            target=NetworkTarget.explicit(routes),
            method="POST",
            url="https://example.test/v1",
            retry_response=lambda response: response.status_code >= 500,
        )
    assert endpoint.call_count == 2
    assert owned.response.status_code == 503
    assert owned.response.text == "terminal upstream body"
    assert owned.attempts[-1].error is not None
    await owned.aclose()


class _TrackedStream(httpx.AsyncByteStream):
    def __init__(self, *, error: Exception | None = None, wait: asyncio.Event | None = None):
        self.error = error
        self.wait = wait
        self.closed = False
        self.read_started = asyncio.Event()

    async def __aiter__(self):
        self.read_started.set()
        if self.wait is not None:
            await self.wait.wait()
        if self.error is not None:
            raise self.error
        yield b"retry body"

    async def aclose(self):
        self.closed = True


def _install_stream_client(monkeypatch, stream: _TrackedStream):
    class Client:
        def build_request(self, *args, **kwargs):
            return httpx.Request("POST", "https://example.test/v1")

        async def send(self, request, *, stream: bool):
            return httpx.Response(503, request=request, stream=globals_stream)

    globals_stream = stream

    async def get(*args, **kwargs):
        return Client()

    monkeypatch.setattr(
        "voidswitch.services.network.get_pool", lambda: type("P", (), {"get": get})()
    )


@pytest.mark.parametrize(
    ("error", "use_deadline", "callback", "expected"),
    [
        (httpx.ReadError("broken body"), False, lambda response: True, NetworkExhausted),
        (None, True, lambda response: True, NetworkExhausted),
        (
            None,
            False,
            lambda response: (_ for _ in ()).throw(RuntimeError("callback")),
            RuntimeError,
        ),
    ],
)
async def test_retry_response_closes_unreturned_response_on_failure(
    monkeypatch, error, use_deadline, callback, expected
):
    stream = _TrackedStream(error=error, wait=asyncio.Event() if use_deadline else None)
    _install_stream_client(monkeypatch, stream)

    with pytest.raises(expected):
        await execute_request(
            target=NetworkTarget.explicit([(Route(), None)]),
            method="POST",
            url="https://example.test/v1",
            deadline=Deadline.after(0.01) if use_deadline else None,
            retry_response=callback,
        )

    assert stream.closed is True


async def test_retry_response_closes_unreturned_response_on_cancellation(monkeypatch):
    stream = _TrackedStream(wait=asyncio.Event())
    _install_stream_client(monkeypatch, stream)
    task = asyncio.create_task(
        execute_request(
            target=NetworkTarget.explicit([(Route(), None)]),
            method="POST",
            url="https://example.test/v1",
            retry_response=lambda response: True,
        )
    )
    await stream.read_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert stream.closed is True
