"""Models catalog: listing, metadata edits, sync, and /v1/models enrichment."""

from __future__ import annotations

import httpx
import pytest
import respx
from voidswitch.core.config import get_settings
from voidswitch.core.security import (
    create_session_token,
    generate_void_token,
    hash_token,
    token_fingerprint,
)
from voidswitch.models.db import User, VoidToken

pytestmark = pytest.mark.asyncio


async def _member_token(db) -> str:
    """A Void-Token owned by a plain member."""
    plaintext = generate_void_token()
    async with db.session() as session:
        user = User(sub="tok-member", username="carol", email="c@example.com", role="member")
        session.add(user)
        await session.flush()
        session.add(
            VoidToken(
                user_id=user.id,
                name="member-tok",
                token_hash=hash_token(plaintext),
                token_prefix=token_fingerprint(plaintext),
            )
        )
    return plaintext


def _session_headers(sub: str = "user-1") -> dict[str, str]:
    token = create_session_token(
        secret=get_settings().server.secret_key,
        subject=sub,
        extra={"role": "owner", "name": "alice"},
    )
    return {"Authorization": f"Bearer {token}"}


async def _add_member(db, sub: str = "member-1") -> None:
    async with db.session() as session:
        session.add(User(sub=sub, username="bob", email="bob@example.com", role="member"))
        await session.flush()


async def test_catalog_lists_provider_models(client, seeded):
    resp = await client.get("/api/models", headers=_session_headers())
    assert resp.status_code == 200, resp.text
    ids = {m["model_id"] for m in resp.json()}
    # "*" wildcards never become catalog entries.
    assert "deepseek-chat" in ids
    assert "*" not in ids
    chat = next(m for m in resp.json() if m["model_id"] == "deepseek-chat")
    assert chat["served"] is True
    assert "deepseek" in chat["providers"]
    assert chat["registered"] is False  # no metadata row yet


