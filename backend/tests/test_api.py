"""End-to-end API tests through the ASGI app."""

from __future__ import annotations

import httpx
import pytest
import respx
from voidswitch.core.config import get_settings
from voidswitch.core.security import create_session_token

pytestmark = pytest.mark.asyncio


def _session_headers(
    sub: str = "user-1", role: str = "owner", name: str = "alice"
) -> dict[str, str]:
    """Dashboard session JWT for the seeded user (sub ``user-1``)."""
    token = create_session_token(
        secret=get_settings().server.secret_key,
        subject=sub,
        extra={"role": role, "name": name},
    )
    return {"Authorization": f"Bearer {token}"}


DS_URL = "https://api.deepseek.com/chat/completions"

OAI_RESPONSE = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "model": "deepseek-chat",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
}


async def test_health(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_root_lists_endpoints(client):
    resp = await client.get("/")
    body = resp.json()
    assert body["endpoints"]["openai"] == "/v1/chat/completions"


async def test_chat_completions_requires_auth(client, seeded):
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 401


async def test_chat_completions_success(client, seeded):
    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(return_value=httpx.Response(200, json=OAI_RESPONSE))
        resp = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {seeded['token']}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "hello"


async def test_messages_endpoint_translates(client, seeded):
    """Anthropic-style inbound (Claude Code) reaching an OpenAI upstream."""
    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(return_value=httpx.Response(200, json=OAI_RESPONSE))
        resp = await client.post(
            "/v1/messages",
            headers={"x-api-key": seeded["token"]},
            json={
                "model": "deepseek-chat",
                "max_tokens": 64,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "message"
    assert body["content"][0]["text"] == "hello"


async def test_invalid_token_rejected(client, seeded):
    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer vs-not-a-real-token"},
        json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 401


async def test_model_not_allowed_for_token(client, db, seeded):
    from voidswitch.models.db import VoidToken

    async with db.session() as session:
        token = await session.get(VoidToken, seeded["token_id"])
        token.allowed_models = ["gpt-4o"]
        await session.flush()

    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {seeded['token']}"},
        json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Void-Token minting returns the one-time plaintext secret (regression: the
# response model requires a `token` field the ORM row does not carry).
# --------------------------------------------------------------------------- #


async def test_create_my_token_returns_plaintext_secret(client, seeded):
    resp = await client.post("/api/me/tokens", headers=_session_headers(), json={"name": "laptop"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "laptop"
    assert body["token"].startswith("vs-")
    assert body["token_prefix"]


async def test_rotate_my_token_returns_new_secret(client, seeded):
    resp = await client.post(
        f"/api/me/tokens/{seeded['token_id']}/rotate", headers=_session_headers()
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["token"].startswith("vs-")


async def test_admin_create_token_returns_secret(client, seeded):
    resp = await client.post(
        "/api/admin/tokens", headers=_session_headers(), json={"name": "service"}
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["token"].startswith("vs-")


# --------------------------------------------------------------------------- #
# Upstream key management: inline ``# comment`` descriptions, listing, editing.
# --------------------------------------------------------------------------- #


async def test_add_keys_parses_inline_comment(client, seeded):
    pid = seeded["provider_id"]
    resp = await client.post(
        f"/api/admin/providers/{pid}/keys",
        headers=_session_headers(),
        json={"keys": ["sk-aaa111bbb # alice's key", "sk-ccc222ddd"], "pool": "members"},
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    by_preview = {k["note"]: k for k in created}
    # The line with a ``#`` carries its comment as the note; the bare line has none.
    assert "alice's key" in by_preview
    assert by_preview["alice's key"]["pool"] == "members"
    assert None in by_preview  # the comment-less key


async def test_add_keys_inline_comment_overrides_batch_note(client, seeded):
    pid = seeded["provider_id"]
    resp = await client.post(
        f"/api/admin/providers/{pid}/keys",
        headers=_session_headers(),
        json={"keys": ["sk-zzz999 # specific", "sk-yyy888"], "note": "batch"},
    )
    assert resp.status_code == 201, resp.text
    notes = sorted((k["note"] or "") for k in resp.json())
    assert notes == ["batch", "specific"]


async def test_list_keys_returns_saved_keys(client, seeded):
    pid = seeded["provider_id"]
    resp = await client.get(
        f"/api/admin/providers/{pid}/keys", headers=_session_headers()
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert any(k["id"] == seeded["key_id"] for k in rows)


async def test_update_key_edits_comment_pool_and_secret(client, seeded):
    pid, kid = seeded["provider_id"], seeded["key_id"]
    resp = await client.patch(
        f"/api/admin/providers/{pid}/keys/{kid}",
        headers=_session_headers(),
        json={"key": "sk-rotated-9999", "note": "renamed", "pool": "leaked"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["note"] == "renamed"
    assert body["pool"] == "leaked"
    # The preview reflects the new secret material.
    assert body["key_preview"] == "sk-r…9999"


async def test_update_key_rejects_duplicate_secret(client, seeded):
    pid, kid = seeded["provider_id"], seeded["key_id"]
    await client.post(
        f"/api/admin/providers/{pid}/keys",
        headers=_session_headers(),
        json={"keys": ["sk-other-key-1234"]},
    )
    resp = await client.patch(
        f"/api/admin/providers/{pid}/keys/{kid}",
        headers=_session_headers(),
        json={"key": "sk-other-key-1234"},
    )
    assert resp.status_code == 409, resp.text


# --------------------------------------------------------------------------- #
# Audit trail: management actions are recorded, and the scope filter separates
# administrative actions from ordinary self-service ones.
# --------------------------------------------------------------------------- #


async def _audit_items(client, **query) -> list[dict]:
    resp = await client.get("/api/admin/logs/audit", headers=_session_headers(), params=query)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


async def test_admin_disable_token_is_audited(client, seeded):
    """Regression: disabling another user's token via the admin page now logs."""
    tid = seeded["token_id"]
    resp = await client.patch(
        f"/api/admin/tokens/{tid}", headers=_session_headers(), json={"enabled": False}
    )
    assert resp.status_code == 200, resp.text

    items = await _audit_items(client, action="token.update")
    assert items, "expected a token.update audit entry"
    entry = items[0]
    assert entry["scope"] == "admin"
    assert entry["target_type"] == "token"
    assert entry["target_id"] == str(tid)
    assert entry["detail"]["changes"] == {"enabled": False}


async def test_self_service_token_ops_are_audited_with_self_scope(client, seeded):
    resp = await client.post(
        "/api/me/tokens", headers=_session_headers(), json={"name": "laptop"}
    )
    assert resp.status_code == 201, resp.text

    items = await _audit_items(client, action="me.token.create")
    assert items, "expected a me.token.create audit entry"
    assert items[0]["scope"] == "self"


async def test_audit_scope_filter_excludes_self_actions(client, seeded):
    # One admin action and one self-service action.
    tid = seeded["token_id"]
    await client.patch(
        f"/api/admin/tokens/{tid}", headers=_session_headers(), json={"enabled": False}
    )
    await client.post("/api/me/tokens", headers=_session_headers(), json={"name": "phone"})

    admin_only = await _audit_items(client, scope="admin")
    assert admin_only, "expected at least one admin-scoped entry"
    assert all(item["scope"] == "admin" for item in admin_only)
    assert not any(item["action"].startswith("me.") for item in admin_only)


async def test_audit_filter_by_target_type_and_action(client, seeded):
    tid = seeded["token_id"]
    await client.patch(
        f"/api/admin/tokens/{tid}", headers=_session_headers(), json={"enabled": False}
    )
    by_type = await _audit_items(client, target_type="token")
    assert by_type, "expected token-targeted entries"
    assert all(item["target_type"] == "token" for item in by_type)

    by_action = await _audit_items(client, action="token.update")
    assert by_action
    assert all(item["action"] == "token.update" for item in by_action)


async def test_audit_filter_options_endpoint(client, seeded):
    tid = seeded["token_id"]
    await client.patch(
        f"/api/admin/tokens/{tid}", headers=_session_headers(), json={"enabled": False}
    )
    resp = await client.get("/api/admin/logs/audit/filters", headers=_session_headers())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "token.update" in body["actions"]
    assert "admin" in body["scopes"]
    assert "token" in body["target_types"]
    assert any(a["sub"] == "user-1" for a in body["actors"])


async def test_token_create_stores_revealable_secret(client, seeded):
    """The minted Void-Token plaintext is kept as owner-revealable sensitive data."""
    resp = await client.post(
        "/api/me/tokens", headers=_session_headers(), json={"name": "revealable"}
    )
    assert resp.status_code == 201, resp.text
    secret = resp.json()["token"]

    items = await _audit_items(client, action="me.token.create")
    assert items, "expected a me.token.create audit entry"
    entry = items[0]
    assert entry["has_sensitive"] is True

    reveal = await client.post(
        f"/api/admin/logs/audit/{entry['id']}/reveal", headers=_session_headers()
    )
    assert reveal.status_code == 200, reveal.text
    assert reveal.json()["sensitive"]["token"] == secret


# --------------------------------------------------------------------------- #
# One-line OpenCode installer (curl | bash / irm | iex)
# --------------------------------------------------------------------------- #


async def test_install_sh_is_bash_with_gateway(client):
    resp = await client.get("/install.sh")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/x-shellscript")
    body = resp.text
    assert body.startswith("#!/usr/bin/env bash")
    assert "https://opencode.ai/config.json" in body
    # Deep integration: downloads the plugin and stores the token in the auth store.
    assert "/opencode/voidswitch.ts" in body
    assert "voidswitch.plugin.ts" in body
    assert "auth.json" in body
    assert "@ai-sdk/anthropic" in body  # provider registered (Anthropic dialect)
    assert "http://test" in body  # gateway derived from the request


async def test_install_ps1_is_powershell(client):
    resp = await client.get("/install.ps1")
    assert resp.status_code == 200
    body = resp.text
    assert "ConvertTo-Json" in body
    assert "Invoke-WebRequest" in body
    assert "/opencode/voidswitch.ts" in body
    assert "voidswitch.plugin.ts" in body
    assert "http://test" in body  # gateway derived from the request


async def test_opencode_plugin_source_is_served(client):
    resp = await client.get("/opencode/voidswitch.ts")
    assert resp.status_code == 200
    assert "typescript" in resp.headers["content-type"]
    body = resp.text
    # The real plugin source, not a stub.
    assert "output_config" in body and "VoidSwitchPlugin" in body


async def test_install_user_agent_sniff(client):
    bash = await client.get("/install", headers={"user-agent": "curl/8.4.0"})
    assert "#!/usr/bin/env bash" in bash.text

    ps = await client.get(
        "/install",
        headers={"user-agent": "Mozilla/5.0 (Windows NT 10.0) PowerShell/7.4.0"},
    )
    assert "$ErrorActionPreference" in ps.text


def _run_install_python(tmp_path, *, token, model="claude-opus-4-8", small_model=""):
    """Execute the install script's embedded python merge block against temp files."""
    import json
    import sys

    from voidswitch.api.install import _BASH

    # Extract Python block: after <<'PY' and before \nPY\n
    start_marker = "<<'PY'"
    start_idx = _BASH.index(start_marker)
    # Skip to the newline after the marker
    after_marker = _BASH.index("\n", start_idx) + 1
    end_marker = "\nPY\n"
    end_idx = _BASH.index(end_marker, after_marker)
    py = _BASH[after_marker:end_idx]
    py = py.replace("__MODEL__", model).replace("__SMALL_MODEL__", small_model)
    config = tmp_path / "opencode.json"
    auth = tmp_path / "auth.json"
    plugin = tmp_path / "voidswitch.plugin.ts"
    argv = ["-", str(config), str(auth), str(plugin), "http://gw:8080", token]
    saved = sys.argv
    sys.argv = argv
    try:
        exec(compile(py, "<install-py>", "exec"), {"__name__": "__main__"})
    finally:
        sys.argv = saved
    cfg = json.loads(config.read_text())
    auth_data = json.loads(auth.read_text()) if auth.exists() else None
    return cfg, auth_data, str(plugin)


def test_install_python_merge_wires_plugin_and_auth(tmp_path):
    cfg, auth_data, plugin = _run_install_python(tmp_path, token="vs-abc123token")
    assert cfg["$schema"] == "https://opencode.ai/config.json"
    assert cfg["model"] == "voidswitch/claude-opus-4-8"
    assert cfg["plugin"] == [plugin]  # plain absolute-path entry
    vs = cfg["provider"]["voidswitch"]
    # Full provider block so OpenCode registers it (and it shows in /connect).
    assert vs["npm"] == "@ai-sdk/anthropic"
    assert vs["name"] == "VoidSwitch"
    assert vs["options"]["baseURL"] == "http://gw:8080/v1"
    assert "apiKey" not in vs["options"]  # no apiKey leak → loader path is used
    assert "claude-opus-4-8" in vs["models"]  # models REQUIRED or provider is dropped
    # Token lands in the auth store (where the plugin loader can read it).
    assert auth_data == {"voidswitch": {"type": "api", "key": "vs-abc123token"}}
    # No small_model when not specified.
    assert "small_model" not in cfg


def test_install_python_merge_sets_small_model(tmp_path):
    cfg, _, _ = _run_install_python(tmp_path, token="", small_model="claude-haiku-4-5-20251001")
    assert cfg["model"] == "voidswitch/claude-opus-4-8"
    assert cfg["small_model"] == "voidswitch/claude-haiku-4-5-20251001"
    vs = cfg["provider"]["voidswitch"]
    assert "claude-opus-4-8" in vs["models"]
    assert "claude-haiku-4-5-20251001" in vs["models"]


def test_install_python_merge_custom_model(tmp_path):
    cfg, _, _ = _run_install_python(tmp_path, token="", model="claude-sonnet-4-6")
    assert cfg["model"] == "voidswitch/claude-sonnet-4-6"
    vs = cfg["provider"]["voidswitch"]
    assert "claude-sonnet-4-6" in vs["models"]


def test_install_python_merge_is_idempotent_and_dedupes(tmp_path):
    # Running twice must not duplicate the plugin entry, and no token => no auth file.
    _run_install_python(tmp_path, token="")
    cfg, auth_data, plugin = _run_install_python(tmp_path, token="")
    assert cfg["plugin"] == [plugin]  # deduped, not [plugin, plugin]
    assert auth_data is None


async def test_install_embeds_valid_token(client):
    resp = await client.get("/install.sh", params={"token": "vs-abcdEFGH1234"})
    assert "vs-abcdEFGH1234" in resp.text


async def test_install_rejects_malformed_token(client):
    # A value that isn't a vs- token must never be echoed into the script.
    resp = await client.get("/install.sh", params={"token": "$(rm -rf /)"})
    assert "rm -rf" not in resp.text
    assert 'TOKEN="${VOIDSWITCH_TOKEN:-}"' in resp.text


async def _seed_request_logs(db) -> None:
    from voidswitch.models.db import RequestLog, User

    async with db.session() as session:
        session.add(User(sub="user-2", username="bob", email="b@example.com", role="member"))
        rows = [
            # alice (owner) — two calls on token 1.
            RequestLog(
                user_sub="user-1", token_id=1, model="deepseek-chat",
                success=True, prompt_tokens=5, completion_tokens=2, total_tokens=7,
            ),
            RequestLog(
                user_sub="user-1", token_id=1, model="deepseek-chat",
                success=False, prompt_tokens=3, completion_tokens=0, total_tokens=3,
            ),
            # bob (member) — one call on token 2.
            RequestLog(
                user_sub="user-2", token_id=2, model="gpt-4o",
                success=True, prompt_tokens=10, completion_tokens=4, total_tokens=14,
            ),
        ]
        for r in rows:
            session.add(r)


async def test_usage_analytics_staff_sees_everything(client, db, seeded):
    await _seed_request_logs(db)
    resp = await client.get("/api/usage", headers=_session_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"] == "all"
    assert body["totals"]["requests"] == 3
    assert body["totals"]["success"] == 2
    assert body["totals"]["failures"] == 1
    assert body["totals"]["total_tokens"] == 24
    # Time-series buckets are present (all three calls land in today's bucket).
    assert sum(b["requests"] for b in body["daily"]) == 3
    assert sum(b["requests"] for b in body["yearly"]) == 3
    # Both users and both tokens appear in the breakdowns.
    assert {r["key"] for r in body["by_user"]} == {"user-1", "user-2"}
    assert {r["key"] for r in body["by_token"]} == {"1", "2"}
    assert {r["key"] for r in body["by_model"]} == {"deepseek-chat", "gpt-4o"}


async def test_usage_analytics_member_sees_only_self(client, db, seeded):
    await _seed_request_logs(db)
    resp = await client.get(
        "/api/usage", headers=_session_headers(sub="user-2", role="member", name="bob")
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"] == "self"
    assert body["totals"]["requests"] == 1
    assert body["totals"]["total_tokens"] == 14
    assert {r["key"] for r in body["by_user"]} == {"user-2"}
    assert {r["key"] for r in body["by_token"]} == {"2"}
    assert {r["key"] for r in body["by_model"]} == {"gpt-4o"}


# --------------------------------------------------------------------------- #
# Log retention cleanup task
# --------------------------------------------------------------------------- #


async def test_log_cleanup_deletes_only_old_rows(db, seeded):
    """The retention task drops rows older than the window and audits the sweep."""
    import datetime as dt

    from sqlalchemy import func, select
    from voidswitch.models.db import AuditLog, RequestLog
    from voidswitch.services import settings_store
    from voidswitch.tasks.log_cleanup import run_log_cleanup

    old = dt.datetime.now(dt.UTC) - dt.timedelta(days=40)
    fresh = dt.datetime.now(dt.UTC)
    async with db.session() as session:
        session.add(RequestLog(user_sub="user-1", model="m", success=True, ts=old))
        session.add(RequestLog(user_sub="user-1", model="m", success=True, ts=fresh))
        session.add(AuditLog(action="x.old", scope="admin", ts=old))
        session.add(AuditLog(action="x.fresh", scope="admin", ts=fresh))
        # Enable a 30-day retention for both log kinds.
        await settings_store.update(
            session,
            {"request_log_retention_days": 30, "audit_log_retention_days": 30},
        )

    await run_log_cleanup()

    async with db.session() as session:
        req = (await session.execute(select(func.count(RequestLog.id)))).scalar_one()
        # One fresh request log survives.
        assert req == 1
        # The old audit row is gone, the fresh one and the new logs.cleanup remain.
        actions = (await session.execute(select(AuditLog.action))).scalars().all()
        assert "x.old" not in actions
        assert "x.fresh" in actions
        assert "logs.cleanup" in actions

    # Reset cache so other tests see defaults again.
    async with db.session() as session:
        await settings_store.update(
            session,
            {"request_log_retention_days": 0, "audit_log_retention_days": 0},
        )
