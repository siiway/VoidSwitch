"""Exposed models catalog: listing, metadata edits, sync, and /v1/models enrichment."""

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
from voidswitch.models.db import ExposedModel, User, VoidToken

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


async def _add_exposed(db, model_id: str) -> None:
    """Create an exposed model with an empty route."""
    from voidswitch.services import model_routing

    async with db.session() as session:
        entry = ExposedModel(model_id=model_id)
        session.add(entry)
        await session.flush()
        await model_routing.get_or_create_route(session, entry)
        await session.flush()


async def test_catalog_lists_exposed_models(client, seeded):
    resp = await client.get("/api/models", headers=_session_headers())
    assert resp.status_code == 200, resp.text
    ids = {m["model_id"] for m in resp.json()}
    # The seeded exposed model is listed.
    assert "deepseek-chat" in ids
    assert "*" not in ids
    chat = next(m for m in resp.json() if m["model_id"] == "deepseek-chat")
    assert chat["id"] is not None


async def test_v1_models_lists_upstreams_only_for_staff(client, seeded):
    # The exposed model is advertised; upstream model id = public id (unmapped).
    resp = await client.get("/v1/models", headers={"x-api-key": seeded["token"]})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    ids = {m["id"] for m in data}
    assert "deepseek-chat" in ids
    chat = next(m for m in data if m["id"] == "deepseek-chat")
    assert chat["object"] == "model"


