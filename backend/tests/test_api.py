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


def _run_install_python(tmp_path, *, token):
    """Execute the install script's embedded python merge block against temp files."""
    import json
    import sys

    from voidswitch.api.install import _BASH

    py = _BASH.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
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