async def test_sync_registers_entries(client, seeded):
    resp = await client.post("/api/models/sync", headers=_session_headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["added"] >= 1
    # Idempotent: a second sync adds nothing.
    resp2 = await client.post("/api/models/sync", headers=_session_headers())
    assert resp2.json()["added"] == 0


async def test_upsert_sets_description_and_config(client, seeded):
    resp = await client.put(
        "/api/models",
        headers=_session_headers(),
        json={
            "model_id": "deepseek-chat",
            "description": "DeepSeek chat model",
            "opencode_config": {"name": "DeepSeek", "limit": {"context": 65536}},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["description"] == "DeepSeek chat model"
    assert body["opencode_config"]["name"] == "DeepSeek"
    assert body["registered"] is True


async def test_member_cannot_edit(client, db, seeded):
    await _add_member(db)
    resp = await client.put(
        "/api/models",
        headers=_session_headers("member-1"),
        json={"model_id": "deepseek-chat", "description": "nope"},
    )
    assert resp.status_code == 403


async def _member_headers(sub: str = "member-1") -> dict[str, str]:
    token = create_session_token(
        secret=get_settings().server.secret_key,
        subject=sub,
        extra={"role": "member", "name": "bob"},
    )
    return {"Authorization": f"Bearer {token}"}


async def test_member_can_view_but_not_sync(client, db, seeded):
    await _add_member(db)
    # Members may browse the catalog…
    assert (
        await client.get("/api/models", headers=await _member_headers())
    ).status_code == 200
    # …but syncing (reshaping the shared catalog) is staff-only now.
    assert (
        await client.post("/api/models/sync", headers=await _member_headers())
    ).status_code == 403
    # Staff can sync.
    assert (
        await client.post("/api/models/sync", headers=_session_headers())
    ).status_code == 200


async def test_member_does_not_see_hidden_models(client, db, seeded):
    await _add_member(db)
    # Staff hides deepseek-chat.
    await client.put(
        "/api/models",
        headers=_session_headers(),
        json={"model_id": "deepseek-chat", "enabled": False},
    )
    member_ids = {
        m["model_id"]
        for m in (await client.get("/api/models", headers=await _member_headers())).json()
    }
    assert "deepseek-chat" not in member_ids
    # Staff still see it (to manage it).
    staff_ids = {
        m["model_id"]
        for m in (await client.get("/api/models", headers=_session_headers())).json()
    }
    assert "deepseek-chat" in staff_ids


async def test_batch_update(client, seeded):
    resp = await client.post(
        "/api/models/batch",
        headers=_session_headers(),
        json={"model_ids": ["deepseek-chat"], "description": "batched", "enabled": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 1
    listed = (await client.get("/api/models", headers=_session_headers())).json()
    chat = next(m for m in listed if m["model_id"] == "deepseek-chat")
    assert chat["description"] == "batched"


async def test_v1_models_includes_metadata_and_hides_disabled(client, seeded):
    # Enrich + then disable through the metadata API.
    await client.put(
        "/api/models",
        headers=_session_headers(),
        json={"model_id": "deepseek-chat", "description": "hello", "opencode_config": {"x": 1}},
    )
    resp = await client.get("/v1/models", headers={"x-api-key": seeded["token"]})
    assert resp.status_code == 200, resp.text
    chat = next(m for m in resp.json()["data"] if m["id"] == "deepseek-chat")
    assert chat["description"] == "hello"
    assert chat["opencode"] == {"x": 1}

    # Disabling hides it from the advertised list entirely.
    await client.put(
        "/api/models",
        headers=_session_headers(),
        json={"model_id": "deepseek-chat", "enabled": False},
    )
    resp2 = await client.get("/v1/models", headers={"x-api-key": seeded["token"]})
    ids = {m["id"] for m in resp2.json()["data"]}
    assert "deepseek-chat" not in ids


async def test_v1_models_sync_with_token(client, seeded):
    resp = await client.post("/v1/models/sync", headers={"x-api-key": seeded["token"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "added" in body
    assert "total" in body
    # The sync response also carries the gateway's recommended OpenCode
    # top-level selectors so the plugin can sync `model` / `small_model`.
    assert body["opencode_default_model"] == "claude-opus-4-8"
    assert isinstance(body["opencode_small_model"], str)


async def test_v1_models_sync_allowed_for_members(client, db, seeded):
    """A member's Void-Token may sync (no admin rights) and only sees the models
    it can actually call — mirroring GET /v1/models — without reshaping the
    shared catalog (that stays the staff-only /api/models/sync action)."""
    tok = await _member_token(db)
    resp = await client.post("/v1/models/sync", headers={"x-api-key": tok})
    # The whole point of the fix: members are no longer blocked with 403.
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # It never reshapes the shared catalog, so nothing is ever "added".
    assert body["added"] == 0
    # `total` reflects exactly what this token may call, matching GET /v1/models.
    listed = (await client.get("/v1/models", headers={"x-api-key": tok})).json()["data"]
    assert body["total"] == len(listed)
    # Per-caller filtering: a moderator (owner) token sees at least as many
    # models as a plain member (who is gated by role-group access).
    owner_total = (
        await client.post("/v1/models/sync", headers={"x-api-key": seeded["token"]})
    ).json()["total"]
    assert owner_total >= body["total"]
    assert owner_total >= 1


DS_URL = "https://api.deepseek.com/chat/completions"
OAI_RESPONSE = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "model": "deepseek-chat",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


async def test_mapping_hides_source_and_exposes_alias(client, seeded):
    await client.put(
        "/api/models",
        headers=_session_headers(),
        json={"model_id": "deepseek-chat", "mapped_id": "ds-pub"},
    )
    # Dashboard catalog exposes both the source and its public id.
    listed = (await client.get("/api/models", headers=_session_headers())).json()
    chat = next(m for m in listed if m["model_id"] == "deepseek-chat")
    assert chat["mapped_id"] == "ds-pub"
    assert chat["public_id"] == "ds-pub"

    # /v1/models advertises only the alias, never the raw upstream id.
    data = (await client.get("/v1/models", headers={"x-api-key": seeded["token"]})).json()["data"]
    ids = {m["id"] for m in data}
    assert "ds-pub" in ids
    assert "deepseek-chat" not in ids


async def test_mapping_self_alias_rejected(client, seeded):
    resp = await client.put(
        "/api/models",
        headers=_session_headers(),
        json={"model_id": "deepseek-chat", "mapped_id": "deepseek-chat"},
    )
    assert resp.status_code == 422


async def test_call_via_alias_routes_to_source(client, seeded):
    await client.put(
        "/api/models",
        headers=_session_headers(),
        json={"model_id": "deepseek-chat", "mapped_id": "ds-pub"},
    )
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(DS_URL).mock(return_value=httpx.Response(200, json=OAI_RESPONSE))
        resp = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {seeded['token']}"},
            json={"model": "ds-pub", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200, resp.text
        # The upstream received the real model id, not the public alias.
        sent = route.calls.last.request
        import json as _json

        assert _json.loads(sent.content)["model"] == "deepseek-chat"


async def test_call_via_hidden_source_rejected(client, seeded):
    await client.put(
        "/api/models",
        headers=_session_headers(),
        json={"model_id": "deepseek-chat", "mapped_id": "ds-pub"},
    )
    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {seeded['token']}"},
        json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 404


async def test_clear_mapping(client, seeded):
    await client.put(
        "/api/models",
        headers=_session_headers(),
        json={"model_id": "deepseek-chat", "mapped_id": "ds-pub"},
    )
    await client.put(
        "/api/models",
        headers=_session_headers(),
        json={"model_id": "deepseek-chat", "mapped_id": ""},
    )
    listed = (await client.get("/api/models", headers=_session_headers())).json()
    chat = next(m for m in listed if m["model_id"] == "deepseek-chat")
    assert chat["mapped_id"] is None
    assert chat["public_id"] == "deepseek-chat"


async def test_delete_metadata(client, seeded):
    created = (
        await client.put(
            "/api/models",
            headers=_session_headers(),
            json={"model_id": "deepseek-chat", "description": "tmp"},
        )
    ).json()
    entry_id = created["id"]
    resp = await client.delete(f"/api/models/{entry_id}", headers=_session_headers())
    assert resp.status_code == 204
    # Still listed (provider serves it) but no longer registered.
    listed = (await client.get("/api/models", headers=_session_headers())).json()
    chat = next(m for m in listed if m["model_id"] == "deepseek-chat")
    assert chat["registered"] is False


async def test_clean_unserved_removes_orphaned_entries(client, db, seeded):
    # Disable the provider so no models are served — makes the orphan truly unserved.
    from sqlalchemy import update
    from voidswitch.models.db import Provider

    async with db.session() as session:
        await session.execute(
            update(Provider).where(Provider.id == seeded["provider_id"]).values(enabled=False)
        )
        await session.commit()

    # Create a metadata entry for a model that no provider serves.
    await client.put(
        "/api/models",
        headers=_session_headers(),
        json={"model_id": "orphan-model", "opencode_config": {"name": "Orphan"}, "description": "will be orphaned"},
    )
    # Verify it exists in catalog.
    listed = (await client.get("/api/models", headers=_session_headers())).json()
    orphan = next((m for m in listed if m["model_id"] == "orphan-model"), None)
    assert orphan is not None
    assert orphan["served"] is False  # no provider serves this
    assert orphan["registered"] is True  # has metadata row

    # Clean: should remove the orphan.
    resp = await client.post("/api/models/clean", headers=_session_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] == 1
    assert "orphan-model" in body["model_ids"]

    # Verify it's gone from catalog.
    listed2 = (await client.get("/api/models", headers=_session_headers())).json()
    orphans = [m for m in listed2 if m["model_id"] == "orphan-model"]
    assert not orphans

    # Running clean again should be idempotent (nothing to delete).
    resp2 = await client.post("/api/models/clean", headers=_session_headers())
    assert resp2.status_code == 200
    assert resp2.json()["deleted"] == 0


async def test_clean_unserved_preserves_served_models(client, seeded):
    # deepseek-chat IS served (provider has wildcard). Clean should NOT remove its metadata.
    await client.put(
        "/api/models",
        headers=_session_headers(),
        json={"model_id": "deepseek-chat", "opencode_config": {"name": "DeepSeek"}, "description": "kept"},
    )
    resp = await client.post("/api/models/clean", headers=_session_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] == 0
    assert "deepseek-chat" not in body["model_ids"]

    # deepseek-chat metadata is still there.
    listed = (await client.get("/api/models", headers=_session_headers())).json()
    chat = next((m for m in listed if m["model_id"] == "deepseek-chat"), None)
    assert chat is not None
    assert chat["opencode_config"] == {"name": "DeepSeek"}


async def test_clean_unserved_requires_staff(client, db, seeded):
    await _add_member(db)
    await client.put(
        "/api/models",
        headers=_session_headers(),
        json={"model_id": "orphan2", "description": "x"},
    )
    resp = await client.post("/api/models/clean", headers=_session_headers("member-1"))
    assert resp.status_code == 403


async def test_display_name(client, seeded):
    resp = await client.put(
        "/api/models",
        headers=_session_headers(),
        json={"model_id": "deepseek-chat", "display_name": "DeepSeek Chat Pro"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["display_name"] == "DeepSeek Chat Pro"

    listed = (await client.get("/api/models", headers=_session_headers())).json()
    chat = next(m for m in listed if m["model_id"] == "deepseek-chat")
    assert chat["display_name"] == "DeepSeek Chat Pro"

    # /v1/models also advertises display_name.
    data = (await client.get("/v1/models", headers={"x-api-key": seeded["token"]})).json()["data"]
    chat = next(m for m in data if m["id"] == "deepseek-chat")
    assert chat["display_name"] == "DeepSeek Chat Pro"

    # Clear display_name.
    await client.put(
        "/api/models",
        headers=_session_headers(),
        json={"model_id": "deepseek-chat", "display_name": ""},
    )
    listed = (await client.get("/api/models", headers=_session_headers())).json()
    chat = next(m for m in listed if m["model_id"] == "deepseek-chat")
    assert chat["display_name"] is None
