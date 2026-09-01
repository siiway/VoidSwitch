"""Codex browser OAuth and device-code login tests."""

from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from sqlalchemy import select
from voidswitch.core.config import get_settings
from voidswitch.core.security import create_session_token
from voidswitch.models.db import ApiKey, Provider, User
from voidswitch.services import codex_oauth
from voidswitch.services.providers.codex import CodexProvider

pytestmark = pytest.mark.asyncio


def _jwt(account_id: str = "acct-1") -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {"https://api.openai.com/auth": {"chatgpt_account_id": account_id}}
        ).encode()
    ).decode().rstrip("=")
    return f"header.{payload}.signature"


async def test_codex_adapter_uses_subscription_backend_and_models():
    provider = Provider(name="Codex", type="codex", base_url="")
    adapter = CodexProvider(provider)
    assert adapter.upstream_url == "https://chatgpt.com/backend-api/codex/responses"
    assert adapter.default_models == (
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "*",
    )
    headers = adapter.headers(_jwt("acct-header"))
    assert headers["ChatGPT-Account-Id"] == "acct-header"
    assert headers["originator"] == "codex_cli_rs"


async def test_browser_login_builds_codex_authorize_url():
    url, state = codex_oauth.begin_login(7)
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == codex_oauth.AUTHORIZE_URL
    assert query["client_id"] == [codex_oauth.CLIENT_ID]
    assert query["redirect_uri"] == [codex_oauth.REDIRECT_URI]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == [state]
    codex_oauth._pending.pop(state, None)


async def test_browser_login_exchanges_pasted_callback():
    _, state = codex_oauth.begin_login(3)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(codex_oauth.TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": _jwt(),
                    "refresh_token": "refresh",
                    "expires_in": 3600,
                },
            )
        )
        bundle = await codex_oauth.complete_login(
            f"{codex_oauth.REDIRECT_URI}?code=approved&state={state}",
            state,
            provider_id=3,
        )
    assert bundle["account_id"] == "acct-1"
    assert bundle["refresh_token"] == "refresh"
    request = route.calls[0].request
    assert "grant_type=authorization_code" in request.content.decode()


async def _owner_headers(db) -> dict[str, str]:
    async with db.session() as session:
        session.add(User(sub="codex-owner", username="owner", role="owner"))
        await session.flush()
    token = create_session_token(
        secret=get_settings().server.secret_key,
        subject="codex-owner",
        extra={"role": "owner", "name": "owner"},
    )
    return {"Authorization": f"Bearer {token}"}


async def _codex_provider(db) -> int:
    async with db.session() as session:
        provider = Provider(name="Codex", type="codex", base_url="", models=["*"])
        session.add(provider)
        await session.flush()
        return provider.id


async def test_device_login_start_pending_then_complete():
    with respx.mock(assert_all_called=True) as mock:
        mock.post(codex_oauth.DEVICE_CODE_URL).mock(
            return_value=httpx.Response(
                200,
                json={"device_auth_id": "device", "user_code": "ABCD-EFGH", "interval": 2},
            )
        )
        device = await codex_oauth.begin_device_login()
        assert device["verification_url"] == codex_oauth.DEVICE_VERIFY_URL

        poll = mock.post(codex_oauth.DEVICE_TOKEN_URL).mock(
            side_effect=[
                httpx.Response(403, json={"error": "authorization_pending"}),
                httpx.Response(
                    200,
                    json={"authorization_code": "approved", "code_verifier": "verifier"},
                ),
            ]
        )
        mock.post(codex_oauth.TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={"access_token": _jwt("acct-2"), "refresh_token": "refresh-2"},
            )
        )
        assert (
            await codex_oauth.complete_device_login("device", "ABCD-EFGH") is None
        )
        bundle = await codex_oauth.complete_device_login("device", "ABCD-EFGH")
    assert poll.call_count == 2
    assert bundle is not None
    assert bundle["account_id"] == "acct-2"


async def test_device_login_admin_api_stores_key(client, db):
    headers = await _owner_headers(db)
    provider_id = await _codex_provider(db)
    with respx.mock(assert_all_called=True) as mock:
        mock.post(codex_oauth.DEVICE_CODE_URL).mock(
            return_value=httpx.Response(
                200, json={"device_auth_id": "dev-api", "user_code": "CODE-1234"}
            )
        )
        started = await client.post(
            f"/api/admin/providers/{provider_id}/keys/oauth/device/start",
            headers=headers,
        )
        assert started.status_code == 200, started.text

        mock.post(codex_oauth.DEVICE_TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={"authorization_code": "approved", "code_verifier": "verifier"},
            )
        )
        mock.post(codex_oauth.TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={"access_token": _jwt(), "refresh_token": "refresh-api"},
            )
        )
        completed = await client.post(
            f"/api/admin/providers/{provider_id}/keys/oauth/device/complete",
            headers=headers,
            json={"device_auth_id": "dev-api", "user_code": "CODE-1234"},
        )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "complete"
    async with db.session() as session:
        key = (
            await session.execute(select(ApiKey).where(ApiKey.provider_id == provider_id))
        ).scalar_one()
        assert key.key_preview.startswith("oauth")
