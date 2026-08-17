"""Admin: outbound node + node-group management (the routing system's surface).

Nodes are concrete egress hops (HTTP/SOCKS proxy, voidswitch-agent, or Direct).
Node groups own the order/routing; a group is a set of direct nodes plus
inherited groups. The special ``system`` group (only (co-)owners may edit its
nodes) carries system requests; the ``default`` group is used by providers with
no explicit node group. Both are seeded at startup and cannot be deleted.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import NodeStatus, NodeType
from voidswitch.core.audit import AuditAction, record_audit
from voidswitch.core.auth import actor_display_name, is_owner, require_owner, require_staff
from voidswitch.core.config import get_settings
from voidswitch.core.database import get_session
from voidswitch.core.logging import get_logger
from voidswitch.core.security import decrypt_secret, encrypt_secret
from voidswitch.models.db import Node, NodeGroup, NodeGroupMember, Provider, User
from voidswitch.models.schemas import (
    NodeCreate,
    NodeGroupCreate,
    NodeGroupMemberIn,
    NodeGroupOut,
    NodeGroupUpdate,
    NodeOut,
    NodeUpdate,
)
from voidswitch.services import routing, settings_store
from voidswitch.services.network import probe_route

log = get_logger("admin.nodes")

router = APIRouter(prefix="/api/admin/nodes", tags=["admin:nodes"])
groups_router = APIRouter(prefix="/api/admin/node-groups", tags=["admin:node-groups"])

_VALID_TYPES = {t.value for t in NodeType}


def _token_preview(raw: str) -> str:
    return f"{raw[:8]}…{raw[-4:]}" if len(raw) > 12 else raw[:4] + "***"


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #


@router.get("", response_model=list[NodeOut])
async def list_nodes(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> list[Node]:
    rows = (await session.execute(select(Node).order_by(Node.id))).scalars().all()
    owner = is_owner(user)
    rows = [
        _with_token_preview(n, show=owner)
        for n in rows
    ]
    return rows


def _with_token_preview(node: Node, *, show: bool) -> Node:
    if show and node.token_ciphertext:
        try:
            plaintext = decrypt_secret(
                node.token_ciphertext, secret=get_settings().server.secret_key
            )
            node.token_preview = _token_preview(plaintext)
        except Exception:
            node.token_preview = "***"
    elif node.token_ciphertext:
        node.token_preview = "•••"
    return node


@router.post("", response_model=list[NodeOut], status_code=status.HTTP_201_CREATED)
async def add_nodes(
    body: NodeCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> list[Node]:
    if body.type not in _VALID_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"type must be one of {sorted(_VALID_TYPES)}.",
        )
    settings = get_settings()
    existing = {u for (u,) in (await session.execute(select(Node.url))).all()}
    created: list[Node] = []
    seen: set[str] = set()
    for raw in body.urls:
        url = (raw or "").strip()
        if not url:
            continue
        if url in existing or url in seen:
            continue
        seen.add(url)
        node = Node(
            url=url,
            type=body.type,
            local_address=body.local_address,
            weight=body.weight,
            note=body.note,
            status=NodeStatus.ACTIVE.value,
            token_ciphertext=(
                encrypt_secret(body.token, secret=settings.server.secret_key)
                if body.token
                else None
            ),
        )
        session.add(node)
        created.append(node)
    if not created:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No new nodes to add.")
    await session.flush()
    await record_audit(
        session,
        action=AuditAction.PROXY_ADD,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="node",
        detail={"added": len(created), "ids": [n.id for n in created], "type": body.type},
        ip=request.client.host if request.client else None,
    )
    return [_with_token_preview(n, show=is_owner(user)) for n in created]


@router.patch("/{node_id}", response_model=NodeOut)
async def update_node(
    node_id: int,
    body: NodeUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> Node:
    node = await session.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found.")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("type") is not None and changes["type"] not in _VALID_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"type must be one of {sorted(_VALID_TYPES)}.",
        )
    token = changes.pop("token", None)
    settings = get_settings()
    if token:
        node.token_ciphertext = encrypt_secret(token, secret=settings.server.secret_key)
    if changes.get("enabled") is True or changes.get("status") == NodeStatus.ACTIVE.value:
        node.failed_count = 0
        node.disabled_reason = None
        node.status = NodeStatus.ACTIVE.value
    for field, value in changes.items():
        if field == "enabled":
            continue
        setattr(node, field, value)
    if "enabled" in changes:
        node.enabled = changes["enabled"]
    await session.flush()
    await record_audit(
        session,
        action=AuditAction.PROXY_UPDATE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="node",
        target_id=node_id,
        detail={"changes": changes},
        ip=request.client.host if request.client else None,
    )
    return _with_token_preview(node, show=is_owner(user))


@router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    node_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> None:
    node = await session.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found.")
    await record_audit(
        session,
        action=AuditAction.PROXY_DELETE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="node",
        target_id=node_id,
        detail={"url": node.url},
        ip=request.client.host if request.client else None,
    )
    await session.delete(node)


@router.post("/{node_id}/probe", response_model=NodeOut)
async def probe_node(
    node_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> Node:
    node = await session.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found.")
    probe_url = settings_store.get_str(
        "node_default_probe_url", "https://api.openai.com/v1/models"
    )
    route = routing.node_route(node)
    ok, latency, _status, error = await probe_route(route, probe_url)
    node.last_checked_at = dt.datetime.now(dt.UTC)
    node.latency_ms = latency
    routing.update_node_latency(node, latency)
    if ok:
        node.status = NodeStatus.ACTIVE.value
        node.failed_count = 0
        node.disabled_reason = None
    else:
        node.disabled_reason = error
    await session.flush()
    await record_audit(
        session,
        action=AuditAction.PROXY_PROBE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="node",
        target_id=node_id,
        detail={"ok": ok, "latency_ms": latency, "url": node.url},
        ip=request.client.host if request.client else None,
    )
    return _with_token_preview(node, show=is_owner(user))


# --------------------------------------------------------------------------- #
# Node groups
# --------------------------------------------------------------------------- #


async def _member_projection(session: AsyncSession, group: NodeGroup) -> NodeGroup:
    groups_by_id = {
        g.id: g
        for g in (
            await session.execute(select(NodeGroup).where(NodeGroup.id != group.id))
        ).scalars().all()
    }
    nodes_by_id = {
        n.id: n
        for n in (
            await session.execute(
                select(Node).where(Node.id.in_(
                    [m.node_id for m in group.members if m.node_id is not None] or [0]
                ))
            )
        ).scalars().all()
    }
    out: list = []
    for member in group.members:
        item = {
            "node_id": member.node_id,
            "source_group_id": member.source_group_id,
            "weight": member.weight,
            "node_url": None,
            "node_status": None,
            "node_latency_ms": None,
            "source_group_name": None,
            "source_group_is_system": False,
        }
        if member.node_id is not None:
            node = nodes_by_id.get(member.node_id)
            if node is not None:
                item["node_url"] = node.url or "(direct)"
                item["node_status"] = node.status if node.enabled else "disabled"
                item["node_latency_ms"] = node.latency_ms
        if member.source_group_id is not None:
            src = groups_by_id.get(member.source_group_id)
            if src is not None:
                item["source_group_name"] = src.name
                item["source_group_is_system"] = src.is_system
        out.append(item)
    from voidswitch.models.schemas import NodeGroupMemberOut

    group.member_count = len(out)
    group.members = [NodeGroupMemberOut(**i) for i in out]  # type: ignore[assignment]
    return group


@groups_router.get("", response_model=list[NodeGroupOut])
async def list_node_groups(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> list[NodeGroup]:
    groups = (await session.execute(select(NodeGroup).order_by(NodeGroup.id))).scalars().all()
    result: list[NodeGroup] = []
    for g in groups:
        await _member_projection(session, g)
        result.append(g)
    return result


async def _validate_members(
    session: AsyncSession, group: NodeGroup, members: list[NodeGroupMemberIn]
) -> None:
    """Validate a member list: refs exist, exactly one kind per row, no cycles."""
    for m in members:
        if (m.node_id is None) == (m.source_group_id is None):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Each member must set exactly one of node_id or source_group_id.",
            )
    node_ids = {m.node_id for m in members if m.node_id is not None}
    src_ids = {m.source_group_id for m in members if m.source_group_id is not None}
    if node_ids:
        found = set(
            (await session.execute(select(Node.id).where(Node.id.in_(node_ids)))).scalars().all()
        )
        missing = sorted(node_ids - found)
        if missing:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown node id(s): {missing}."
            )
    if src_ids:
        if group.id in src_ids:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "A group cannot inherit from itself.",
            )
        found = set(
            (
                await session.execute(
                    select(NodeGroup.id).where(NodeGroup.id.in_(src_ids))
                )
            )
            .scalars()
            .all()
        )
        missing = sorted(src_ids - found)
        if missing:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown group id(s): {missing}."
            )
        # Cycle check: the referenced group (transitively) must not include us.
        index = await routing.load_group_index(session)
        for src in src_ids:
            src_group = index.get(src)
            if src_group is None:
                continue
            # Walk the referenced group's transitive inheritance.
            path: set[int] = set()
            stack = [src_group]
            while stack:
                cur = stack.pop()
                if cur.id in path or cur.id == group.id:
                    continue
                path.add(cur.id)
                for m in cur.members:
                    if m.source_group_id is not None:
                        nxt = index.get(m.source_group_id)
                        if nxt is not None:
                            stack.append(nxt)
            if group.id in path:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "Cycle detected: this group would inherit from itself transitively.",
                )


@groups_router.post("", response_model=NodeGroupOut, status_code=status.HTTP_201_CREATED)
async def create_node_group(
    body: NodeGroupCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> NodeGroup:
    existing = (
        await session.execute(select(NodeGroup).where(NodeGroup.name == body.name))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Node group name already exists.")
    group = NodeGroup(
        name=body.name,
        description=body.description,
        probe_url=(body.probe_url or "").strip() or None,
        probe_interval_seconds=max(0, body.probe_interval_seconds),
    )
    session.add(group)
    await session.flush()
    await _validate_members(session, group, body.members)
    for m in body.members:
        session.add(
            NodeGroupMember(
                group_id=group.id,
                node_id=m.node_id,
                source_group_id=m.source_group_id,
                weight=max(1, m.weight),
            )
        )
    await session.flush()
    await record_audit(
        session,
        action=AuditAction.PROXY_ADD,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="node_group",
        target_id=group.id,
        detail={"name": group.name, "member_count": len(body.members)},
        ip=request.client.host if request.client else None,
    )
    group = await session.get(NodeGroup, group.id)
    return await _member_projection(session, group)


@groups_router.patch("/{group_id}", response_model=NodeGroupOut)
async def update_node_group(
    group_id: int,
    body: NodeGroupUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> NodeGroup:
    group = await session.get(NodeGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node group not found.")
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] != group.name:
        clash = (
            await session.execute(
                select(NodeGroup.id).where(
                    NodeGroup.name == changes["name"], NodeGroup.id != group_id
                )
            )
        ).first()
        if clash is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Node group name already exists.")
    for field, value in changes.items():
        if field == "probe_url":
            setattr(group, field, (value or "").strip() or None)
        else:
            setattr(group, field, value)
    await session.flush()
    await record_audit(
        session,
        action=AuditAction.PROXY_UPDATE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="node_group",
        target_id=group_id,
        detail={"changes": changes},
        ip=request.client.host if request.client else None,
    )
    return await _member_projection(session, group)


@groups_router.put("/{group_id}/members", response_model=NodeGroupOut)
async def set_node_group_members(
    group_id: int,
    body: list[NodeGroupMemberIn],
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> NodeGroup:
    group = await session.get(NodeGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node group not found.")
    if group.slug in {routing.SYSTEM_GROUP_SLUG} and not is_owner(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only owners/co-owners may edit the System node group.",
        )
    await _validate_members(session, group, body)
    for member in list(group.members):
        await session.delete(member)
    for m in body:
        session.add(
            NodeGroupMember(
                group_id=group.id,
                node_id=m.node_id,
                source_group_id=m.source_group_id,
                weight=max(1, m.weight),
            )
        )
    await session.flush()
    await record_audit(
        session,
        action=AuditAction.PROXY_UPDATE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="node_group",
        target_id=group_id,
        detail={"changes": {"members": [m.model_dump() for m in body]}},
        ip=request.client.host if request.client else None,
    )
    group = await session.get(NodeGroup, group_id)
    return await _member_projection(session, group)


@groups_router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node_group(
    group_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_owner),
) -> None:
    group = await session.get(NodeGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node group not found.")
    if group.slug in {routing.DEFAULT_GROUP_SLUG, routing.SYSTEM_GROUP_SLUG}:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"The '{group.slug}' node group cannot be deleted.",
        )
    # Providers referencing this group fall back to the default group.
    providers = (await session.execute(select(Provider))).scalars().all()
    for p in providers:
        if p.node_group_id == group_id:
            p.node_group_id = None
    await record_audit(
        session,
        action=AuditAction.PROXY_DELETE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="node_group",
        target_id=group_id,
        detail={"name": group.name},
        ip=request.client.host if request.client else None,
    )
    await session.delete(group)