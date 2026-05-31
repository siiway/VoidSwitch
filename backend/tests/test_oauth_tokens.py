"""Tests for Claude Code OAuth: login (PKCE authorization-code) + token refresh."""

from __future__ import annotations

import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from sqlalchemy import select
from voidswitch.constants import ApiStyle, KeyStatus
from voidswitch.core.config import get_settings
from voidswitch.core.security import (
    create_session_token,
    decrypt_secret,
    encrypt_secret,
    hash_token,
)
from voidswitch.models.db import ApiKey, Provider, Proxy, User
from voidswitch.services import oauth_tokens
from voidswitch.services.dispatcher import DispatchRequest, dispatch

pytestmark = pytest.mark.asyncio


async def _make_key(db, bundle: dict) -> int:
    secret_key = get_settings().server.secret_key
    async with db.session() as session:
        provider = Provider(
            name="cc",
            type="claude-code",
            base_url="https://api.anthropic.com",
            models=["*"],
        )
        session.add(provider)
        await session.flush()
        key = ApiKey(
            provider_id=provider.id,
            key_ciphertext=encrypt_secret(json.dumps(bundle), secret=secret_key),
            key_hash=hash_token(json.dumps(bundle)),
            key_preview="cc",
            status=KeyStatus.ACTIVE.value,
        )
        session.add(key)
        await session.flush()
        return key.id


async def test_static_token_is_returned_as_is(db):
    secret_key = get_settings().server.secret_key
    async with db.session() as session:
        provider = Provider(name="cc", type="claude-code", models=["*"])
        session.add(provider)
        await session.flush()
        key = ApiKey(
            provider_id=provider.id,
            key_ciphertext=encrypt_secret("sk-ant-oat01-static", secret=secret_key),
            key_hash=hash_token("static"),
            key_preview="cc",
            status=KeyStatus.ACTIVE.value,
        )
        session.add(key)
        await session.flush()
        token = await oauth_tokens.resolve_access_token(session, key, secret_key=secret_key)
    assert token == "sk-ant-oat01-static"


