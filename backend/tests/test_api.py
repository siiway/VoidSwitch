"""End-to-end API tests through the ASGI app."""

from __future__ import annotations

import httpx
import pytest
import respx
from voidswitch.core.config import get_settings
from voidswitch.core.security import create_session_token

pytestmark = pytest.mark.asyncio


def _session_headers(
    sub: str = "user-1",
    role: str = "owner",
    name: str = "alice",
    headers: dict[str, str] | None = None,
) -> dict[str, str]:
    """Dashboard session JWT for the seeded user (sub ``user-1``)."""
    token = create_session_token(
        secret=get_settings().server.secret_key,
        subject=sub,
        extra={"role": role, "name": name},
    )
    return {"Authorization": f"Bearer {token}", **(headers or {})}


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
    # Providers breakdown mirrors the model grouping (no provider recorded on
    # these seeded rows, so they all fall under one "(unknown)" bucket).
    assert {r["label"] for r in body["by_provider"]} == {"(unknown)"}
    # Performance aggregates: TTFT only counts streamed successes, and the
    # seeded rows have no started/finished timestamps → no latency/TTFT values.
    perf = body["performance"]
    assert perf["avg_first_token_ms"] is None
    assert perf["avg_latency_ms"] is None
    assert perf["avg_tokens_per_request"] == 8.0  # 24 tokens / 3 requests
    assert perf["stream_requests"] == 0
    assert perf["non_stream_requests"] == 3
    # Status-code distribution: unset status codes are excluded.
    assert body["status_codes"] == []


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


async def _seed_internal_and_dated_logs(db) -> None:
    """Seed an internal Claude-Code token-op row and a stale (old) request."""
    import datetime as dt

    from voidswitch.models.db import RequestLog

    async with db.session() as session:
        # Internal token exchange: no user, no token, synthetic model.
        session.add(
            RequestLog(
                user_sub=None, token_id=None, model="<cc-exchange-token>",
                success=True, prompt_tokens=0, completion_tokens=0, total_tokens=0,
            )
        )
        # A real request from a year ago (outside a "recent" window).
        session.add(
            RequestLog(
                user_sub="user-1", token_id=1, model="deepseek-chat",
                success=True, prompt_tokens=1, completion_tokens=1, total_tokens=2,
                ts=dt.datetime.now(dt.UTC) - dt.timedelta(days=365),
            )
        )


async def test_usage_excludes_internal_model_and_relabels(client, db, seeded):
    await _seed_request_logs(db)
    await _seed_internal_and_dated_logs(db)
    resp = await client.get("/api/usage", headers=_session_headers())
    assert resp.status_code == 200
    body = resp.json()
    # The synthetic <cc-…-token> model is dropped from the model breakdown.
    assert "<cc-exchange-token>" not in {r["label"] for r in body["by_model"]}
    assert all(not r["key"].startswith("<cc-") for r in body["by_model"])
    # The caller-less internal row is grouped under a single "<internal>" entry
    # in both the user and token breakdowns.
    internal_users = [r for r in body["by_user"] if r["key"] == ""]
    internal_tokens = [r for r in body["by_token"] if r["key"] == ""]
    assert internal_users and internal_users[0]["label"] == "<internal>"
    assert internal_tokens and internal_tokens[0]["label"] == "<internal>"


