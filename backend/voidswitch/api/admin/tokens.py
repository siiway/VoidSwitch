"""Admin: manage Void-Tokens across all users."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.auth import require_staff
from voidswitch.core.database import get_session
from voidswitch.core.security import generate_void_token, hash_token, token_fingerprint
from voidswitch.models.db import User, VoidToken
from voidswitch.models.schemas import (
    VoidTokenCreate,
    VoidTokenOut,
    VoidTokenUpdate,
    VoidTokenWithSecret,
)

router = APIRouter(prefix="/api/admin/tokens", tags=["admin:tokens"])


@router.get("", response_model=list[VoidTokenOut])
async def list_tokens(
    user_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> list[VoidToken]:
    stmt = select(VoidToken).order_by(VoidToken.id)
    if user_id is not None:
        stmt = stmt.where(VoidToken.user_id == user_id)
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


@router.post("", response_model=VoidTokenWithSecret, status_code=status.HTTP_201_CREATED)
async def create_token(
    body: VoidTokenCreate,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_staff),
) -> VoidTokenWithSecret:
    target_user_id = body.user_id or actor.id
    owner = await session.get(User, target_user_id)
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Target user not found.")
    secret = generate_void_token()
    token = VoidToken(
        user=owner,
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
    # Plaintext secret returned exactly once; ORM stores only its hash.
    return VoidTokenWithSecret(**VoidTokenOut.model_validate(token).model_dump(), token=secret)


@router.patch("/{token_id}", response_model=VoidTokenOut)
async def update_token(
    token_id: int,
    body: VoidTokenUpdate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> VoidToken:
    token = await session.get(VoidToken, token_id)
    if token is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token not found.")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(token, field, value)
    await session.flush()
    return token


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_token(
    token_id: int,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> None:
    token = await session.get(VoidToken, token_id)
    if token is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token not found.")
    await session.delete(token)
