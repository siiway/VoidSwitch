"""Admin: audit log and request/usage log browsing."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
import time
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.audit import AuditAction, record_audit
from voidswitch.core.auth import (
    actor_display_name,
    get_current_user,
    is_owner,
    is_staff,
    require_owner,
    require_staff,
)
from voidswitch.core.config import Settings, get_settings
from voidswitch.core.database import get_database, get_session
from voidswitch.core.security import decrypt_secret
from voidswitch.models.db import ApiKey, AuditLog, RequestLog, User, VoidToken
from voidswitch.models.schemas import (
    AuditActor,
    AuditFilterOptions,
    AuditLogOut,
    Page,
    RequestFilterOptions,
    RequestLogDetail,
    RequestLogOut,
    TokenRef,
)
from voidswitch.services import settings_store

router = APIRouter(prefix="/api/admin/logs", tags=["admin:logs"])


def _text_match(column: Any, q: str) -> ColumnElement:
    """Case-insensitive filter for a free-text field.

    Plain input is a substring match (``%q%``). When the query contains glob
    wildcards it is treated as an ``fnmatch``-style pattern: ``*`` matches any run
    of characters and ``?`` matches a single one. The LIKE metacharacters (``%``,
    ``_``) and the escape char are escaped first so only ``*`` / ``?`` are special.
    """
    if "*" in q or "?" in q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = escaped.replace("*", "%").replace("?", "_")
        return column.ilike(pattern, escape="\\")
    return column.ilike(f"%{q}%")


def _audit_filters(
    *,
    action: str | None,
    scope: str | None,
    actor_sub: str | None,
    target_type: str | None,
    ip: str | None,
    user_agent: str | None,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
) -> list[ColumnElement]:
    """Shared WHERE clauses for the audit list and locate endpoints.

    Exact-match on the enumerable columns (populated from the filter-options
    dropdowns), substring/glob match on the free-text IP and user-agent, and an
    inclusive ``start``/``end`` window on the indexed ``ts`` timestamp.
    """
    clauses: list[ColumnElement] = []
    if action:
        clauses.append(AuditLog.action == action)
    if scope:
        clauses.append(AuditLog.scope == scope)
    if actor_sub:
        clauses.append(AuditLog.actor_sub == actor_sub)
    if target_type:
        clauses.append(AuditLog.target_type == target_type)
    if ip:
        clauses.append(_text_match(AuditLog.ip, ip))
    if user_agent:
        clauses.append(_text_match(AuditLog.user_agent, user_agent))
    if start is not None:
        clauses.append(AuditLog.ts >= start)
    if end is not None:
        clauses.append(AuditLog.ts <= end)
    return clauses


@router.get("/audit", response_model=Page[AuditLogOut])
async def audit_logs(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None, description="Filter by exact action."),
    scope: str | None = Query(default=None, description="Filter by scope, e.g. 'admin'."),
    actor_sub: str | None = Query(default=None, description="Filter by the actor's subject."),
    target_type: str | None = Query(default=None, description="Filter by target resource type."),
    ip: str | None = Query(default=None, description="Substring/glob match on the actor IP."),
    user_agent: str | None = Query(
        default=None, description="Substring/glob match on the user-agent."
    ),
    start: dt.datetime | None = Query(
        default=None, description="Only entries at or after this instant (ISO 8601)."
    ),
    end: dt.datetime | None = Query(
        default=None, description="Only entries at or before this instant (ISO 8601)."
    ),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> Page[AuditLogOut]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    count_stmt = select(func.count(AuditLog.id))

    for clause in _audit_filters(
        action=action,
        scope=scope,
        actor_sub=actor_sub,
        target_type=target_type,
        ip=ip,
        user_agent=user_agent,
        start=start,
        end=end,
    ):
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()
    items: list[AuditLogOut] = []
    for r in rows:
        out = AuditLogOut.model_validate(r)
        out.has_sensitive = bool(r.sensitive_ciphertext)
        items.append(out)
    return Page[AuditLogOut](
        items=items,
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get("/audit/locate")
async def audit_locate(
    id: int = Query(..., ge=1, description="Audit entry id to locate."),
    action: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    actor_sub: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    ip: str | None = Query(default=None),
    user_agent: str | None = Query(default=None),
    start: dt.datetime | None = Query(default=None),
    end: dt.datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> dict[str, object]:
    """Return the zero-based offset of audit entry ``id`` under the given filters.

    The list is ordered by ``id`` descending, so the offset is the number of
    matching rows with a larger id. Gap-safe (survives deletions) — used by the
    dashboard's "jump to id" so it lands on the right page regardless of order.
    """
    filters = _audit_filters(
        action=action,
        scope=scope,
        actor_sub=actor_sub,
        target_type=target_type,
        ip=ip,
        user_agent=user_agent,
        start=start,
        end=end,
    )

    exists_stmt = select(func.count(AuditLog.id)).where(AuditLog.id == id)
    before_stmt = select(func.count(AuditLog.id)).where(AuditLog.id > id)
    for clause in filters:
        exists_stmt = exists_stmt.where(clause)
        before_stmt = before_stmt.where(clause)
    found = (await session.execute(exists_stmt)).scalar_one() > 0
    offset = int((await session.execute(before_stmt)).scalar_one())
    return {"id": id, "offset": offset, "found": found}


@router.get("/audit/filters", response_model=AuditFilterOptions)
async def audit_filter_options(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> AuditFilterOptions:
    """Distinct values present in the trail, to populate the dashboard filters."""
    actions = (
        (await session.execute(select(AuditLog.action).distinct().order_by(AuditLog.action)))
        .scalars()
        .all()
    )
    scopes = (
        (await session.execute(select(AuditLog.scope).distinct().order_by(AuditLog.scope)))
        .scalars()
        .all()
    )
    target_types = (
        (
            await session.execute(
                select(AuditLog.target_type)
                .where(AuditLog.target_type.is_not(None))
                .distinct()
                .order_by(AuditLog.target_type)
            )
        )
        .scalars()
        .all()
    )
    actor_rows = (
        await session.execute(
            select(AuditLog.actor_sub, AuditLog.actor_name)
            .where(AuditLog.actor_sub.is_not(None))
            .distinct()
        )
    ).all()
    # Collapse to the most-recent display name per subject.
    actors: dict[str, str] = {}
    for sub, name in actor_rows:
        if sub and sub not in actors:
            actors[sub] = name or sub
    return AuditFilterOptions(
        actions=[a for a in actions if a],
        scopes=[s for s in scopes if s],
        target_types=[t for t in target_types if t],
        actors=[AuditActor(sub=sub, name=name) for sub, name in sorted(actors.items())],
    )


@router.post("/audit/{audit_id}/reveal")
async def reveal_audit_sensitive(
    audit_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_owner),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Owner-only: decrypt and return the sensitive payload for one audit entry.

    Guarded behind a secondary confirmation in the UI. The reveal itself is
    audited (without re-storing the secret) so there is a trail of who looked.
    """
    entry = await session.get(AuditLog, audit_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Audit entry not found.")
    if not entry.sensitive_ciphertext:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No sensitive data for this entry.")
    try:
        payload = json.loads(
            decrypt_secret(entry.sensitive_ciphertext, secret=settings.server.secret_key)
        )
    except (ValueError, TypeError) as exc:  # pragma: no cover - corrupt/rotated key
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not decrypt sensitive data."
        ) from exc
    await record_audit(
        session,
        action=AuditAction.AUDIT_REVEAL,
        actor_sub=actor.sub,
        actor_name=actor_display_name(actor),
        target_type="audit",
        target_id=audit_id,
        detail={"revealed_action": entry.action, "revealed_actor": entry.actor_name},
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return {"id": audit_id, "action": entry.action, "sensitive": payload}


def _status_clause(status_code: str) -> ColumnElement | None:
    """Turn a status filter into a clause.

    ``"404"`` → exactly 404; ``"4xx"`` (or a bare ``"4"`` the frontend expands to
    ``4xx``) → the whole 400-499 class. Anything else is ignored.
    """
    s = status_code.strip().lower()
    cls = re.fullmatch(r"([1-5])xx", s)
    if cls:
        n = int(cls.group(1))
        return (RequestLog.status_code >= n * 100) & (RequestLog.status_code < (n + 1) * 100)
    if s.isdigit():
        return RequestLog.status_code == int(s)
    return None


def _request_log_filters(
    user: User,
    *,
    success: bool | None = None,
    model: str | None = None,
    user_sub: str | None = None,
    token_id: int | None = None,
    provider: str | None = None,
    client_ip: str | None = None,
    status_code: str | None = None,
    req_status: str | None = None,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
) -> list[ColumnElement]:
    """Shared WHERE clauses for the request-log list and locate endpoints.

    Model / user / token / provider / lifecycle status are exact matches (chosen
    from the filter dropdowns); ``status_code`` accepts an exact code or an
    ``Nxx`` class; ``client_ip`` is a substring/glob match on the caller's IP
    (mirroring the audit-log IP filter, so ``10.0.*`` works); ``start``/``end``
    bound the indexed ``ts`` timestamp inclusively.
    """
    clauses: list[ColumnElement] = []
    if not is_staff(user):
        # Members may browse the request log, but only their own traffic.
        clauses.append(RequestLog.user_sub == user.sub)
    if success is not None:
        clauses.append(RequestLog.success.is_(success))
    if model:
        clauses.append(RequestLog.model == model)
    if user_sub:
        clauses.append(RequestLog.user_sub == user_sub)
    if token_id is not None:
        clauses.append(RequestLog.token_id == token_id)
    if provider:
        clauses.append(RequestLog.provider_name == provider)
    if client_ip:
        clauses.append(_text_match(RequestLog.client_ip, client_ip))
    if status_code:
        clause = _status_clause(status_code)
        if clause is not None:
            clauses.append(clause)
    if req_status:
        clauses.append(RequestLog.req_status == req_status)
    if start is not None:
        clauses.append(RequestLog.ts >= start)
    if end is not None:
        clauses.append(RequestLog.ts <= end)
    return clauses


@router.get("/requests", response_model=Page[RequestLogOut])
async def request_logs(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    success: bool | None = None,
    model: str | None = None,
    user_sub: str | None = Query(default=None, description="Filter by exact caller subject."),
    token_id: int | None = Query(default=None, description="Filter by exact Void-Token id."),
    provider: str | None = Query(default=None, description="Filter by exact provider name."),
    client_ip: str | None = Query(
        default=None, description="Substring/glob match on the caller's IP (e.g. 10.0.*)."
    ),
    status_code: str | None = Query(
        default=None, description="Exact status code (e.g. 404) or a class (e.g. 4xx)."
    ),
    req_status: str | None = Query(
        default=None,
        description="Lifecycle status: pending / completed / cancelled / error / terminated.",
    ),
    start: dt.datetime | None = Query(
        default=None, description="Only entries at or after this instant (ISO 8601)."
    ),
    end: dt.datetime | None = Query(
        default=None, description="Only entries at or before this instant (ISO 8601)."
    ),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Page[RequestLogOut]:
    stmt = select(RequestLog).order_by(RequestLog.id.desc())
    count_stmt = select(func.count(RequestLog.id))
    for clause in _request_log_filters(
        user,
        success=success,
        model=model,
        user_sub=user_sub,
        token_id=token_id,
        provider=provider,
        client_ip=client_ip,
        status_code=status_code,
        req_status=req_status,
        start=start,
        end=end,
    ):
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()

    items = await _resolve_request_log_rows(session, rows)
    return Page[RequestLogOut](
        items=items,
        total=int(total),
        limit=limit,
        offset=offset,
    )


async def _resolve_request_log_rows(
    session: AsyncSession, rows: Sequence[RequestLog]
) -> list[RequestLogOut]:
    """Map request-log rows to ``RequestLogOut``, resolving the human-friendly
    caller + token labels in two batched queries (mirrors the list endpoint; the
    live stream reuses it so pushed rows render identically to fetched ones)."""
    token_ids = {r.token_id for r in rows if r.token_id is not None}
    subs = {r.user_sub for r in rows if r.user_sub}
    token_names: dict[int, tuple[str, str | None]] = {}
    if token_ids:
        for tid, tname, usub, username, name, email, uid in (
            await session.execute(
                select(
                    VoidToken.id,
                    VoidToken.name,
                    User.sub,
                    User.username,
                    User.name,
                    User.email,
                    User.id,
                )
                .join(User, User.id == VoidToken.user_id)
                .where(VoidToken.id.in_(token_ids))
            )
        ).all():
            label = username or name or email or usub
            token_names[tid] = (f"{tname}#{tid}", f"{label}#{uid}")
    user_names: dict[str, str | None] = {}
    if subs:
        for u in (await session.execute(select(User).where(User.sub.in_(subs)))).scalars().all():
            label = u.username or u.name or u.email or u.sub
            user_names[u.sub] = f"{label}#{u.id}"

    items: list[RequestLogOut] = []
    for r in rows:
        out = RequestLogOut.model_validate(r)
        if r.token_id is not None:
            token_ref = token_names.get(r.token_id)
            if token_ref:
                out.token_name = token_ref[0]
                out.token_owner_name = token_ref[1]
        if r.user_sub:
            out.user_name = user_names.get(r.user_sub)
        items.append(out)
    return items


@router.get("/requests/locate")
async def request_locate(
    id: int = Query(..., ge=1, description="Request log id to locate."),
    success: bool | None = None,
    model: str | None = None,
    user_sub: str | None = Query(default=None),
    token_id: int | None = Query(default=None),
    provider: str | None = Query(default=None),
    client_ip: str | None = Query(default=None),
    status_code: str | None = Query(default=None),
    req_status: str | None = Query(default=None),
    start: dt.datetime | None = Query(default=None),
    end: dt.datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    """Zero-based offset of request log ``id`` under the given filters (id desc)."""
    clauses = _request_log_filters(
        user,
        success=success,
        model=model,
        user_sub=user_sub,
        token_id=token_id,
        provider=provider,
        client_ip=client_ip,
        status_code=status_code,
        req_status=req_status,
        start=start,
        end=end,
    )
    exists_stmt = select(func.count(RequestLog.id)).where(RequestLog.id == id)
    before_stmt = select(func.count(RequestLog.id)).where(RequestLog.id > id)
    for clause in clauses:
        exists_stmt = exists_stmt.where(clause)
        before_stmt = before_stmt.where(clause)
    found = (await session.execute(exists_stmt)).scalar_one() > 0
    offset = int((await session.execute(before_stmt)).scalar_one())
    return {"id": id, "offset": offset, "found": found}


@router.get("/requests/filters", response_model=RequestFilterOptions)
async def request_filter_options(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> RequestFilterOptions:
    """Distinct values present in the request log, to drive the UI filters.

    Scoped to the caller's own traffic for members (mirroring the log list), so a
    member never learns which models/tokens/users exist beyond their own.
    """
    scope: list[ColumnElement] = []
    if not is_staff(user):
        scope.append(RequestLog.user_sub == user.sub)

    def _distinct(column: Any):
        stmt = select(column).where(column.is_not(None)).distinct()
        for clause in scope:
            stmt = stmt.where(clause)
        return stmt

    models = sorted(
        {m for m in (await session.execute(_distinct(RequestLog.model))).scalars().all() if m}
    )
    providers = sorted(
        {
            p
            for p in (await session.execute(_distinct(RequestLog.provider_name))).scalars().all()
            if p
        }
    )
    subs = {s for s in (await session.execute(_distinct(RequestLog.user_sub))).scalars().all() if s}
    token_ids = {
        tid
        for tid in (await session.execute(_distinct(RequestLog.token_id))).scalars().all()
        if tid is not None
    }

    # Resolve human-friendly labels; fall back to the raw id for deleted rows.
    users: list[AuditActor] = []
    if subs:
        resolved: dict[str, str] = {}
        for u in (await session.execute(select(User).where(User.sub.in_(subs)))).scalars().all():
            label = u.username or u.name or u.email or u.sub
            resolved[u.sub] = f"{label}#{u.id}"
        users = [AuditActor(sub=s, name=resolved.get(s, s)) for s in subs]
        users.sort(key=lambda a: a.name.lower())

    tokens: list[TokenRef] = []
    if token_ids:
        resolved_tokens: dict[int, tuple[str, str | None, str | None]] = {}
        for tid, tname, usub, username, name, email, uid in (
            await session.execute(
                select(
                    VoidToken.id,
                    VoidToken.name,
                    User.sub,
                    User.username,
                    User.name,
                    User.email,
                    User.id,
                )
                .join(User, User.id == VoidToken.user_id)
                .where(VoidToken.id.in_(token_ids))
            )
        ).all():
            label = username or name or email or usub
            resolved_tokens[tid] = (tname, usub, f"{label}#{uid}")
        tokens = [
            TokenRef(
                id=tid,
                name=(f"{resolved_tokens[tid][0]}#{tid}" if tid in resolved_tokens else f"#{tid}"),
                user_sub=resolved_tokens.get(tid, (f"#{tid}", None, None))[1],
                user_name=resolved_tokens.get(tid, (f"#{tid}", None, None))[2],
            )
            for tid in token_ids
        ]
        tokens.sort(key=lambda tk: tk.name.lower())

    return RequestFilterOptions(models=models, providers=providers, users=users, tokens=tokens)


# --------------------------------------------------------------------------- #
# Live request-log stream (SSE)
# --------------------------------------------------------------------------- #

# How often a connected live stream re-checks the log for new rows. 1s keeps the
# view near-realtime while staying trivially cheap: the query is an indexed
# ``id > last_seen`` scan with no joins, bounded by ``_STREAM_BATCH``.
_STREAM_POLL_SECONDS = 1.0
# Max rows pushed per poll — bounds both the query and the burst per event.
_STREAM_BATCH = 100
# Interval (seconds) for a keep-alive comment so idle connections through
# proxies/load balancers aren't silently dropped.
_STREAM_HEARTBEAT_SECONDS = 15.0

# Active streams per user (in-process; a small module-level dict guarded by a
# lock). Enforces the per-user connection cap without touching the hot request
# path — this registry is only touched on connect/disconnect.
_stream_lock = asyncio.Lock()
_stream_active: dict[str, int] = {}


async def _acquire_stream_slot(user_sub: str, max_streams: int) -> None:
    """Reserve one live-stream slot for ``user_sub``, raising 429 when the
    per-user cap is reached. Must be paired with a matching ``_release_stream``
    (the stream generator's ``finally``)."""
    if max_streams <= 0:
        return
    async with _stream_lock:
        active = _stream_active.get(user_sub, 0)
        if active >= max_streams:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Too many active live-log streams (limit {max_streams}). "
                "Close another live view and try again.",
            )
        _stream_active[user_sub] = active + 1


async def _release_stream_slot(user_sub: str) -> None:
    async with _stream_lock:
        active = _stream_active.get(user_sub, 0)
        if active <= 1:
            _stream_active.pop(user_sub, None)
        else:
            _stream_active[user_sub] = active - 1


@router.get("/requests/stream")
async def request_log_stream(
    after_id: int = Query(
        default=0, ge=0, description="Only rows with id greater than this are streamed."
    ),
    model: str | None = None,
    user_sub: str | None = Query(default=None, description="Filter by exact caller subject."),
    token_id: int | None = Query(default=None, description="Filter by exact Void-Token id."),
    provider: str | None = Query(default=None, description="Filter by exact provider name."),
    client_ip: str | None = Query(
        default=None, description="Substring/glob match on the caller's IP (e.g. 10.0.*)."
    ),
    status_code: str | None = Query(
        default=None, description="Exact status code (e.g. 404) or a class (e.g. 4xx)."
    ),
    req_status: str | None = Query(
        default=None,
        description="Lifecycle status: pending / completed / cancelled / error / terminated.",
    ),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Live request-log stream over SSE.

    Pushes new request-log rows matching the same filters as ``GET
    /requests`` (and the same member-scoping), roughly as they are written. The
    payload for each row is the same ``RequestLogOut`` the list endpoint returns
    (names resolved), so the client can append rows to its table directly.
    ``after_id`` skips rows already known to the client (pass the max id
    currently displayed); the stream only delivers strictly newer ones.

    The stream is driven by a lightweight poll — ``SELECT ... WHERE id > last``
    with no joins, once per second, bounded to ``_STREAM_BATCH`` rows — rather
    than hooking the dispatcher's hot path, so it adds no per-request overhead
    and stays correct even when request-log rows are written by another worker.

    Per-user concurrency is capped by the ``log_stream_max_connections`` setting
    (default 2); exceeding it returns ``429``.
    """
    max_streams = settings_store.get_int("log_stream_max_connections", 2)
    await _acquire_stream_slot(user.sub, max_streams)
    filters = _request_log_filters(
        user,
        model=model,
        user_sub=user_sub,
        token_id=token_id,
        provider=provider,
        client_ip=client_ip,
        status_code=status_code,
        req_status=req_status,
    )

    # The stream should only ever deliver rows created *after* the client
    # connects. If the client didn't pass an explicit ``after_id`` (it hasn't
    # yet seen any row, e.g. the live view was just switched on), snapshot the
    # current max id now so the stream doesn't flood the client with the
    # entire request-log history on the first poll.
    if after_id == 0:
        after_id = (await session.execute(select(func.max(RequestLog.id)))).scalar_one() or 0

    async def _stream() -> AsyncIterator[str]:
        async for event in _stream_request_log_events(
            get_database(), filters, user.sub, after_id=after_id
        ):
            yield event

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # tell nginx not to buffer the SSE body
            "Connection": "keep-alive",
        },
    )


async def _stream_request_log_events(
    db: Any,
    filters: list[ColumnElement],
    user_sub: str,
    *,
    after_id: int = 0,
    poll_seconds: float = _STREAM_POLL_SECONDS,
) -> AsyncGenerator[str]:
    """Yield SSE events (``data: …`` rows / keep-alive pings) for a live stream.

    Polls ``request_logs`` for rows newer than the last emitted id (an indexed,
    join-free query bounded to ``_STREAM_BATCH`` rows), pushes them as the same
    ``RequestLogOut`` JSON the list endpoint returns, and emits a keep-alive
    comment when the stream is otherwise idle. Runs until cancelled; the
    per-user stream slot is released on exit.

    Also re-pushes rows that this stream previously sent as ``pending`` once they
    finalise (``finished_at`` is set), so the client's duration and status
    update live without a manual refresh. Historical rows already present at
    connect time (``<= after_id``) are never re-pushed — only rows the stream
    itself observed being created are watched for finalisation.
    """
    last_id = after_id
    # Ids of rows this stream pushed while they were still pending — the only
    # rows that need re-pushing when they finalise.
    watched_pending: set[int] = set()
    last_sent = time.monotonic()
    try:
        while True:
            try:
                async with db.session() as session:
                    # New rows (id > last_id).
                    stmt = (
                        select(RequestLog)
                        .where(RequestLog.id > last_id)
                        .order_by(RequestLog.id.asc())
                        .limit(_STREAM_BATCH)
                    )
                    for clause in filters:
                        stmt = stmt.where(clause)
                    rows = (await session.execute(stmt)).scalars().all()

                    # Rows we watched as pending that have since finalised.
                    update_rows: list[RequestLog] = []
                    if watched_pending:
                        update_stmt = (
                            select(RequestLog)
                            .where(
                                RequestLog.id.in_(list(watched_pending)),
                                RequestLog.finished_at.isnot(None),
                                RequestLog.req_status != "pending",
                            )
                            .order_by(RequestLog.id.asc())
                            .limit(_STREAM_BATCH)
                        )
                        for clause in filters:
                            update_stmt = update_stmt.where(clause)
                        update_rows = (await session.execute(update_stmt)).scalars().all()

                    all_rows = rows + [r for r in update_rows if r.id not in {rr.id for rr in rows}]
                    # Newly-created pending rows enter the watchlist; finalised
                    # ones leave it so we never query for them again.
                    for r in all_rows:
                        if r.req_status == "pending":
                            watched_pending.add(r.id)
                        else:
                            watched_pending.discard(r.id)
                    if all_rows:
                        items = await _resolve_request_log_rows(session, all_rows)
                if all_rows:
                    last_id = max(last_id, all_rows[-1].id)
                    for item in items:
                        yield f"data: {item.model_dump_json()}\n\n"
                    last_sent = time.monotonic()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Transient DB blip must not kill the stream — skip this
                # poll and try again on the next tick.
                await asyncio.sleep(poll_seconds)
                continue
            # Keep-alive comment so proxies don't drop a quiet connection.
            if time.monotonic() - last_sent >= _STREAM_HEARTBEAT_SECONDS:
                yield ": ping\n\n"
                last_sent = time.monotonic()
            await asyncio.sleep(poll_seconds)
    finally:
        await _release_stream_slot(user_sub)


def _redact_key_preview(preview: str | None) -> str | None:
    """Show first 4 and last 4 chars with *** in between."""
    if not preview or len(preview) <= 8:
        return preview
    return f"{preview[:4]}***{preview[-4:]}"


@router.get("/requests/{log_id}", response_model=RequestLogDetail)
async def request_log_detail(
    log_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> RequestLogDetail:
    """Return full detail for a single request log entry.

    Owners (co-owner / owner) see everything including reveal-secret mode.
    Admins see redacted key preview and no req/resp headers/body.
    Members can only view their own logs.
    """
    row = await session.get(RequestLog, log_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request log not found.")

    # Members can only see their own traffic.
    if not is_staff(user) and row.user_sub != user.sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request log not found.")

    owner = is_owner(user)
    admin = is_staff(user) and not owner

    detail = RequestLogDetail.model_validate(row)

    # Resolve names.
    if row.token_id is not None:
        tok = await session.get(VoidToken, row.token_id)
        if tok:
            detail.token_name = f"{tok.name}#{tok.id}"
            if tok.user:
                label = tok.user.username or tok.user.name or tok.user.email or tok.user.sub
                detail.token_owner_name = f"{label}#{tok.user.id}"
    if row.user_sub:
        u = (
            await session.execute(select(User).where(User.sub == row.user_sub))
        ).scalar_one_or_none()
        if u:
            label = u.username or u.name or u.email or u.sub
            detail.user_name = f"{label}#{u.id}"

    # Resolve key preview.
    if row.key_id is not None:
        key = await session.get(ApiKey, row.key_id)
        if key:
            if admin:
                detail.key_preview = _redact_key_preview(key.key_preview)
            else:
                detail.key_preview = key.key_preview

    # Admin: strip debug detail fields (headers, body, per-attempt trail). Admins
    # may view the normal log info but never the debug-level request/response
    # capture — that is owner / co-owner only.
    if admin:
        detail.req_headers = None
        detail.req_body = None
        detail.resp_headers = None
        detail.resp_body = None
        detail.debug_attempts = None

    return detail
