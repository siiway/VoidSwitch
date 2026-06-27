"""Tests for the per-provider key-management API + its credential lifecycle."""

from __future__ import annotations

import pytest
from voidswitch.core.config import get_settings
from voidswitch.core.security import create_session_token

pytestmark = pytest.mark.asyncio


def _session_headers(role: str = "owner") -> dict[str, str]:
    token = create_session_token(
        secret=get_settings().server.secret_key,
        subject="user-1",
        extra={"role": role, "name": "alice"},
    )
    return {"Authorization": f"Bearer {token}"}


async def _enable(client, pid: int) -> str:
    resp = await client.post(
        f"/api/admin/providers/{pid}/key-api/enable", headers=_session_headers()
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enabled"] is True
    assert body["token"].startswith("vsk-")
    return body["token"]


# --------------------------------------------------------------------------- #
# Credential lifecycle (owner-only)
# --------------------------------------------------------------------------- #


async def test_provider_has_uuid(client, seeded):
    resp = await client.get("/api/admin/providers", headers=_session_headers())
    assert resp.status_code == 200, resp.text
    provider = next(p for p in resp.json() if p["id"] == seeded["provider_id"])
    assert provider["uuid"]
    assert provider["key_api_enabled"] is False


async def test_enable_rotate_reveal_disable(client, seeded):
    pid = seeded["provider_id"]
    token = await _enable(client, pid)

    # Reveal returns the same plaintext.
    resp = await client.post(
        f"/api/admin/providers/{pid}/key-api/reveal", headers=_session_headers()
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["token"] == token

    # Rotate mints a new, different token; the old one stops working.
    resp = await client.post(
        f"/api/admin/providers/{pid}/key-api/rotate", headers=_session_headers()
    )
    rotated = resp.json()["token"]
    assert rotated != token
    old = await client.get("/provider-api/keys", headers={"Authorization": f"Bearer {token}"})
    assert old.status_code == 401

    # Disable revokes everything.
    resp = await client.post(
        f"/api/admin/providers/{pid}/key-api/disable", headers=_session_headers()
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["enabled"] is False
    dead = await client.get(
        "/provider-api/keys", headers={"Authorization": f"Bearer {rotated}"}
    )
    assert dead.status_code == 401
    # Reveal now fails (nothing to reveal).
    resp = await client.post(
        f"/api/admin/providers/{pid}/key-api/reveal", headers=_session_headers()
    )
    assert resp.status_code == 400


async def test_key_api_requires_owner(client, db, seeded):
    from voidswitch.models.db import User

    async with db.session() as session:
        session.add(User(sub="user-admin", username="bob", role="admin"))

    pid = seeded["provider_id"]
    headers = {
        "Authorization": "Bearer "
        + create_session_token(
            secret=get_settings().server.secret_key,
            subject="user-admin",
            extra={"role": "admin", "name": "bob"},
        )
    }
    resp = await client.post(
        f"/api/admin/providers/{pid}/key-api/enable", headers=headers
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Key management through the mounted sub-app
# --------------------------------------------------------------------------- #


async def test_subapp_requires_token(client, seeded):
    resp = await client.get("/provider-api/keys")
    assert resp.status_code == 401


async def test_subapp_crud_and_isolation(client, seeded):
    pid = seeded["provider_id"]
    token = await _enable(client, pid)
    hdr = {"Authorization": f"Bearer {token}"}

    # whoami returns the managed provider.
    resp = await client.get("/provider-api/provider", headers=hdr)
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == pid
    # The management credential state is never echoed back.
    assert resp.json()["key_api_enabled"] is False

    # List (seeded key present).
    resp = await client.get("/provider-api/keys", headers=hdr)
    assert resp.status_code == 200, resp.text
    assert any(k["id"] == seeded["key_id"] for k in resp.json())

    # Create via X-API-Key header, with inline comment + pool.
    resp = await client.post(
        "/provider-api/keys",
        headers={"X-API-Key": token},
        json={"keys": ["sk-new-aaa111 # via api", "sk-new-bbb222"], "pool": "members"},
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert len(created) == 2
    by_note = {k["note"]: k for k in created}
    assert by_note["via api"]["pool"] == "members"
    new_id = created[0]["id"]

    # Edit: disable it.
    resp = await client.patch(
        f"/provider-api/keys/{new_id}", headers=hdr, json={"enabled": False}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "disabled"

    # Delete it.
    resp = await client.delete(f"/provider-api/keys/{new_id}", headers=hdr)
    assert resp.status_code == 204, resp.text


async def test_key_reorder(client, seeded):
    pid = seeded["provider_id"]
    # Add two more keys (they append after the seeded one).
    resp = await client.post(
        f"/api/admin/providers/{pid}/keys",
        headers=_session_headers(),
        json={"keys": ["sk-aaa111", "sk-bbb222"]},
    )
    assert resp.status_code == 201, resp.text
    new_ids = [k["id"] for k in resp.json()]
    seeded_id = seeded["key_id"]

    # Default order is insertion order (seeded first, then the two new keys).
    resp = await client.get(
        f"/api/admin/providers/{pid}/keys", headers=_session_headers()
    )
    assert [k["id"] for k in resp.json()] == [seeded_id, *new_ids]

    # Reorder: put the last key first.
    new_order = [new_ids[1], seeded_id, new_ids[0]]
    resp = await client.post(
        f"/api/admin/providers/{pid}/keys/reorder",
        headers=_session_headers(),
        json={"order": new_order},
    )
    assert resp.status_code == 200, resp.text
    assert [k["id"] for k in resp.json()] == new_order
    assert [k["sort_order"] for k in resp.json()] == [0, 1, 2]

    # The new order persists on a fresh list.
    resp = await client.get(
        f"/api/admin/providers/{pid}/keys", headers=_session_headers()
    )
    assert [k["id"] for k in resp.json()] == new_order

    # A partial order list appends the omitted keys after the listed ones.
    resp = await client.post(
        f"/api/admin/providers/{pid}/keys/reorder",
        headers=_session_headers(),
        json={"order": [seeded_id]},
    )
    assert resp.status_code == 200, resp.text
    assert next(k["id"] for k in resp.json()) == seeded_id

    # Unknown id is rejected.
    resp = await client.post(
        f"/api/admin/providers/{pid}/keys/reorder",
        headers=_session_headers(),
        json={"order": [999999]},
    )
    assert resp.status_code == 404


async def test_provider_key_select_mode(client, seeded):
    pid = seeded["provider_id"]
    # Default mode is round-robin.
    resp = await client.get("/api/admin/providers", headers=_session_headers())
    provider = next(p for p in resp.json() if p["id"] == pid)
    assert provider["key_select_mode"] == "round_robin"

    # Update to a valid mode.
    resp = await client.patch(
        f"/api/admin/providers/{pid}",
        headers=_session_headers(),
        json={"key_select_mode": "pinned_random"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["key_select_mode"] == "pinned_random"

    # Reject an unknown mode.
    resp = await client.patch(
        f"/api/admin/providers/{pid}",
        headers=_session_headers(),
        json={"key_select_mode": "nonsense"},
    )
    assert resp.status_code == 422


async def test_subapp_cleanup_targets(client, seeded):
    pid = seeded["provider_id"]
    token = await _enable(client, pid)
    hdr = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        "/provider-api/keys/cleanup",
        headers=hdr,
        json={"target": "not-a-status"},
    )
    assert resp.status_code == 400

    resp = await client.post(
        "/provider-api/keys/cleanup",
        headers=hdr,
        json={"target": "invalid"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] == 0


async def test_subapp_has_own_docs(client, seeded):
    resp = await client.get("/provider-api/openapi.json")
    assert resp.status_code == 200, resp.text
    schema = resp.json()
    assert "/keys" in schema["paths"]
    assert "/keys/cleanup" in schema["paths"]


# --------------------------------------------------------------------------- #
# Provider rename
# --------------------------------------------------------------------------- #


async def test_provider_rename(client, seeded):
    pid = seeded["provider_id"]
    resp = await client.patch(
        f"/api/admin/providers/{pid}",
        headers=_session_headers(),
        json={"name": "deepseek-renamed"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "deepseek-renamed"


async def test_provider_rename_conflict(client, seeded):
    # Create a second provider, then try to rename it onto the seeded name.
    resp = await client.post(
        "/api/admin/providers",
        headers=_session_headers(),
        json={"name": "other", "type": "openai"},
    )
    assert resp.status_code == 201, resp.text
    other_id = resp.json()["id"]
    resp = await client.patch(
        f"/api/admin/providers/{other_id}",
        headers=_session_headers(),
        json={"name": "deepseek"},
    )
    assert resp.status_code == 409
