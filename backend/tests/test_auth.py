"""Authentication helpers."""

from __future__ import annotations

import pytest
from voidswitch.core import auth
from voidswitch.services import settings_store

pytestmark = pytest.mark.asyncio


async def test_oauth_client_uses_static_proxy(monkeypatch):
    seen = {}

    class Pool:
        async def get(self, route, *, connect_timeout, read_timeout):
            seen["route"] = route
            seen["connect_timeout"] = connect_timeout
            seen["read_timeout"] = read_timeout
            return object()

    monkeypatch.setattr(settings_store, "get_str", lambda key, default="": "http://proxy:7890")
    monkeypatch.setattr(auth, "get_pool", lambda: Pool())

    await auth._oauth_client()

    assert seen["route"].proxy_url == "http://proxy:7890"
    assert seen["route"].local_address is None
    assert seen["connect_timeout"] == 15.0
    assert seen["read_timeout"] == 30.0