async def test_near_expiry_triggers_refresh(db):
    secret_key = get_settings().server.secret_key
    key_id = await _make_key(
        db,
        {
            "access_token": "old-access",
            "refresh_token": "refresh-1",
            "expires_at": time.time() + 10,  # within the 5-min buffer
        },
    )
    with respx.mock(assert_all_called=True) as mock:
        mock.post(oauth_tokens.TOKEN_URL).mock(
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
            token = await oauth_tokens.resolve_access_token(session, key, secret_key=secret_key)
    assert token == "new-access"

    # The rotated bundle was persisted (new access + refresh token).
    async with db.session() as session:
        key = await session.get(ApiKey, key_id)
        bundle = json.loads(decrypt_secret(key.key_ciphertext, secret=secret_key))
    assert bundle["access_token"] == "new-access"
    assert bundle["refresh_token"] == "refresh-2"


async def test_valid_token_not_refreshed(db):
    secret_key = get_settings().server.secret_key
    key_id = await _make_key(
        db,
        {
            "access_token": "still-good",
            "refresh_token": "refresh-1",
            "expires_at": time.time() + 7200,  # far from expiry
        },
    )
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(oauth_tokens.TOKEN_URL)
        async with db.session() as session:
            key = await session.get(ApiKey, key_id)
            token = await oauth_tokens.resolve_access_token(session, key, secret_key=secret_key)
    assert token == "still-good"
    assert not route.called  # no network refresh for a healthy token


async def test_force_refresh_on_static_raises(db):
    secret_key = get_settings().server.secret_key
    async with db.session() as session:
        provider = Provider(name="cc", type="claude-code", models=["*"])
        session.add(provider)
        await session.flush()
        key = ApiKey(
            provider_id=provider.id,
            key_ciphertext=encrypt_secret("sk-ant-oat01-static", secret=secret_key),
            key_hash=hash_token("static2"),
            key_preview="cc",
            status=KeyStatus.ACTIVE.value,
        )
        session.add(key)
        await session.flush()
        with pytest.raises(oauth_tokens.NotRefreshable):
            await oauth_tokens.resolve_access_token(
                session, key, secret_key=secret_key, force_refresh=True
            )


# --------------------------------------------------------------------------- #
# Login: PKCE authorization-code flow (manual)
# --------------------------------------------------------------------------- #


def _expected_challenge(verifier: str) -> str:
    return oauth_tokens._b64url(hashlib.sha256(verifier.encode("ascii")).digest())


async def test_pkce_pair_is_s256_and_unpadded():
    verifier, challenge = oauth_tokens._pkce_pair()
    # Verifier and challenge are base64url with no padding.
    assert "=" not in verifier and "+" not in verifier and "/" not in verifier
    assert "=" not in challenge and "+" not in challenge and "/" not in challenge
    # The challenge is the S256 of the verifier — the load-bearing PKCE invariant.
    assert challenge == _expected_challenge(verifier)
    # Two pairs are independent.
    assert oauth_tokens._pkce_pair()[0] != verifier


async def test_begin_login_builds_authorize_url():
    url, state = oauth_tokens.begin_login(provider_id=7)
    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "claude.com"
    assert parsed.path == "/cai/oauth/authorize"

    qs = parse_qs(parsed.query)
    assert qs["code"] == ["true"]
    assert qs["client_id"] == [oauth_tokens.CLIENT_ID]
    assert qs["response_type"] == ["code"]
    assert qs["redirect_uri"] == [oauth_tokens.MANUAL_REDIRECT_URL]
    assert qs["code_challenge_method"] == ["S256"]
    assert qs["state"] == [state]
    # Full login scope set, including the API-key-creation scope.
    assert "org:create_api_key" in qs["scope"][0].split()
    assert "user:inference" in qs["scope"][0].split()

    # The verifier was stashed for this state+provider, and the emitted challenge
    # is genuinely the S256 of that verifier (not a plaintext/independent value).
    pending = oauth_tokens._login_states.peek(state)
    assert pending is not None
    assert pending.provider_id == 7
    assert qs["code_challenge"] == [_expected_challenge(pending.verifier)]
    oauth_tokens._login_states.discard(state)
    assert oauth_tokens._login_states.peek(state) is None


async def test_extract_code_variants():
    assert oauth_tokens.extract_code("CODE#STATE") == ("CODE", "STATE")
    assert oauth_tokens.extract_code(
        "https://platform.claude.com/oauth/code/callback?code=AC&state=ST"
    ) == ("AC", "ST")
    assert oauth_tokens.extract_code("bare-code") == ("bare-code", None)
    with pytest.raises(oauth_tokens.LoginError):
        oauth_tokens.extract_code("   ")


async def test_complete_login_exchanges_code():
    _url, state = oauth_tokens.begin_login(provider_id=1)
    # The exact verifier whose challenge is in the authorize URL.
    pending = oauth_tokens._login_states.peek(state)
    assert pending is not None
    issued_verifier = pending.verifier
    with respx.mock(assert_all_called=True) as mock:
        mock.post(oauth_tokens.TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "sk-ant-oat01-xyz",
                    "refresh_token": "rt-1",
                    "expires_in": 3600,
                    "scope": "user:inference user:profile",
                },
            )
        )
        bundle = await oauth_tokens.complete_login(f"thecode#{state}", state, provider_id=1)

        sent = json.loads(mock.calls.last.request.content)
        assert sent["grant_type"] == "authorization_code"
        assert sent["code"] == "thecode"
        assert sent["redirect_uri"] == oauth_tokens.MANUAL_REDIRECT_URL
        assert sent["client_id"] == oauth_tokens.CLIENT_ID
        # The verifier reaching the exchange is the SAME one bound to the challenge.
        assert sent["code_verifier"] == issued_verifier
        assert sent["state"] == state

    assert bundle["access_token"] == "sk-ant-oat01-xyz"
    assert bundle["refresh_token"] == "rt-1"
    assert bundle["expires_at"] > time.time()
    assert "user:inference" in bundle["scopes"]
    # The bundle is exactly what the refresh path recognises.
    assert oauth_tokens.parse_bundle(json.dumps(bundle)) is not None
    # The state was consumed on success.
    assert oauth_tokens._login_states.peek(state) is None


async def test_complete_login_unknown_state_raises():
    with pytest.raises(oauth_tokens.LoginError):
        await oauth_tokens.complete_login("code#state", "no-such-state", provider_id=1)


async def test_complete_login_wrong_provider_raises():
    _, state = oauth_tokens.begin_login(provider_id=1)
    with pytest.raises(oauth_tokens.LoginError):
        await oauth_tokens.complete_login(f"thecode#{state}", state, provider_id=2)
    # A mismatched provider burns the state.
    assert oauth_tokens._login_states.peek(state) is None


async def test_complete_login_state_mismatch_raises():
    _, state = oauth_tokens.begin_login(provider_id=1)
    # The paste embeds a different state than the one we issued.
    with pytest.raises(oauth_tokens.LoginError):
        await oauth_tokens.complete_login(f"thecode#{state}-tampered", state, provider_id=1)


