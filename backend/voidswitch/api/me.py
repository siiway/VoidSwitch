"""Member self-service: fetch your Void-Token(s) and usage/quota."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.audit import record_audit
from voidswitch.core.auth import actor_display_name, get_current_user
from voidswitch.core.database import get_session
from voidswitch.core.security import (
    generate_void_token,
    hash_token,
    token_fingerprint,
)
from voidswitch.models.db import RequestLog, User, VoidToken
from voidswitch.models.schemas import (
    UserOut,
    VoidTokenCreate,
    VoidTokenOut,
    VoidTokenUpdate,
    VoidTokenWithSecret,
)

router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("", response_model=UserOut)
async def my_profile(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/tokens", response_model=list[VoidTokenOut])
async def my_tokens(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[VoidToken]:
    rows = (
        (
            await session.execute(
                select(VoidToken).where(VoidToken.user_id == user.id).order_by(VoidToken.id)
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
        action="me.token.create",
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="token",
        target_id=token.id,
        detail={"name": token.name},
        ip=request.client.host if request.client else None,
        scope="self",
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
    if token is None or token.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token not found.")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(token, field, value)
    await session.flush()
    await record_audit(
        session,
        action="me.token.update",
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="token",
        target_id=token.id,
        detail={"changes": body.model_dump(mode="json", exclude_unset=True)},
        ip=request.client.host if request.client else None,
        scope="self",
    )
    return token


@router.post("/tokens/{token_id}/rotate", response_model=VoidTokenWithSecret)
async def rotate_my_token(
    token_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> VoidTokenWithSecret:
    token = await session.get(VoidToken, token_id)
    if token is None or token.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token not found.")
    secret = generate_void_token()
    token.token_hash = hash_token(secret)
    token.token_prefix = token_fingerprint(secret)
    await session.flush()
    await record_audit(
        session,
        action="me.token.rotate",
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="token",
        target_id=token.id,
        ip=request.client.host if request.client else None,
        scope="self",
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
    if token is None or token.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token not found.")
    await record_audit(
        session,
        action="me.token.delete",
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="token",
        target_id=token.id,
        detail={"name": token.name},
        ip=request.client.host if request.client else None,
        scope="self",
    )
    await session.delete(token)


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
        await session.execute(select(func.count(VoidToken.id)).where(VoidToken.user_id == user.id))
    ).scalar_one()
    return {
        "requests": int(totals[0] or 0),
        "tokens": int(totals[1] or 0),
        "token_count": int(token_count or 0),
    }
