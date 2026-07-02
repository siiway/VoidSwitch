"""Announcement API: publish permissions, tier-based edit/delete, audit trail."""

from __future__ import annotations

import pytest
import respx  # noqa: F401  (kept for parity with sibling test modules)
from voidswitch.core.config import get_settings
from voidswitch.core.security import create_session_token
from voidswitch.models.db import AuditLog, User

pytestmark = pytest.mark.asyncio


def _headers(sub: str, role: str, name: str) -> dict[str, str]:
    token = create_session_token(
        secret=get_settings().server.secret_key,
        subject=sub,
        extra={"role": role, "name": name, "epoch": 0},
    )
    return {"Authorization": f"Bearer {token}"}


async def _seed_users(db) -> None:
    async with db.session() as session:
        session.add(User(sub="owner-1", username="olive", role="owner"))
        session.add(User(sub="admin-1", username="andy", role="admin"))
        session.add(User(sub="member-1", username="mia", role="member"))
        await session.flush()


async def test_member_cannot_publish(client, db):
    await _seed_users(db)
    resp = await client.post(
        "/api/announcements",
        headers=_headers("member-1", "member", "mia"),
        json={"title": "hi", "body": "there"},
    )
    assert resp.status_code == 403


async def test_admin_can_publish_and_shows_author(client, db):
    await _seed_users(db)
    resp = await client.post(
        "/api/announcements",
        headers=_headers("admin-1", "admin", "andy"),
        json={"title": "Maintenance", "body": "tonight"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Maintenance"
    assert data["created_by_name"].startswith("andy#")
    assert data["created_by_role"] == "admin"
    # Any signed-in user can read the list (incl. members).
    listed = await client.get(
        "/api/announcements", headers=_headers("member-1", "member", "mia")
    )
    assert listed.status_code == 200
    items = listed.json()
    assert len(items) == 1
    assert items[0]["can_manage"] is False


async def test_owner_can_delete_lower_tier_but_admin_cannot_delete_owner(client, db):
    await _seed_users(db)
    # Admin publishes.
    a = await client.post(
        "/api/announcements",
        headers=_headers("admin-1", "admin", "andy"),
        json={"title": "admin note"},
    )
    admin_id = a.json()["id"]
    # Owner publishes.
    o = await client.post(
        "/api/announcements",
        headers=_headers("owner-1", "owner", "olive"),
        json={"title": "owner note"},
    )
    owner_id = o.json()["id"]

    # Admin cannot delete the owner's announcement (higher tier).
    forbidden = await client.delete(
        f"/api/announcements/{owner_id}", headers=_headers("admin-1", "admin", "andy")
    )
    assert forbidden.status_code == 403

    # Owner can delete the admin's announcement (lower tier).
    ok = await client.delete(
        f"/api/announcements/{admin_id}", headers=_headers("owner-1", "owner", "olive")
    )
    assert ok.status_code == 204


async def test_edit_records_sensitive_audit(client, db):
    await _seed_users(db)
    created = await client.post(
        "/api/announcements",
        headers=_headers("admin-1", "admin", "andy"),
        json={"title": "v1", "body": "first"},
    )
    ann_id = created.json()["id"]
    edited = await client.patch(
        f"/api/announcements/{ann_id}",
        headers=_headers("admin-1", "admin", "andy"),
        json={"title": "v2", "body": "second"},
    )
    assert edited.status_code == 200
    assert edited.json()["edited"] is True

    async with db.session() as session:
        from sqlalchemy import select

        rows = (
            (await session.execute(select(AuditLog).where(AuditLog.action == "announcement.update")))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        # The before/after content is stored as an owner-revealable secret.
        assert rows[0].sensitive_ciphertext
