"""Admin: audit log and request/usage log browsing."""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
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
from voidswitch.core.database import get_session
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
) -> list[ColumnElement]:
    """Shared WHERE clauses for the audit list and locate endpoints.

    Exact-match on the enumerable columns (populated from the filter-options
    dropdowns), substring/glob match on the free-text IP and user-agent.
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
    status_code: str | None = None,
) -> list[ColumnElement]:
    """Shared WHERE clauses for the request-log list and locate endpoints.

    Model / user / token / provider are exact matches (chosen from the filter
    dropdowns); ``status_code`` accepts an exact code or an ``Nxx`` class.
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
    if status_code:
        clause = _status_clause(status_code)
        if clause is not None:
            clauses.append(clause)
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
    status_code: str | None = Query(
        default=None, description="Exact status code (e.g. 404) or a class (e.g. 4xx)."
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
        status_code=status_code,
    ):
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()

    # Resolve human-friendly caller + token labels in two batched queries.
    token_ids = {r.token_id for r in rows if r.token_id is not None}
    subs = {r.user_sub for r in rows if r.user_sub}
    token_names: dict[int, str] = {}
    if token_ids:
        for tid, tname in (
            await session.execute(
                select(VoidToken.id, VoidToken.name).where(VoidToken.id.in_(token_ids))
            )
        ).all():
            token_names[tid] = tname
    user_names: dict[str, str | None] = {}
    if subs:
        for u in (
            (await session.execute(select(User).where(User.sub.in_(subs)))).scalars().all()
        ):
            label = u.username or u.name or u.email or u.sub
            user_names[u.sub] = f"{label}#{u.id}"

    items: list[RequestLogOut] = []
    for r in rows:
        out = RequestLogOut.model_validate(r)
        if r.token_id is not None:
            out.token_name = token_names.get(r.token_id)
        if r.user_sub:
            out.user_name = user_names.get(r.user_sub)
        items.append(out)
    return Page[RequestLogOut](
        items=items,
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get("/requests/locate")
async def request_locate(
    id: int = Query(..., ge=1, description="Request log id to locate."),
    success: bool | None = None,
    model: str | None = None,
    user_sub: str | None = Query(default=None),
    token_id: int | None = Query(default=None),
    provider: str | None = Query(default=None),
    status_code: str | None = Query(default=None),
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
        status_code=status_code,
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
    subs = {
        s for s in (await session.execute(_distinct(RequestLog.user_sub))).scalars().all() if s
    }
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
        resolved_tokens: dict[int, str] = {}
        for tid, tname in (
            await session.execute(
                select(VoidToken.id, VoidToken.name).where(VoidToken.id.in_(token_ids))
            )
        ).all():
            resolved_tokens[tid] = tname
        tokens = [TokenRef(id=tid, name=resolved_tokens.get(tid, f"#{tid}")) for tid in token_ids]
        tokens.sort(key=lambda tk: tk.name.lower())

    return RequestFilterOptions(
        models=models, providers=providers, users=users, tokens=tokens
    )


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
            detail.token_name = tok.name
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
