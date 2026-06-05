"""Audit logging helper."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.security import encrypt_secret
from voidswitch.models.db import AuditLog


async def record_audit(
    session: AsyncSession,
    *,
    action: str,
    actor_sub: str | None = None,
    actor_name: str | None = None,
    target_type: str | None = None,
    target_id: str | int | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
    sensitive: dict[str, Any] | None = None,
    secret_key: str | None = None,
    scope: str = "admin",
) -> None:
    """Append an audit entry. Caller owns the transaction.

    ``scope`` classifies the entry so the dashboard can separate administrative
    actions from ordinary self-service ones:

    * ``"admin"`` — an action on the management surface (providers, keys, proxies,
      settings, other users' resources). Default, so existing call sites stay
      administrative without change.
    * ``"self"`` — a user acting on their own account (signing in/out, managing
      their own Void-Tokens). Surfaced in the audit trail but hidden when the
      viewer filters to administrative actions only.

    ``sensitive`` carries owner-only context (e.g. plaintext keys). It is stored
    encrypted at rest and only ever decrypted for owners on an explicit request;
    it is never returned in the normal audit listing. Encryption requires
    ``secret_key`` (the app secret) — without it the sensitive blob is dropped.
    """
    sensitive_ciphertext: str | None = None
    if sensitive and secret_key:
        sensitive_ciphertext = encrypt_secret(json.dumps(sensitive), secret=secret_key)

    session.add(
        AuditLog(
            action=action,
            actor_sub=actor_sub,
            actor_name=actor_name,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            detail=detail or {},
            ip=ip,
            sensitive_ciphertext=sensitive_ciphertext,
            scope=scope,
        )
    )
