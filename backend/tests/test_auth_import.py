"""Tests for importing sub2api / CLIProxyAPI (cpa) auth files."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from sqlalchemy import select
from voidswitch.core.config import get_settings
from voidswitch.core.security import create_session_token, decrypt_secret
from voidswitch.models.db import ApiKey, Provider, User
from voidswitch.services import auth_import

# --------------------------------------------------------------------------- #
# parse_source — pure parsing
# --------------------------------------------------------------------------- #


def test_epoch_normalisation_variants():
    # Seconds passthrough.
    assert auth_import._to_epoch_seconds(1_700_000_000) == 1_700_000_000.0
    # Milliseconds are divided down.
    assert auth_import._to_epoch_seconds(1_700_000_000_000) == 1_700_000_000.0
    # Numeric string.
    assert auth_import._to_epoch_seconds("1700000000") == 1_700_000_000.0
    # RFC3339 with Z.
    got = auth_import._to_epoch_seconds("2030-01-01T00:00:00Z")
    assert got == dt.datetime(2030, 1, 1, tzinfo=dt.UTC).timestamp()
    # Garbage / empty → None.
    assert auth_import._to_epoch_seconds("") is None
    assert auth_import._to_epoch_seconds("not-a-date") is None
    assert auth_import._to_epoch_seconds(None) is None


def test_parse_cpa_claude_oauth_object():
    blob = json.dumps(
        {
            "id_token": "id-1",
            "access_token": "acc-1",
            "refresh_token": "ref-1",
            "email": "a@x.io",
            "type": "claude",
            "expired": "2030-01-01T00:00:00Z",
        }
    )
    parsed = auth_import.parse_source(blob)
    assert not parsed.skipped
    assert len(parsed.accounts) == 1
    acc = parsed.accounts[0]
    assert acc.source == "cpa"
    assert acc.platform == "claude"
    assert acc.account_type == "oauth"
    assert acc.is_bundle
    assert acc.label == "a@x.io"
    bundle = json.loads(acc.secret)
    assert bundle["access_token"] == "acc-1"
    assert bundle["refresh_token"] == "ref-1"
    assert bundle["expires_at"] == dt.datetime(2030, 1, 1, tzinfo=dt.UTC).timestamp()


def test_parse_cpa_codex_platform_alias_and_id_token_fallback():
    # codex → openai; no access_token/api_key, only id_token → stored raw.
    blob = json.dumps({"id_token": "tok-only", "type": "codex"})
    parsed = auth_import.parse_source(blob)
    assert len(parsed.accounts) == 1
    acc = parsed.accounts[0]
    assert acc.platform == "openai"
    assert acc.account_type == "token"
    assert not acc.is_bundle
    assert acc.secret == "tok-only"


def test_parse_cpa_array():
    blob = json.dumps(
        [
            {"access_token": "a1", "refresh_token": "r1", "type": "claude"},
            {"api_key": "sk-2", "type": "gemini"},
        ]
    )
    parsed = auth_import.parse_source(blob)
    assert len(parsed.accounts) == 2
    assert parsed.accounts[0].account_type == "oauth"
    assert parsed.accounts[1].account_type == "api_key"
    assert parsed.accounts[1].platform == "gemini"


def test_parse_sub2api_export():
    blob = json.dumps(
        {
            "proxies": [],
            "accounts": [
                {
                    "platform": "claude",
                    "type": "oauth",
                    "credentials": {
                        "access_token": "acc-s",
                        "refresh_token": "ref-s",
                        "expires_at": 1_700_000_000,
                    },
                    "name": "acct-1",
                },
                {
                    "platform": "openai",
                    "type": "api_key",
                    "credentials": {"api_key": "sk-openai"},
                },
                {
                    "platform": "claude",
                    "type": "cookie",
                    "credentials": {"session_key": "sess-1"},
                },
            ],
        }
    )
    parsed = auth_import.parse_source(blob)
    assert not parsed.skipped
    assert len(parsed.accounts) == 3
    oauth = parsed.accounts[0]
    assert oauth.source == "sub2api"
    assert oauth.is_bundle
    assert oauth.label == "acct-1"
    assert json.loads(oauth.secret)["expires_at"] == 1_700_000_000.0
    assert parsed.accounts[1].account_type == "api_key"
    assert parsed.accounts[1].secret == "sk-openai"
    assert parsed.accounts[2].account_type == "cookie"
    assert parsed.accounts[2].secret == "sess-1"


def test_parse_sub2api_single_account():
    blob = json.dumps(
        {
            "platform": "gemini",
            "type": "oauth",
            "credentials": {"access_token": "acc-g", "expires_at": "2030-01-01T00:00:00Z"},
        }
    )
    parsed = auth_import.parse_source(blob)
    assert len(parsed.accounts) == 1
    assert parsed.accounts[0].platform == "gemini"
    assert parsed.accounts[0].is_bundle


def test_parse_sub2api_oauth_without_access_token_is_skipped():
    blob = json.dumps(
        {"platform": "claude", "type": "oauth", "credentials": {"refresh_token": "r"}}
    )
    parsed = auth_import.parse_source(blob)
    assert not parsed.accounts
    assert len(parsed.skipped) == 1
    assert parsed.skipped[0].source == "sub2api"


def test_parse_jsonl_fallback():
    blob = "\n".join(
        [
            json.dumps({"access_token": "a1", "type": "claude"}),
            "   ",
            json.dumps({"api_key": "sk-2", "type": "gemini"}),
        ]
    )
    parsed = auth_import.parse_source(blob)
    assert len(parsed.accounts) == 2


def test_parse_blank_is_empty():
    parsed = auth_import.parse_source("   ")
    assert not parsed.accounts and not parsed.skipped


# --------------------------------------------------------------------------- #
# import_credentials — via the admin API endpoint
# --------------------------------------------------------------------------- #


async def _owner_headers(db) -> dict[str, str]:
    secret_key = get_settings().server.secret_key
    async with db.session() as session:
        existing = (
            await session.execute(select(User).where(User.sub == "owner-imp"))
        ).scalar_one_or_none()
        if existing is None:
            session.add(User(sub="owner-imp", username="owner", email="o@x.io", role="owner"))
            await session.flush()
    token = create_session_token(
        secret=secret_key, subject="owner-imp", extra={"role": "owner", "name": "owner"}
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_cc_provider(db) -> int:
    async with db.session() as session:
        provider = Provider(
            name="cc-import", type="claude-code", base_url="https://api.anthropic.com", models=["*"]
        )
        session.add(provider)
        await session.flush()
        return provider.id


@pytest.mark.asyncio
async def test_import_endpoint_creates_keys_and_dedupes(client, db):
    headers = await _owner_headers(db)
    pid = await _make_cc_provider(db)

    cpa_file = json.dumps(
        {"access_token": "acc-1", "refresh_token": "ref-1", "type": "claude", "email": "a@x.io"}
    )
    sub2api_file = json.dumps(
        {
            "accounts": [
                {
                    "platform": "claude",
                    "type": "oauth",
                    "credentials": {"access_token": "acc-2", "refresh_token": "ref-2"},
                },
                {"platform": "openai", "type": "api_key", "credentials": {"api_key": "sk-x"}},
            ]
        }
    )

    resp = await client.post(
        f"/api/admin/providers/{pid}/keys/import",
        headers=headers,
        json={"sources": [cpa_file, sub2api_file], "pool": "batch1", "note": "seed"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["imported"] == 3
    assert body["duplicates"] == 0
    assert body["by_source"] == {"cpa": 1, "sub2api": 2}
    assert body["by_platform"]["claude"] == 2
    assert body["by_platform"]["openai"] == 1
    assert len(body["keys"]) == 3

    # A stored OAuth key decrypts to a usable bundle.
    secret_key = get_settings().server.secret_key
    async with db.session() as session:
        rows = (
            (await session.execute(select(ApiKey).where(ApiKey.provider_id == pid))).scalars().all()
        )
    assert len(rows) == 3
    bundles = [decrypt_secret(r.key_ciphertext, secret=secret_key) for r in rows]
    assert any('"access_token": "acc-1"' in b for b in bundles)
    assert all(r.pool == "batch1" for r in rows)

    # Re-importing the same files adds nothing (dedupe by hash).
    again = await client.post(
        f"/api/admin/providers/{pid}/keys/import",
        headers=headers,
        json={"sources": [cpa_file, sub2api_file], "pool": "batch1"},
    )
    assert again.status_code == 201, again.text
    body2 = again.json()
    assert body2["imported"] == 0
    assert body2["duplicates"] == 3


@pytest.mark.asyncio
async def test_import_endpoint_rejects_empty_sources(client, db):
    headers = await _owner_headers(db)
    pid = await _make_cc_provider(db)
    resp = await client.post(
        f"/api/admin/providers/{pid}/keys/import",
        headers=headers,
        json={"sources": ["   ", ""]},
    )
    assert resp.status_code == 400