async def test_complete_login_definitive_rejection_burns_state():
    _, state = oauth_tokens.begin_login(provider_id=1)
    with respx.mock(assert_all_called=True) as mock:
        mock.post(oauth_tokens.TOKEN_URL).mock(
            return_value=httpx.Response(400, json={"error": "invalid_grant"})
        )
        with pytest.raises(oauth_tokens.LoginError):
            await oauth_tokens.complete_login(f"thecode#{state}", state, provider_id=1)
    # A definitive 4xx spends the code — the state is gone.
    assert oauth_tokens._login_states.peek(state) is None


async def test_complete_login_transient_block_preserves_state():
    """A 403/blocked egress raises LoginUpstreamError but keeps the state so the
    user can retry the same code once a working proxy is available."""
    _, state = oauth_tokens.begin_login(provider_id=1)
    with respx.mock(assert_all_called=True) as mock:
        mock.post(oauth_tokens.TOKEN_URL).mock(
            return_value=httpx.Response(
                403, json={"error": {"type": "forbidden", "message": "Request not allowed"}}
            )
        )
        with pytest.raises(oauth_tokens.LoginUpstreamError):
            await oauth_tokens.complete_login(f"thecode#{state}", state, provider_id=1)
    # State preserved for a retry; not echoing the raw upstream body.
    assert oauth_tokens._login_states.peek(state) is not None
    oauth_tokens._login_states.discard(state)


# --------------------------------------------------------------------------- #
# Login: admin API endpoints
# --------------------------------------------------------------------------- #


async def _owner_headers(db) -> dict[str, str]:
    secret_key = get_settings().server.secret_key
    async with db.session() as session:
        existing = (
            await session.execute(select(User).where(User.sub == "owner-1"))
        ).scalar_one_or_none()
        if existing is None:
            session.add(User(sub="owner-1", username="owner", email="o@x.io", role="owner"))
            await session.flush()
    token = create_session_token(
        secret=secret_key, subject="owner-1", extra={"role": "owner", "name": "owner"}
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_provider(db, *, name: str, type_: str) -> int:
    async with db.session() as session:
        provider = Provider(
            name=name, type=type_, base_url="https://api.anthropic.com", models=["*"]
        )
        session.add(provider)
        await session.flush()
        return provider.id


async def test_oauth_start_rejects_non_claude_code(client, db):
    headers = await _owner_headers(db)
    pid = await _make_provider(db, name="oai", type_="openai")
    resp = await client.post(f"/api/admin/providers/{pid}/keys/oauth/start", headers=headers)
    assert resp.status_code == 400


async def test_oauth_start_and_complete_via_api(client, db):
    headers = await _owner_headers(db)
    pid = await _make_provider(db, name="cc-oauth", type_="claude-code")

    start = await client.post(f"/api/admin/providers/{pid}/keys/oauth/start", headers=headers)
    assert start.status_code == 200, start.text
    body = start.json()
    assert "claude.com/cai/oauth/authorize" in body["authorize_url"]
    state = body["state"]

    with respx.mock(assert_all_called=True) as mock:
        mock.post(oauth_tokens.TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "sk-ant-oat01-new",
                    "refresh_token": "rt-new",
                    "expires_in": 3600,
                    "scope": "user:inference",
                },
            )
        )
        done = await client.post(
            f"/api/admin/providers/{pid}/keys/oauth/complete",
            headers=headers,
            json={"code": f"theauthcode#{state}", "state": state},
        )
    assert done.status_code == 201, done.text
    out = done.json()
    assert out["status"] == "active"
    assert out["key_preview"].startswith("oauth")

    # The stored key decrypts to a refreshable credential bundle.
    secret_key = get_settings().server.secret_key
    async with db.session() as session:
        rows = (
            (await session.execute(select(ApiKey).where(ApiKey.provider_id == pid))).scalars().all()
        )
    assert len(rows) == 1
    bundle = oauth_tokens.parse_bundle(decrypt_secret(rows[0].key_ciphertext, secret=secret_key))
    assert bundle is not None
    assert bundle["access_token"] == "sk-ant-oat01-new"
    assert bundle["refresh_token"] == "rt-new"


async def test_oauth_complete_rejects_non_claude_code(client, db):
    headers = await _owner_headers(db)
    pid = await _make_provider(db, name="oai-complete", type_="openai")
    resp = await client.post(
        f"/api/admin/providers/{pid}/keys/oauth/complete",
        headers=headers,
        json={"code": "anything#state", "state": "state"},
    )
    assert resp.status_code == 400


