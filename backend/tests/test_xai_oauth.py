"""Tests for xAI (Grok) OAuth token refresh on the official ``api.x.ai`` adapter.

Unlike Claude Code, the xAI flow is refresh-only: there is no interactive login.
A key is stored as either a plain ``xai-…`` API key (static, never refreshed) or
an OAuth bundle ``{"access_token"?, "refresh_token", "expires_at"?}`` that is
refreshed near expiry, when it has no access token yet (sub2api refresh-only
exports), or on a forced 401 retry.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest
import respx
from sqlalchemy import select
from voidswitch.constants import KeyStatus
from voidswitch.core.config import get_settings
from voidswitch.core.security import decrypt_secret, encrypt_secret, hash_token
from voidswitch.models.db import ApiKey, Provider, Proxy, RequestLog
from voidswitch.services import settings_store, xai_oauth

pytestmark = pytest.mark.asyncio


async def _make_key(db, secret: str) -> int:
    secret_key = get_settings().server.secret_key
    async with db.session() as session:
        provider = Provider(
            name="xai",
            type="xai",
            base_url="https://api.x.ai/v1",
            models=["*"],
        )
        session.add(provider)
        await session.flush()
        key = ApiKey(
            provider_id=provider.id,
            key_ciphertext=encrypt_secret(secret, secret=secret_key),
            key_hash=hash_token(secret),
            key_preview="xai",
            status=KeyStatus.ACTIVE.value,
        )
        session.add(key)
        await session.flush()
        return key.id


async def test_static_api_key_is_returned_as_is(db):
    secret_key = get_settings().server.secret_key
    key_id = await _make_key(db, "xai-static-key")
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(xai_oauth.TOKEN_URL)
        async with db.session() as session:
            key = await session.get(ApiKey, key_id)
            token = await xai_oauth.resolve_access_token(session, key, secret_key=secret_key)
    assert token == "xai-static-key"
    assert not route.called  # a plain key never touches the network


async def test_refresh_only_bundle_mints_access_token(db):
    """sub2api exports a bundle with only a refresh_token — resolving it must
    immediately mint an access token and persist the rotated bundle."""
    secret_key = get_settings().server.secret_key
    key_id = await _make_key(db, json.dumps({"refresh_token": "r-only"}))
    with respx.mock(assert_all_called=True) as mock:
        mock.post(xai_oauth.TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "fresh-access",
                    "refresh_token": "r-rotated",
                    "expires_in": 3600,
                },
            )
        )
        async with db.session() as session:
            key = await session.get(ApiKey, key_id)
            token = await xai_oauth.resolve_access_token(session, key, secret_key=secret_key)
    assert token == "fresh-access"

    async with db.session() as session:
        key = await session.get(ApiKey, key_id)
        bundle = json.loads(decrypt_secret(key.key_ciphertext, secret=secret_key))
    assert bundle["access_token"] == "fresh-access"
    assert bundle["refresh_token"] == "r-rotated"
    assert bundle["expires_at"] > time.time()


async def test_near_expiry_triggers_refresh(db):
    secret_key = get_settings().server.secret_key
    key_id = await _make_key(
        db,
        json.dumps(
            {
                "access_token": "old-access",
                "refresh_token": "refresh-1",
                "expires_at": time.time() + 10,  # inside the 5-min buffer
            }
        ),
    )
    with respx.mock(assert_all_called=True) as mock:
        mock.post(xai_oauth.TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "new-access",
                    "refresh_token": "refresh-2",
                    "expires_in": 3600,
                },
            )
        )
        async with db.session() as session:
            key = await session.get(ApiKey, key_id)
            token = await xai_oauth.resolve_access_token(session, key, secret_key=secret_key)
    assert token == "new-access"

    async with db.session() as session:
        key = await session.get(ApiKey, key_id)
        bundle = json.loads(decrypt_secret(key.key_ciphertext, secret=secret_key))
    assert bundle["access_token"] == "new-access"
    assert bundle["refresh_token"] == "refresh-2"


async def test_healthy_bundle_not_refreshed(db):
    secret_key = get_settings().server.secret_key
    key_id = await _make_key(
        db,
        json.dumps(
            {
                "access_token": "still-good",
                "refresh_token": "refresh-1",
                "expires_at": time.time() + 7200,  # far from expiry
            }
        ),
    )
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(xai_oauth.TOKEN_URL)
        async with db.session() as session:
            key = await session.get(ApiKey, key_id)
            token = await xai_oauth.resolve_access_token(session, key, secret_key=secret_key)
    assert token == "still-good"
    assert not route.called


async def test_refresh_uses_static_proxy_and_records_request_log(db):
    secret_key = get_settings().server.secret_key
    key_id = await _make_key(db, json.dumps({"refresh_token": "r-only"}))
    async with db.session() as session:
        await settings_store.update(
            session,
            {"proxy_switching_enabled": False, "static_proxy_url": "http://static.local:8080"},
        )
    with respx.mock(assert_all_called=True) as mock:
        mock.post(xai_oauth.TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "a", "refresh_token": "r2", "expires_in": 3600},
            )
        )
        async with db.session() as session:
            key = await session.get(ApiKey, key_id)
            await xai_oauth.resolve_access_token(session, key, secret_key=secret_key)

    async with db.session() as session:
        row = (
            await session.execute(
                select(RequestLog).where(RequestLog.model == "<xai-refresh-token>")
            )
        ).scalar_one()
    assert row.success is True
    assert row.status_code == 200
    assert row.proxy_url == "http://static.local:8080"
    assert row.client_type == "xai-oauth"


async def test_force_refresh_on_static_raises(db):
    secret_key = get_settings().server.secret_key
    key_id = await _make_key(db, "xai-static-key")
    async with db.session() as session:
        key = await session.get(ApiKey, key_id)
        with pytest.raises(xai_oauth.NotRefreshable):
            await xai_oauth.resolve_access_token(
                session, key, secret_key=secret_key, force_refresh=True
            )


async def test_bundle_without_access_or_refresh_raises(db):
    """A JSON object with neither token is not even recognised as a bundle, so
    it is treated as a static token and returned verbatim (no crash)."""
    secret_key = get_settings().server.secret_key
    key_id = await _make_key(db, json.dumps({"scope": "nothing-useful"}))
    async with db.session() as session:
        key = await session.get(ApiKey, key_id)
        token = await xai_oauth.resolve_access_token(session, key, secret_key=secret_key)
    assert token == json.dumps({"scope": "nothing-useful"})


async def test_refresh_rotates_past_blocked_egress(db):
    """A 403 on the first proxy rotates to the next egress and succeeds."""
    secret_key = get_settings().server.secret_key
    key_id = await _make_key(db, json.dumps({"refresh_token": "r-only"}))
    async with db.session() as session:
        session.add(Proxy(url="http://p1.local:8080", status="active", enabled=True))
        session.add(Proxy(url="http://p2.local:8080", status="active", enabled=True))
        await session.flush()
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(xai_oauth.TOKEN_URL).mock(
            side_effect=[
                httpx.Response(403, json={"error": {"message": "blocked"}}),
                httpx.Response(
                    200,
                    json={"access_token": "a", "refresh_token": "r2", "expires_in": 3600},
                ),
            ]
        )
        async with db.session() as session:
            key = await session.get(ApiKey, key_id)
            token = await xai_oauth.resolve_access_token(session, key, secret_key=secret_key)
    assert token == "a"
    assert route.call_count == 2
