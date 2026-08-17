"""Authentication helpers."""

from __future__ import annotations

import pytest
from voidswitch.core import auth
from voidswitch.core.security import (
    create_session_token,
    generate_login_token,
    hash_token,
    token_fingerprint,
)
from voidswitch.models.db import User
from voidswitch.services import settings_store

pytestmark = pytest.mark.asyncio


async def test_oauth_client_uses_system_routes_off_falls_to_static(db, monkeypatch):
    """With routing off, the OAuth client uses the static proxy route."""
    seen = {}

    class Pool:
        async def get(self, route, *, connect_timeout, read_timeout):
            seen["route"] = route
            seen["connect_timeout"] = connect_timeout
            seen["read_timeout"] = read_timeout
            return object()

    monkeypatch.setattr(settings_store, "get_bool", lambda key, default=True: False)
    monkeypatch.setattr(
        settings_store, "get_str", lambda key, default="": "http://proxy:7890"
    )
    monkeypatch.setattr(auth, "get_pool", lambda: Pool())

    await auth._oauth_client()

    assert seen["route"].proxy_url == "http://proxy:7890"
    assert seen["route"].local_address is None
    assert seen["connect_timeout"] == 15.0
    assert seen["read_timeout"] == 30.0


async def test_staff_can_use_login_token(db, client):
    raw = generate_login_token()
    async with db.session() as session:
        user = User(
            sub="owner-1",
            username="owner",
            role="owner",
            login_token_hash=hash_token(raw),
            login_token_prefix=token_fingerprint(raw),
        )
        session.add(user)
        await session.flush()

    resp = await client.post("/api/auth/token-login", json={"token": raw})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["sub"] == "owner-1"
    assert body["access_token"]


async def test_staff_can_rotate_own_login_token(db, client, settings):
    async with db.session() as session:
        user = User(sub="admin-1", username="admin", role="admin")
        session.add(user)
        await session.flush()
        user_id = user.id

    session_token = create_session_token(
        secret=settings.server.secret_key,
        subject="admin-1",
        extra={"role": "admin", "name": "admin", "epoch": 0},
        ttl_minutes=30,
    )
    headers = {"Authorization": f"Bearer {session_token}"}

    resp = await client.post("/api/me/login-token/rotate", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["prefix"]
    assert body["token"].startswith("vsl-")

    status = await client.get("/api/me/login-token", headers=headers)
    assert status.status_code == 200
    assert status.json() == {"enabled": True, "prefix": body["prefix"]}

    async with db.session() as session:
        user = await session.get(User, user_id)
        assert user is not None
        assert user.login_token_hash == hash_token(body["token"])


async def test_token_login_requires_staff(db, client):
    raw = generate_login_token()
    async with db.session() as session:
        user = User(
            sub="member-1",
            username="member",
            role="member",
            login_token_hash=hash_token(raw),
            login_token_prefix=token_fingerprint(raw),
        )
        session.add(user)
        await session.flush()

    resp = await client.post("/api/auth/token-login", json={"token": raw})
    assert resp.status_code == 401