async def test_usage_time_window_scopes_totals(client, db, seeded):
    await _seed_request_logs(db)
    await _seed_internal_and_dated_logs(db)
    import datetime as dt

    # A tight window around "now" excludes the year-old request.
    start = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)).isoformat()
    resp = await client.get(
        "/api/usage",
        params={"start": start},
        headers=_session_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    # 3 seeded "today" rows + 1 internal today row = 4; the year-old row excluded.
    assert body["totals"]["requests"] == 4


async def test_usage_mode_b_returns_windowed_series(client, db, seeded):
    await _seed_request_logs(db)
    import datetime as dt

    start = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=6)).isoformat()
    end = (dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)).isoformat()
    resp = await client.get(
        "/api/usage",
        params={"start": start, "end": end, "time_mode": "B"},
        headers=_session_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    # Mode B fills a single windowed series (hourly for a <2-day span) and leaves
    # the trailing daily/weekly/... arrays empty.
    assert body["windowed_granularity"] == "hour"
    assert body["windowed_series"] is not None
    assert sum(b["requests"] for b in body["windowed_series"]) == 3
    assert body["daily"] == []


async def test_admin_stats_24h_metrics(client, db, seeded):
    """The dashboard 24h stats include success rate, average TTFT, and average
    tokens per request — and a streamed request with a recorded TTFT feeds the
    average."""
    from voidswitch.models.db import RequestLog

    async with db.session() as session:
        session.add(
            RequestLog(
                user_sub="user-1", token_id=1, model="deepseek-chat",
                success=True, stream=True, first_token_ms=250.0,
                prompt_tokens=10, completion_tokens=20, total_tokens=30,
            )
        )
        session.add(
            RequestLog(
                user_sub="user-1", token_id=1, model="deepseek-chat",
                success=True, stream=False, first_token_ms=None,
                prompt_tokens=5, completion_tokens=5, total_tokens=10,
            )
        )
        session.add(
            RequestLog(
                user_sub="user-1", token_id=1, model="deepseek-chat",
                success=False, stream=False,
                prompt_tokens=0, completion_tokens=0, total_tokens=0,
            )
        )

    resp = await client.get("/api/admin/stats", headers=_session_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["requests_24h"] == 3
    assert body["success_24h"] == 2
    assert body["success_rate_24h"] == pytest.approx(66.7, abs=0.1)
    assert body["avg_first_token_ms_24h"] == pytest.approx(250.0)
    assert body["avg_tokens_per_request_24h"] == pytest.approx(40 / 3, abs=0.1)


# --------------------------------------------------------------------------- #
# Live request-log stream (SSE)
# --------------------------------------------------------------------------- #


async def test_request_log_stream_pushes_new_rows(db, seeded):
    """The live-log stream emits newly written request-log rows matching the
    requested filters."""
    import asyncio
    import json as _json

    from voidswitch.api.admin.logs import (
        _request_log_filters,
        _stream_request_log_events,
    )
    from voidswitch.models.db import RequestLog

    async with db.session() as session:
        session.add(RequestLog(user_sub="user-1", model="deepseek-chat", success=True))
        await session.commit()

    owner = await _load_user(db, "user-1")
    filters = _request_log_filters(owner, model="deepseek-chat")
    events = _stream_request_log_events(db, filters, "user-1", poll_seconds=0.05)

    # The pre-existing matching row is pushed immediately.
    first = await asyncio.wait_for(events.__anext__(), timeout=2)
    payload = _json.loads(first[len("data: "):])
    assert payload["model"] == "deepseek-chat"

    # A new row written while the stream is open is picked up on the next poll.
    async with db.session() as session:
        session.add(RequestLog(user_sub="user-1", model="deepseek-chat", success=True))
        await session.commit()
    second = await asyncio.wait_for(events.__anext__(), timeout=2)
    payload = _json.loads(second[len("data: "):])
    assert payload["model"] == "deepseek-chat"

    await events.aclose()


async def test_request_log_stream_scopes_members_and_honours_filters(db, seeded):
    """The stream honours server-side filters: a non-matching model is never
    pushed, and member traffic is scoped to the caller."""
    import asyncio
    import json as _json

    from voidswitch.api.admin.logs import (
        _request_log_filters,
        _stream_request_log_events,
    )
    from voidswitch.models.db import RequestLog

    async with db.session() as session:
        session.add(RequestLog(user_sub="user-2", model="gpt-4o", success=True))
        session.add(RequestLog(user_sub="user-1", model="deepseek-chat", success=True))
        await session.commit()

    owner = await _load_user(db, "user-1")
    # Staff filters: model=deepseek-chat → only that row is pushed.
    filters = _request_log_filters(owner, model="deepseek-chat")
    events = _stream_request_log_events(db, filters, "user-1", poll_seconds=0.05)
    first = await asyncio.wait_for(events.__anext__(), timeout=2)
    payload = _json.loads(first[len("data: "):])
    assert payload["model"] == "deepseek-chat"
    await events.aclose()

    # A non-matching row written while streaming is NOT pushed.
    events = _stream_request_log_events(db, filters, "user-1", poll_seconds=0.05)
    async with db.session() as session:
        session.add(RequestLog(user_sub="user-1", model="gpt-4o", success=True))
        await session.commit()
    # Wait one poll cycle, then a matching row; only the matching one arrives.
    await asyncio.sleep(0.15)
    async with db.session() as session:
        session.add(RequestLog(user_sub="user-1", model="deepseek-chat", success=True))
        await session.commit()
    got = await asyncio.wait_for(events.__anext__(), timeout=2)
    payload = _json.loads(got[len("data: "):])
    assert payload["model"] == "deepseek-chat"
    await events.aclose()


async def test_request_log_stream_enforces_per_user_limit(client, db, seeded):
    """More than ``log_stream_max_connections`` concurrent streams for one user
    are rejected with 429."""
    from voidswitch.api.admin.logs import _acquire_stream_slot, _release_stream_slot
    from voidswitch.services import settings_store

    async with db.session() as session:
        await settings_store.update(session, {"log_stream_max_connections": 1})

    # Fill the single slot; the endpoint then rejects a second connection with
    # 429 (returned before streaming starts, so a plain GET works).
    await _acquire_stream_slot("user-1", 1)
    resp = await client.get(
        "/api/admin/logs/requests/stream",
        headers=_session_headers(),
    )
    assert resp.status_code == 429

    # Release the slot → a new slot is acquirable again.
    await _release_stream_slot("user-1")
    await _acquire_stream_slot("user-1", 1)
    await _release_stream_slot("user-1")

    # Reset so other tests see the default.
    async with db.session() as session:
        await settings_store.update(session, {"log_stream_max_connections": 2})


async def _load_user(db, sub):
    from sqlalchemy import select as _select
    from voidswitch.models.db import User

    async with db.session() as session:
        return (
            await session.execute(_select(User).where(User.sub == sub))
        ).scalar_one()


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


# --------------------------------------------------------------------------- #
# Activity heatmap
# --------------------------------------------------------------------------- #


async def _seed_heatmap(db) -> None:
    """Seed daily rollups + a session span for two users across recent days."""
    import datetime as dt

    from voidswitch.models.db import SessionSpan, UsageDaily, User

    today = dt.datetime.now(dt.UTC).date()

    def day(offset: int) -> str:
        return (today - dt.timedelta(days=offset)).strftime("%Y-%m-%d")

    async with db.session() as session:
        session.add(User(sub="user-2", username="bob", email="b@example.com", role="member"))
        # alice: today + yesterday (a 2-day streak), peak 100.
        session.add(UsageDaily(user_sub="user-1", day=day(0), tokens=100, requests=4))
        session.add(UsageDaily(user_sub="user-1", day=day(1), tokens=50, requests=2))
        # bob: today only, 30 tokens.
        session.add(UsageDaily(user_sub="user-2", day=day(0), tokens=30, requests=1))
        # A ~1h session span for alice → longest task duration.
        now = dt.datetime.now(dt.UTC)
        session.add(
            SessionSpan(
                session_key="t1:sid:s1",
                user_sub="user-1",
                started_at=now - dt.timedelta(hours=1),
                last_at=now,
                requests=4,
            )
        )


async def test_heatmap_bundle_staff_sees_site_and_personal(client, db, seeded):
    await _seed_heatmap(db)
    resp = await client.get("/api/usage/heatmap", headers=_session_headers())
    assert resp.status_code == 200
    body = resp.json()

    personal = body["personal"]
    assert personal["scope"] == "self"
    assert personal["stats"]["cumulative_tokens"] == 150
    assert personal["stats"]["peak_tokens"] == 100
    assert personal["stats"]["current_streak"] == 2
    assert personal["stats"]["longest_streak"] == 2
    # ~1h task span, allow a little slack around the boundary.
    assert 3500 <= personal["stats"]["longest_task_seconds"] <= 3700
    assert personal["retention_days"] == 365

    site = body["site"]
    assert site is not None
    assert site["scope"] == "site"
    # Site cumulative is alice (150) + bob (30).
    assert site["stats"]["cumulative_tokens"] == 180


async def test_heatmap_bundle_member_has_no_site(client, db, seeded):
    await _seed_heatmap(db)
    resp = await client.get(
        "/api/usage/heatmap",
        headers=_session_headers(sub="user-2", role="member", name="bob"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["site"] is None
    assert body["personal"]["stats"]["cumulative_tokens"] == 30


async def test_heatmap_for_user_is_staff_only(client, db, seeded):
    await _seed_heatmap(db)
    # Staff can inspect a specific user's heatmap (powers the stats popup).
    resp = await client.get(
        "/api/usage/heatmap/user", params={"sub": "user-1"}, headers=_session_headers()
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"] == "user"
    assert body["label"] == "alice#1"
    assert body["stats"]["cumulative_tokens"] == 150

    # Members may not view arbitrary users.
    denied = await client.get(
        "/api/usage/heatmap/user",
        params={"sub": "user-1"},
        headers=_session_headers(sub="user-2", role="member", name="bob"),
    )
    assert denied.status_code == 403


async def test_heatmap_retention_validation(client, seeded):
    """A non-zero heatmap retention below one year is rejected; 0/>=365 accepted."""
    too_short = await client.put(
        "/api/admin/settings",
        json={"values": {"heatmap_retention_days": 30}},
        headers=_session_headers(),
    )
    assert too_short.status_code == 400

    ok = await client.put(
        "/api/admin/settings",
        json={"values": {"heatmap_retention_days": 400}},
        headers=_session_headers(),
    )
    assert ok.status_code == 200


async def test_usage_rollup_records_daily_and_span(db, seeded):
    """record_usage upserts the daily rollup and the session span idempotently."""
    import datetime as dt

    from sqlalchemy import select
    from voidswitch.models.db import SessionSpan, UsageDaily
    from voidswitch.services import usage_rollup

    t0 = dt.datetime.now(dt.UTC)
    async with db.session() as session:
        await usage_rollup.record_usage(
            session, user_sub="user-1", session_key="t1:sid:x", tokens=10, ts=t0
        )
        await usage_rollup.record_usage(
            session,
            user_sub="user-1",
            session_key="t1:sid:x",
            tokens=5,
            ts=t0 + dt.timedelta(minutes=30),
        )

    async with db.session() as session:
        daily = (
            await session.execute(select(UsageDaily).where(UsageDaily.user_sub == "user-1"))
        ).scalars().all()
        assert len(daily) == 1
        assert daily[0].tokens == 15
        assert daily[0].requests == 2

        span = (
            await session.execute(select(SessionSpan).where(SessionSpan.session_key == "t1:sid:x"))
        ).scalar_one()
        assert span.requests == 2
        assert (span.last_at - span.started_at) >= dt.timedelta(minutes=29)


async def test_log_cleanup_prunes_heatmap_rollups(db, seeded):
    """Heatmap rollups older than heatmap_retention_days are pruned on cleanup."""
    import datetime as dt

    from sqlalchemy import func, select
    from voidswitch.models.db import SessionSpan, UsageDaily
    from voidswitch.services import settings_store
    from voidswitch.tasks.log_cleanup import run_log_cleanup

    today = dt.datetime.now(dt.UTC)
    old_day = (today - dt.timedelta(days=400)).strftime("%Y-%m-%d")
    fresh_day = today.strftime("%Y-%m-%d")
    async with db.session() as session:
        session.add(UsageDaily(user_sub="user-1", day=old_day, tokens=1, requests=1))
        session.add(UsageDaily(user_sub="user-1", day=fresh_day, tokens=1, requests=1))
        session.add(
            SessionSpan(
                session_key="old",
                user_sub="user-1",
                started_at=today - dt.timedelta(days=400),
                last_at=today - dt.timedelta(days=400),
            )
        )
        session.add(
            SessionSpan(
                session_key="fresh", user_sub="user-1", started_at=today, last_at=today
            )
        )
        await settings_store.update(session, {"heatmap_retention_days": 365})

    await run_log_cleanup()

    async with db.session() as session:
        days = (await session.execute(select(func.count(UsageDaily.id)))).scalar_one()
        spans = (await session.execute(select(func.count(SessionSpan.id)))).scalar_one()
        assert days == 1
        assert spans == 1

    # Reset cache so other tests see defaults again.
    async with db.session() as session:
        await settings_store.update(session, {"heatmap_retention_days": 365})


# --------------------------------------------------------------------------- #
# Log filters: request status class / exact / provider / model, and audit
# ip / user-agent substring + glob matching.
# --------------------------------------------------------------------------- #


async def test_request_log_filters_and_options(client, db, seeded):
    from voidswitch.models.db import RequestLog

    async with db.session() as session:
        session.add(
            RequestLog(
                user_sub="user-1", token_id=1, model="gpt-4o",
                provider_name="openai", status_code=200, success=True,
                client_ip="10.0.0.1",
            )
        )
        session.add(
            RequestLog(
                user_sub="user-1", token_id=1, model="deepseek-chat",
                provider_name="deepseek", status_code=404, success=False,
                client_ip="192.168.1.5",
            )
        )
        session.add(
            RequestLog(
                user_sub="user-1", token_id=1, model="deepseek-chat",
                provider_name="deepseek", status_code=429, success=False,
                client_ip="10.0.0.2",
            )
        )

    async def items(**params):
        r = await client.get(
            "/api/admin/logs/requests", headers=_session_headers(), params=params
        )
        assert r.status_code == 200, r.text
        return r.json()["items"]

    # A status *class* matches the whole range.
    assert {i["status_code"] for i in await items(status_code="4xx")} == {404, 429}
    # An exact status matches just that code.
    assert {i["status_code"] for i in await items(status_code="404")} == {404}
    # Provider + model are exact filters.
    only_openai = await items(provider="openai")
    assert all(i["provider_name"] == "openai" for i in only_openai)
    assert len(only_openai) == 1
    assert all(i["model"] == "deepseek-chat" for i in await items(model="deepseek-chat"))
    # Client IP: substring + glob matching (mirrors the audit log's IP filter).
    assert {i["client_ip"] for i in await items(client_ip="10.0.")} == {"10.0.0.1", "10.0.0.2"}
    assert {i["client_ip"] for i in await items(client_ip="10.0.0.2")} == {"10.0.0.2"}
    assert {i["client_ip"] for i in await items(client_ip="10.0.*")} == {"10.0.0.1", "10.0.0.2"}
    assert all(i["client_ip"] == "192.168.1.5" for i in await items(client_ip="192.168.*"))

    # The filter-options endpoint lists the distinct values present.
    r = await client.get("/api/admin/logs/requests/filters", headers=_session_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"gpt-4o", "deepseek-chat"} <= set(body["models"])
    assert {"openai", "deepseek"} <= set(body["providers"])
    assert any(a["sub"] == "user-1" for a in body["users"])


async def test_request_log_time_range_filter(client, db, seeded):
    import datetime as _dt

    from voidswitch.models.db import RequestLog

    base = _dt.datetime(2024, 1, 1, 12, 0, tzinfo=_dt.UTC)
    async with db.session() as session:
        for offset_h, model in ((-48, "old"), (-1, "recent"), (48, "future")):
            session.add(
                RequestLog(
                    user_sub="user-1", token_id=1, model=model,
                    provider_name="openai", status_code=200, success=True,
                    ts=base + _dt.timedelta(hours=offset_h),
                )
            )

    async def models(**params):
        r = await client.get(
            "/api/admin/logs/requests", headers=_session_headers(), params=params
        )
        assert r.status_code == 200, r.text
        return {i["model"] for i in r.json()["items"]}

    window = {"old", "recent", "future"}
    # `start` excludes everything strictly before it (inclusive lower bound).
    got = await models(start=(base - _dt.timedelta(hours=24)).isoformat())
    assert "old" not in got and {"recent", "future"} <= got
    # `end` excludes everything strictly after it (inclusive upper bound).
    got = await models(end=(base + _dt.timedelta(hours=24)).isoformat())
    assert "future" not in got and {"old", "recent"} <= got
    # A bounded window keeps only the middle record.
    got = await models(
        start=(base - _dt.timedelta(hours=24)).isoformat(),
        end=(base + _dt.timedelta(hours=24)).isoformat(),
    )
    assert got & window == {"recent"}


async def test_audit_ip_ua_substring_and_glob(client, db, seeded):
    from voidswitch.models.db import AuditLog

    async with db.session() as session:
        session.add(
            AuditLog(action="x.a", scope="admin", ip="10.0.0.1", user_agent="Mozilla/5.0 Chrome")
        )
        session.add(
            AuditLog(action="x.b", scope="admin", ip="192.168.1.5", user_agent="curl/8.0")
        )

    # Glob on IP (prefix).
    by_ip = await _audit_items(client, ip="10.0.*")
    assert by_ip and all(i["ip"].startswith("10.0.") for i in by_ip)
    # Plain substring on UA.
    by_ua = await _audit_items(client, user_agent="Chrome")
    assert by_ua and all("Chrome" in i["user_agent"] for i in by_ua)
    # Glob on UA.
    curl = await _audit_items(client, user_agent="curl/*")
    assert curl and all(i["user_agent"].startswith("curl/") for i in curl)


async def test_audit_user_agent_captured_from_request(client, db, seeded):
    """Audit rows record the caller's user-agent even when the call site only
    passes the session/ip — the request-session middleware exposes it as an
    ambient client context that ``record_audit`` falls back to."""
    from sqlalchemy import select as _select
    from voidswitch.models.db import AuditLog

    # An audit action that does NOT pass ``user_agent`` (e.g. AUTH_LOGOUT, or the
    # owner's reveal flow) must still capture the UA from the request context.
    await client.post("/api/auth/logout", headers=_session_headers(headers={"user-agent": "curl/8.4.0"}))

    async with db.session() as session:
        rows = (
            await session.execute(
                _select(AuditLog).where(AuditLog.action == "auth.logout")
            )
        ).scalars().all()
    assert rows, "expected an audit row for the logout"
    assert rows[0].user_agent == "curl/8.4.0"
    assert rows[0].ip is not None


async def test_daily_quota_enforced(client, db, seeded):
    """A token with a daily_quota is rejected once today's requests reach it."""
    from voidswitch.models.db import VoidToken

    async with db.session() as session:
        token = await session.get(VoidToken, seeded["token_id"])
        token.daily_quota = 1
        await session.flush()

    with respx.mock(assert_all_called=False) as mock:
        mock.post(DS_URL).mock(return_value=httpx.Response(200, json=OAI_RESPONSE))
        first = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {seeded['token']}"},
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert first.status_code == 200
        # The first request is logged, so the second is over the daily quota.
        second = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {seeded['token']}"},
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert second.status_code == 429
    assert "Daily request quota" in second.json()["detail"]


async def test_malformed_messages_rejected_400(client, seeded):
    """A request body whose ``messages`` is not a list is a client error (400),
    not a translator crash (500)."""
    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {seeded['token']}"},
        json={"model": "deepseek-chat", "messages": "not-a-list"},
    )
    assert resp.status_code == 400