async def test_upsert_sets_metadata(client, seeded):
    resp = await client.put(
        "/api/models",
        headers=_session_headers(),
        json={
            "model_id": "deepseek-chat",
            "description": "DeepSeek chat model",
            "opencode_config": {"name": "DeepSeek", "limit": {"context": 65536}},
            "limit_context": 131072,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["description"] == "DeepSeek chat model"
    assert body["limit_context"] == 131072


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


async def test_member_can_view_but_not_reshape(client, db, seeded):
    await _add_member(db)
    # Members may browse the catalog…
    assert (await client.get("/api/models", headers=await _member_headers())).status_code == 200
    # …but reshaping the shared catalog is staff-only. The old "sync from
    # providers" auto-expose endpoint is gone: models are created by hand or
    # via provider passthrough, so a member can't mass-create model configs.
    assert (
        await client.put("/api/models", headers=await _member_headers(), json={"model_id": "x"})
    ).status_code == 403


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
        m["model_id"] for m in (await client.get("/api/models", headers=_session_headers())).json()
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


async def test_v1_models_includes_merged_opencode_and_hides_disabled(client, seeded):
    # Enrich then disable through the metadata API.
    await client.put(
        "/api/models",
        headers=_session_headers(),
        json={
            "model_id": "deepseek-chat",
            "description": "hello",
            "opencode_config": {"limit": {"context": 64000}},
            "limit_context": 128000,
        },
    )
    resp = await client.get("/v1/models", headers={"x-api-key": seeded["token"]})
    assert resp.status_code == 200, resp.text
    chat = next(m for m in resp.json()["data"] if m["id"] == "deepseek-chat")
    assert chat["description"] == "hello"
    # Structured field overrides the custom config's limit.context.
    assert chat["opencode"]["limit"]["context"] == 128000

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
    it can actually call."""
    tok = await _member_token(db)
    resp = await client.post("/v1/models/sync", headers={"x-api-key": tok})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Never reshapes the shared catalog, so nothing is ever "added".
    assert body["added"] == 0
    listed = (await client.get("/v1/models", headers={"x-api-key": tok})).json()["data"]
    assert body["total"] == len(listed)
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


async def test_call_via_exposed_model_routes_to_upstream(client, db, seeded):
    """An exposed model with a different upstream_model routes to the upstream id."""
    from sqlalchemy import select
    from voidswitch.models.db import Provider, RouteLayer, RoutePoolEntry
    from voidswitch.services import model_routing

    async with db.session() as session:
        provider = (
            await session.execute(select(Provider).where(Provider.id == seeded["provider_id"]))
        ).scalar_one()
        provider.models = ["deepseek-chat", "*", "gpt-5"]
        new_exp = ExposedModel(model_id="ds-pub")
        session.add(new_exp)
        await session.flush()
        route = await model_routing.get_or_create_route(session, new_exp)
        layer = RouteLayer(route_id=route.id, position=0, max_attempts=1)
        session.add(layer)
        await session.flush()
        session.add(
            RoutePoolEntry(
                layer_id=layer.id,
                provider_id=seeded["provider_id"],
                upstream_model="deepseek-chat",
            )
        )
        await session.flush()

    with respx.mock(assert_all_called=False) as mock:
        route_mock = mock.post(DS_URL).mock(return_value=httpx.Response(200, json=OAI_RESPONSE))
        resp = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {seeded['token']}"},
            json={"model": "ds-pub", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200, resp.text
        import json as _json

        # The upstream received the real (upstream) model id.
        assert _json.loads(route_mock.calls.last.request.content)["model"] == "deepseek-chat"


async def test_call_with_unexposed_model_rejected(client, seeded):
    """A model id with no exposed row is rejected (raw upstream ids aren't callable)."""
    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {seeded['token']}"},
        json={"model": "not-exposed-anywhere", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 404


async def test_delete_removes_exposed_model(client, seeded):
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
    # The exposed model is gone from the catalog entirely.
    listed = (await client.get("/api/models", headers=_session_headers())).json()
    assert all(m["model_id"] != "deepseek-chat" for m in listed)


async def test_upsert_returns_model_without_greenlet_error(client, seeded):
    """PUT /api/models must not MissingGreenlet when projecting route upstreams."""
    resp = await client.put(
        "/api/models",
        headers=_session_headers(),
        json={"model_id": "deepseek-chat", "description": "round-trip"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["model_id"] == "deepseek-chat"
    assert body["description"] == "round-trip"
    assert isinstance(body.get("upstreams"), list)


async def test_batch_delete_models(client, db, seeded):
    await _add_exposed(db, "batch-del-a")
    await _add_exposed(db, "batch-del-b")
    resp = await client.post(
        "/api/models/batch-delete",
        headers=_session_headers(),
        json={"model_ids": ["batch-del-a", "batch-del-b", "missing-no-op"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] == 2
    assert set(resp.json()["model_ids"]) == {"batch-del-a", "batch-del-b"}
    listed = (await client.get("/api/models", headers=_session_headers())).json()
    ids = {m["model_id"] for m in listed}
    assert "batch-del-a" not in ids
    assert "batch-del-b" not in ids


async def test_clean_unserved_removes_models_without_route(client, db, seeded):
    # Create an exposed model with an empty route (no usable upstream).
    await _add_exposed(db, "orphan-model")
    listed = (await client.get("/api/models", headers=_session_headers())).json()
    assert any(m["model_id"] == "orphan-model" for m in listed)

    resp = await client.post("/api/models/clean", headers=_session_headers())
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1
    assert "orphan-model" in resp.json()["model_ids"]

    listed2 = (await client.get("/api/models", headers=_session_headers())).json()
    assert not any(m["model_id"] == "orphan-model" for m in listed2)

    resp2 = await client.post("/api/models/clean", headers=_session_headers())
    assert resp2.status_code == 200
    assert resp2.json()["deleted"] == 0


async def test_clean_preserves_models_with_route(client, seeded):
    # deepseek-chat has a route (seeded) → clean must NOT remove it.
    resp = await client.post("/api/models/clean", headers=_session_headers())
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 0
    listed = (await client.get("/api/models", headers=_session_headers())).json()
    assert any(m["model_id"] == "deepseek-chat" for m in listed)


async def test_clean_unserved_requires_staff(client, db, seeded):
    await _add_member(db)
    await _add_exposed(db, "orphan2")
    resp = await client.post("/api/models/clean", headers=_session_headers("member-1"))
    assert resp.status_code == 403
