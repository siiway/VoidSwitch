"""Admin: system information and background task status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from voidswitch import __version__
from voidswitch.core.auth import require_staff
from voidswitch.models.db import User
from voidswitch.services.providers.registry import adapter_catalog

router = APIRouter(prefix="/api/admin/system", tags=["admin:system"])


@router.get("")
async def system_info(
    request: Request,
    _: User = Depends(require_staff),
) -> dict[str, object]:
    manager = getattr(request.app.state, "task_manager", None)
    return {
        "version": __version__,
        "adapters": adapter_catalog(),
        "tasks": manager.status() if manager is not None else [],
    }
