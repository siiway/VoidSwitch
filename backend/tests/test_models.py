"""Models catalog: listing, metadata edits, sync, and /v1/models enrichment."""

from __future__ import annotations

import httpx
import pytest
import respx
from voidswitch.core.config import get_settings
from voidswitch.core.security import create_session_token
from voidswitch.models.db import User

pytestmark = pytest.mark.asyncio


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


async def test_member_can_view_and_sync(client, db, seeded):
    await _add_member(db)
    assert (await client.get("/api/models", headers=_session_headers("member-1"))).status_code == 200
    assert (
        await client.post("/api/models/sync", headers=_session_headers("member-1"))
    ).status_code == 200


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
    assert "added" in resp.json()
    assert "total" in resp.json()


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
