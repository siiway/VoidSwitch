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
    NodeGroupMemberOut,
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


def _parse_node_url(raw: str) -> tuple[str, str, str | None]:
    """Parse one textarea line into ``(url, type, token)``.

    ``url`` is what gets stored (empty for direct nodes), ``type`` is one of the
    :class:`NodeType` values, and ``token`` is the agent credential parsed from
    the ``?token`` query of an agent URL (else ``None``). ``# ...`` introduces an
    inline comment.
    """
    line = raw.split("#", 1)[0].strip()
    lower = line.lower()
    if lower in {"direct", "direct://"}:
        return "", NodeType.DIRECT.value, None
    if lower.startswith("http+agent://") or lower.startswith("https+agent://"):
        base, sep, token = line.partition("?")
        return base.strip(), NodeType.AGENT.value, (token.strip() if sep else None)
    if lower.startswith("socks5://"):
        return line, NodeType.SOCKS5.value, None
    if lower.startswith("http://") or lower.startswith("https://"):
        return line, NodeType.HTTP.value, None
    raise ValueError(f"Unrecognised node URL: {line!r}")


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #


@router.get("", response_model=list[NodeOut])
async def list_nodes(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> list[NodeOut]:
    rows = (await session.execute(select(Node).order_by(Node.id))).scalars().all()
    owner = is_owner(user)
    return [_with_token_preview(n, show=owner) for n in rows]


def _with_token_preview(node: Node, *, show: bool) -> NodeOut:
    """A ``NodeOut`` carrying the token preview for agent nodes.

    Builds a schema object rather than stuffing a transient attribute onto the
    ORM ``Node`` (which is not a model field and confuses type-checkers).
    """
    out = NodeOut.model_validate(node)
    if show and node.token_ciphertext:
        try:
            plaintext = decrypt_secret(
                node.token_ciphertext, secret=get_settings().server.secret_key
            )
            out.token_preview = _token_preview(plaintext)
        except Exception:
            out.token_preview = "***"
    elif node.token_ciphertext:
        out.token_preview = "•••"
    return out


@router.post("", response_model=list[NodeOut], status_code=status.HTTP_201_CREATED)
async def add_nodes(
    body: NodeCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> list[NodeOut]:
    settings = get_settings()
    existing = {u for (u,) in (await session.execute(select(Node.url))).all()}
    created: list[Node] = []
    seen: set[str] = set()
    types_seen: list[str] = []
    for raw in body.urls:
        raw_s = (raw or "").strip()
        if not raw_s:
            continue
        try:
            url, node_type, token = _parse_node_url(raw)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        if url in existing or url in seen:
            continue
        seen.add(url)
        node = Node(
            url=url,
            type=node_type,
            weight=1,
            note=body.note,
            status=NodeStatus.ACTIVE.value,
            token_ciphertext=(
                encrypt_secret(token, secret=settings.server.secret_key) if token else None
            ),
        )
        session.add(node)
        created.append(node)
        types_seen.append(node_type)
    if not created:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No new nodes to add.")
    await session.flush()
    await record_audit(
        session,
        action=AuditAction.PROXY_ADD,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="node",
        detail={
            "added": len(created),
            "ids": [n.id for n in created],
            "types": types_seen,
        },
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
) -> NodeOut:
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
) -> NodeOut:
    node = await session.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found.")
    probe_url = settings_store.get_str("node_default_probe_url", "https://api.openai.com/v1/models")
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


async def _member_projection(session: AsyncSession, group: NodeGroup) -> NodeGroupOut:
    """Project a group (with its resolved members) into the response schema.

    Builds a plain ``NodeGroupOut`` rather than mutating the ORM object. Members
    are loaded with an explicit query (never via the ``group.members`` lazy
    relationship, which triggers a MissingGreenlet when the group was just
    created and its collection is still unloaded in this async session).

    Direct nodes are ordered by their *computed* dynamic ranking (pinned first,
    then by quality score), matching what the dispatcher actually tries; the
    rank is exposed per-member so the UI can show the live order.
    """
    # Never touch ``group.members`` directly — query the rows explicitly.
    member_rows = (
        (
            await session.execute(
                select(NodeGroupMember)
                .where(NodeGroupMember.group_id == group.id)
                .order_by(NodeGroupMember.id)
            )
        )
        .scalars()
        .all()
    )
    groups_by_id = {
        g.id: g
        for g in (await session.execute(select(NodeGroup).where(NodeGroup.id != group.id)))
        .scalars()
        .all()
    }
    node_ids = [m.node_id for m in member_rows if m.node_id is not None]
    nodes_by_id = {
        n.id: n
        for n in (await session.execute(select(Node).where(Node.id.in_(node_ids or [0]))))
        .scalars()
        .all()
    }

    # Compute the dynamic order of this group's direct nodes (pinned first,
    # then quality score), mirroring routing.group_routes.
    direct_nodes = [nodes_by_id[nid] for nid in node_ids if nid in nodes_by_id]
    pinned_ids = {m.node_id for m in member_rows if m.pinned and m.node_id is not None}
    ranked = routing.rank_nodes(direct_nodes, pinned=pinned_ids)
    rank_by_id = {n.id: idx for idx, n in enumerate(ranked)}

    members: list[NodeGroupMemberOut] = []
    for member in member_rows:
        item = {
            "node_id": member.node_id,
            "source_group_id": member.source_group_id,
            "weight": member.weight,
            "pinned": member.pinned,
            "node_url": None,
            "node_note": None,
            "node_status": None,
            "node_latency_ms": None,
            "node_latency_ewma": None,
            "source_group_name": None,
            "source_group_is_system": False,
            "rank": None,
        }
        if member.node_id is not None:
            node = nodes_by_id.get(member.node_id)
            if node is not None:
                item["node_url"] = node.url or "(direct)"
                item["node_note"] = node.note
                item["node_status"] = node.status if node.enabled else "disabled"
                item["node_latency_ms"] = node.latency_ms
                item["node_latency_ewma"] = node.latency_ewma
                item["rank"] = rank_by_id.get(node.id)
        if member.source_group_id is not None:
            src = groups_by_id.get(member.source_group_id)
            if src is not None:
                item["source_group_name"] = src.name
                item["source_group_is_system"] = src.is_system
        members.append(NodeGroupMemberOut(**item))
    # Sort: pinned direct nodes first by rank, then the rest, with inherited
    # group refs kept after direct nodes (they resolve to their own nodes).
    members.sort(
        key=lambda m: (
            0 if m.node_id is not None else 1,
            0 if m.pinned else 1,
            m.rank if m.rank is not None else 2**31,
            m.node_id or 2**31,
        )
    )
    return NodeGroupOut(
        id=group.id,
        slug=group.slug,
        name=group.name,
        description=group.description,
        probe_url=group.probe_url,
        probe_interval_seconds=group.probe_interval_seconds,
        is_system=group.is_system,
        member_count=len(members),
        members=members,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


@groups_router.get("", response_model=list[NodeGroupOut])
async def list_node_groups(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> list[NodeGroupOut]:
    groups = (await session.execute(select(NodeGroup).order_by(NodeGroup.id))).scalars().all()
    result: list[NodeGroupOut] = []
    for g in groups:
        result.append(await _member_projection(session, g))
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
            (await session.execute(select(NodeGroup.id).where(NodeGroup.id.in_(src_ids))))
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
) -> NodeGroupOut:
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
                pinned=m.pinned,
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
    if group is None:  # pragma: no cover - just written above
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node group not found.")
    return await _member_projection(session, group)


@groups_router.patch("/{group_id}", response_model=NodeGroupOut)
async def update_node_group(
    group_id: int,
    body: NodeGroupUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> NodeGroupOut:
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
) -> NodeGroupOut:
    group = await session.get(NodeGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node group not found.")
    if group.slug in {routing.SYSTEM_GROUP_SLUG} and not is_owner(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only owners/co-owners may edit the System node group.",
        )
    await _validate_members(session, group, body)
    # Load existing member rows explicitly — ``group.members`` may be unloaded
    # on a freshly fetched group and lazy-loading it can raise MissingGreenlet.
    existing_members = (
        (await session.execute(select(NodeGroupMember).where(NodeGroupMember.group_id == group.id)))
        .scalars()
        .all()
    )
    for member in existing_members:
        await session.delete(member)
    for m in body:
        session.add(
            NodeGroupMember(
                group_id=group.id,
                node_id=m.node_id,
                source_group_id=m.source_group_id,
                weight=max(1, m.weight),
                pinned=m.pinned,
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
    if group is None:  # pragma: no cover - guarded above
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node group not found.")
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