async def test_oauth_complete_routes_through_proxies_and_rotates(client, db):
    """The exchange leaves via the configured proxies and rotates past a blocked
    egress (a 403 on the first proxy) to a working one."""
    headers = await _owner_headers(db)
    pid = await _make_provider(db, name="cc-proxy", type_="claude-code")
    async with db.session() as session:
        session.add(Proxy(url="http://p1.local:8080", status="active", enabled=True))
        session.add(Proxy(url="http://p2.local:8080", status="active", enabled=True))
        await session.flush()

    start = await client.post(f"/api/admin/providers/{pid}/keys/oauth/start", headers=headers)
    state = start.json()["state"]
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(oauth_tokens.TOKEN_URL).mock(
            side_effect=[
                httpx.Response(403, json={"error": {"message": "Request not allowed"}}),
                httpx.Response(
                    200,
                    json={
                        "access_token": "sk-ant-oat01-viaproxy",
                        "refresh_token": "rt-p",
                        "expires_in": 3600,
                    },
                ),
            ]
        )
        done = await client.post(
            f"/api/admin/providers/{pid}/keys/oauth/complete",
            headers=headers,
            json={"code": f"c#{state}", "state": state},
        )
    assert done.status_code == 201, done.text
    # It rotated: a blocked first egress, then a success on the second.
    assert route.call_count == 2


async def test_two_logins_create_two_keys(client, db):
    """Each successful sign-in mints a distinct credential key (no false dedupe)."""
    headers = await _owner_headers(db)
    pid = await _make_provider(db, name="cc-twice", type_="claude-code")

    async def _login(suffix: str) -> None:
        state = (
            await client.post(f"/api/admin/providers/{pid}/keys/oauth/start", headers=headers)
        ).json()["state"]
        with respx.mock(assert_all_called=True) as mock:
            mock.post(oauth_tokens.TOKEN_URL).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "access_token": f"sk-ant-oat01-{suffix}",
                        "refresh_token": f"rt-{suffix}",
                        "expires_in": 3600,
                    },
                )
            )
            resp = await client.post(
                f"/api/admin/providers/{pid}/keys/oauth/complete",
                headers=headers,
                json={"code": f"c#{state}", "state": state},
            )
        assert resp.status_code == 201, resp.text

    await _login("one")
    await _login("two")
    async with db.session() as session:
        rows = (
            (await session.execute(select(ApiKey).where(ApiKey.provider_id == pid))).scalars().all()
        )
    assert len(rows) == 2


async def test_dispatch_oauth_401_forces_refresh_and_retries(db):
    """The dispatcher's load-bearing path: on a 401 from a claude-code upstream,
    force-refresh the bundle once, rebuild the Bearer header, and retry the same
    key — persisting the rotated bundle."""
    secret_key = get_settings().server.secret_key
    bundle = {
        "access_token": "old-access",
        "refresh_token": "rt-old",
        "expires_at": time.time() + 7200,  # healthy → no pre-emptive refresh
    }
    async with db.session() as session:
        provider = Provider(
            name="cc-dispatch",
            type="claude-code",
            base_url="https://api.anthropic.com",
            models=["*"],
        )
        session.add(provider)
        await session.flush()
        key = ApiKey(
            provider_id=provider.id,
            key_ciphertext=encrypt_secret(json.dumps(bundle), secret=secret_key),
            key_hash=hash_token(json.dumps(bundle)),
            key_preview="cc",
            status=KeyStatus.ACTIVE.value,
        )
        session.add(key)
        await session.flush()
        key_id = key.id

    msg_url = "https://api.anthropic.com/v1/messages"
    msg_ok = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude",
        "content": [{"type": "text", "text": "hi"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 3, "output_tokens": 2},
    }
    with respx.mock(assert_all_called=False) as mock:
        msg_route = mock.post(msg_url).mock(
            side_effect=[
                httpx.Response(
                    401, json={"type": "error", "error": {"type": "authentication_error"}}
                ),
                httpx.Response(200, json=msg_ok),
            ]
        )
        tok_route = mock.post(oauth_tokens.TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "new-access", "refresh_token": "rt-new", "expires_in": 3600},
            )
        )
        result = await dispatch(
            DispatchRequest(
                inbound_style=ApiStyle.ANTHROPIC,
                model="claude-3-5-sonnet",
                payload={
                    "model": "claude-3-5-sonnet",
                    "max_tokens": 64,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                stream=False,
            )
        )

    assert result.status_code == 200, result.error
    assert result.attempts == 2
    # Exactly one refresh occurred (the oauth_refreshed once-only gate held).
    assert tok_route.call_count == 1
    # The retry carried the rotated access token.
    assert msg_route.calls[0].request.headers["authorization"] == "Bearer old-access"
    assert msg_route.calls[1].request.headers["authorization"] == "Bearer new-access"
    # The rotated bundle was persisted back into the key.
    async with db.session() as session:
        k = await session.get(ApiKey, key_id)
    rotated = oauth_tokens.parse_bundle(decrypt_secret(k.key_ciphertext, secret=secret_key))
    assert rotated is not None
    assert rotated["access_token"] == "new-access"
    assert rotated["refresh_token"] == "rt-new"
