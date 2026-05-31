"""Tests for the dev-mode OAuth bypass."""

from __future__ import annotations

import pytest
from voidswitch.core.config import get_settings
from voidswitch.main import create_app

pytestmark = pytest.mark.asyncio


async def test_dev_login_disabled_when_off(client, monkeypatch):
    # Force dev mode off regardless of the local config.yaml.
    monkeypatch.setattr(get_settings().server, "dev_mode", False)
    resp = await client.post("/api/auth/dev-login")
    assert resp.status_code == 404


async def test_auth_config_reports_dev_mode(client):
    resp = await client.get("/api/auth/config")
    assert resp.status_code == 200
    assert "dev_mode" in resp.json()


async def test_dev_login_when_enabled(db, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    settings = get_settings()
    monkeypatch.setattr(settings.server, "dev_mode", True)
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/auth/dev-login")
        assert resp.status_code == 200
        body = resp.json()
        assert body["user"]["role"] == "owner"
        token = body["access_token"]

        # The minted session token authenticates the dashboard API.
        me = await ac.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["sub"] == "dev-mode-user"
