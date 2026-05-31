"""Admin: user listing and role/enable management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import Role
from voidswitch.core.auth import STAFF_ROLES, require_staff
from voidswitch.core.database import get_session
from voidswitch.models.db import User
from voidswitch.models.schemas import UserOut

router = APIRouter(prefix="/api/admin/users", tags=["admin:users"])


class UserUpdate(BaseModel):
    role: str | None = None
    enabled: bool | None = None


@router.get("", response_model=list[UserOut])
async def list_users(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> list[User]:
    rows = (await session.execute(select(User).order_by(User.id))).scalars().all()
    return list(rows)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: UserUpdate,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_staff),
) -> User:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")

    if body.role is not None:
        if body.role not in {r.value for r in Role}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid role.")
        # Only owners may grant or revoke staff-level roles.
        grants_staff = body.role in STAFF_ROLES or target.role in STAFF_ROLES
        if grants_staff and actor.role != Role.OWNER.value:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners can change staff roles.")
        if target.id == actor.id and body.role != Role.OWNER.value:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot demote yourself.")
        target.role = body.role

    if body.enabled is not None:
        if target.id == actor.id and not body.enabled:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot disable yourself.")
        target.enabled = body.enabled

    await session.flush()
    return target
