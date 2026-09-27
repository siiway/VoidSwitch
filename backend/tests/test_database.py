"""Request-session cleanup under ASGI cancellation."""

from __future__ import annotations

import asyncio

import pytest
from voidswitch.core import database as database_module
from voidswitch.core.database import RequestSessionMiddleware

pytestmark = pytest.mark.asyncio


async def test_cancelled_request_waits_for_session_close(monkeypatch):
    close_started = asyncio.Event()
    permit_close = asyncio.Event()

    class Session:
        def in_transaction(self):
            return False

        async def rollback(self):
            raise AssertionError("rollback should not run without a transaction")

        async def close(self):
            close_started.set()
            await permit_close.wait()

    class Database:
        def session_factory(self):
            return Session()

    async def app(scope, receive, send):
        await asyncio.Event().wait()

    async def receive():
        await asyncio.Event().wait()
        return {}

    async def send(message):
        return None

    monkeypatch.setattr(database_module, "get_database", lambda: Database())
    middleware = RequestSessionMiddleware(app)
    task = asyncio.create_task(middleware({"type": "http", "headers": []}, receive, send))
    await asyncio.sleep(0)
    task.cancel()
    await close_started.wait()
    assert not task.done()
    permit_close.set()
    await task


async def test_streaming_response_releases_request_session_at_response_start(monkeypatch):
    close_started = asyncio.Event()
    release_response = asyncio.Event()

    class Session:
        def in_transaction(self):
            return False

        async def commit(self):
            raise AssertionError("commit should not run without a transaction")

        async def rollback(self):
            raise AssertionError("rollback should not run without a transaction")

        async def close(self):
            close_started.set()

    class Database:
        def session_factory(self):
            return Session()

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await release_response.wait()

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        return None

    monkeypatch.setattr(database_module, "get_database", lambda: Database())
    task = asyncio.create_task(
        RequestSessionMiddleware(app)({"type": "http", "headers": []}, receive, send)
    )
    try:
        await asyncio.wait_for(close_started.wait(), timeout=0.05)
    finally:
        release_response.set()
        await task
