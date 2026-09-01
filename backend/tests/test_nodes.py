"""Node groups: member replace must not UniqueViolation on pin toggle."""

from __future__ import annotations

import pytest
from voidswitch.constants import NodeStatus
from voidswitch.core.config import get_settings
from voidswitch.core.security import create_session_token
from voidswitch.models.db import Node, NodeGroupMember
from voidswitch.services import routing

pytestmark = pytest.mark.asyncio


def _session_headers(sub: str = "user-1") -> dict[str, str]:
    token = create_session_token(
        secret=get_settings().server.secret_key,
        subject=sub,
        extra={"role": "owner", "name": "alice"},
    )
    return {"Authorization": f"Bearer {token}"}


async def _add_node(db, url: str) -> int:
    async with db.session() as session:
        node = Node(url=url, type="http", status=NodeStatus.ACTIVE.value)
        session.add(node)
        await session.flush()
        default = await routing.default_group(session)
        if default is not None:
            session.add(NodeGroupMember(group_id=default.id, node_id=node.id))
        await session.flush()
        return node.id


async def test_pin_toggle_same_members_no_unique_violation(client, db, seeded):
    node_id = await _add_node(db, "http://proxy-pin-test:8080")
    created = await client.post(
        "/api/admin/node-groups",
        headers=_session_headers(),
        json={
            "name": "pin-toggle-group",
            "members": [{"node_id": node_id, "pinned": False, "weight": 1}],
        },
    )
    assert created.status_code == 201, created.text
    group_id = created.json()["id"]

    # Replacing with the same (group, node) but pinned=True must not 500.
    pinned = await client.put(
        f"/api/admin/node-groups/{group_id}/members",
        headers=_session_headers(),
        json=[{"node_id": node_id, "pinned": True, "weight": 1}],
    )
    assert pinned.status_code == 200, pinned.text
    assert pinned.json()["members"][0]["pinned"] is True

    unpinned = await client.put(
        f"/api/admin/node-groups/{group_id}/members",
        headers=_session_headers(),
        json=[{"node_id": node_id, "pinned": False, "weight": 1}],
    )
    assert unpinned.status_code == 200, unpinned.text
    assert unpinned.json()["members"][0]["pinned"] is False
