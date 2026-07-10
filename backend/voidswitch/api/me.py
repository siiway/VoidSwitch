"""Member self-service: fetch your Void-Token(s) and usage/quota."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.audit import AuditAction, AuditScope, record_audit
from voidswitch.core.auth import actor_display_name, get_current_user, is_staff
from voidswitch.core.config import Settings, get_settings
from voidswitch.core.database import get_session
from voidswitch.core.security import (
    generate_login_token,
    generate_void_token,
    hash_token,
    token_fingerprint,
)
from voidswitch.models.db import RequestLog, User, VoidToken
from voidswitch.models.schemas import (
    LoginTokenStatus,
    LoginTokenWithSecret,
    UserOut,
    VoidTokenCreate,
    VoidTokenOut,
    VoidTokenUpdate,
    VoidTokenWithSecret,
)

router = APIRouter(prefix="/api/me", tags=["me"])


def _require_login_token_user(user: User) -> None:
    if not is_staff(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Login tokens are only available to staff.")


@router.get("", response_model=UserOut)
async def my_profile(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/login-token", response_model=LoginTokenStatus)
async def my_login_token(user: User = Depends(get_current_user)) -> LoginTokenStatus:
    _require_login_token_user(user)
    return LoginTokenStatus(
        enabled=bool(user.login_token_hash),
        prefix=user.login_token_prefix,
    )


@router.post("/login-token/rotate", response_model=LoginTokenWithSecret)
async def rotate_my_login_token(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> LoginTokenWithSecret:
    _require_login_token_user(user)
    secret = generate_login_token()
    user.login_token_hash = hash_token(secret)
    user.login_token_prefix = token_fingerprint(secret)
    await session.flush()
    await record_audit(
        session,
        action=AuditAction.ME_LOGIN_TOKEN_ROTATE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="user",
        target_id=user.id,
        detail={"prefix": user.login_token_prefix},
        ip=request.client.host if request.client else None,
        scope=AuditScope.SELF.value,
    )
    return LoginTokenWithSecret(enabled=True, prefix=user.login_token_prefix, token=secret)


@router.get("/tokens", response_model=list[VoidTokenOut])
async def my_tokens(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[VoidToken]:
    rows = (
        (
            await session.execute(
                select(VoidToken)
                .where(VoidToken.user_id == user.id, VoidToken.deleted.is_(False))
                .order_by(VoidToken.id)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.post("/tokens", response_model=VoidTokenWithSecret, status_code=status.HTTP_201_CREATED)
async def create_my_token(
    body: VoidTokenCreate,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> VoidTokenWithSecret:
    secret = generate_void_token()
    token = VoidToken(
        user_id=user.id,
        name=body.name,
        token_hash=hash_token(secret),
        token_prefix=token_fingerprint(secret),
        allowed_models=body.allowed_models,
        rpm_limit=body.rpm_limit,
        daily_quota=body.daily_quota,
        expires_at=body.expires_at,
    )
    session.add(token)
    await session.flush()
    await record_audit(
        session,
        action=AuditAction.ME_TOKEN_CREATE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="token",
        target_id=token.id,
        detail={"name": token.name, "prefix": token.token_prefix},
        # The plaintext secret is shown to the user exactly once; keep an
        # owner-revealable copy so a lost token can be recovered/audited.
        sensitive={"token": secret, "name": token.name},
        secret_key=settings.server.secret_key,
        ip=request.client.host if request.client else None,
        scope=AuditScope.SELF.value,
    )
    # The plaintext secret lives only here; the ORM row stores its hash. Build
    # the public view from the row, then attach the one-time secret.
    return VoidTokenWithSecret(**VoidTokenOut.model_validate(token).model_dump(), token=secret)


@router.patch("/tokens/{token_id}", response_model=VoidTokenOut)
async def update_my_token(
    token_id: int,
    body: VoidTokenUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> VoidToken:
    token = await session.get(VoidToken, token_id)
    if token is None or token.user_id != user.id or token.deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token not found.")
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(token, field, value)
    if "enabled" in changes:
        token.auto_disabled = False
    await session.flush()
    await record_audit(
        session,
        action=AuditAction.ME_TOKEN_UPDATE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="token",
        target_id=token.id,
        detail={"name": token.name, "changes": body.model_dump(mode="json", exclude_unset=True)},
        ip=request.client.host if request.client else None,
        scope=AuditScope.SELF.value,
    )
    return token


@router.post("/tokens/{token_id}/rotate", response_model=VoidTokenWithSecret)
async def rotate_my_token(
    token_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> VoidTokenWithSecret:
    token = await session.get(VoidToken, token_id)
    if token is None or token.user_id != user.id or token.deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token not found.")
    secret = generate_void_token()
    token.token_hash = hash_token(secret)
    token.token_prefix = token_fingerprint(secret)
    await session.flush()
    await record_audit(
        session,
        action=AuditAction.ME_TOKEN_ROTATE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="token",
        target_id=token.id,
        detail={"name": token.name, "prefix": token.token_prefix},
        sensitive={"token": secret, "name": token.name},
        secret_key=settings.server.secret_key,
        ip=request.client.host if request.client else None,
        scope=AuditScope.SELF.value,
    )
    return VoidTokenWithSecret(**VoidTokenOut.model_validate(token).model_dump(), token=secret)


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_token(
    token_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    token = await session.get(VoidToken, token_id)
    if token is None or token.user_id != user.id or token.deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token not found.")
    await record_audit(
        session,
        action=AuditAction.ME_TOKEN_DELETE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="token",
        target_id=token.id,
        detail={"name": token.name, "prefix": token.token_prefix},
        ip=request.client.host if request.client else None,
        scope=AuditScope.SELF.value,
    )
    token.enabled = False
    token.auto_disabled = False
    token.deleted = True
    token.deleted_at = dt.datetime.now(dt.UTC)


@router.get("/usage")
async def my_usage(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    totals = (
        await session.execute(
            select(
                func.count(RequestLog.id),
                func.coalesce(func.sum(RequestLog.total_tokens), 0),
            ).where(RequestLog.user_sub == user.sub)
        )
    ).one()
    token_count = (
        await session.execute(
            select(func.count(VoidToken.id)).where(
                VoidToken.user_id == user.id, VoidToken.deleted.is_(False)
            )
        )
    ).scalar_one()
    return {
        "requests": int(totals[0] or 0),
        "tokens": int(totals[1] or 0),
        "token_count": int(token_count or 0),
    }
