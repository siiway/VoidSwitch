"""Audit logging helper.

A single ``record_audit`` entry point writes one row to ``audit_logs``. The
goal is a *uniform* shape across the whole project so the dashboard can render,
filter, and reason about the trail consistently:

* ``action``  — a dotted ``resource.verb`` string drawn from :class:`AuditAction`.
* ``scope``   — one of :class:`AuditScope` (``admin`` / ``self`` / ``system``).
* ``actor_*`` — *always* a stable ``name#id`` display label (via
  :func:`voidswitch.core.auth.actor_display_name`) plus the raw subject.
* ``detail``  — a small JSON object of **non-secret** context, e.g. the actual
  changed values (not just their field names).
* ``sensitive`` — owner-only context (plaintext keys/tokens, secret headers).
  Stored Fernet-encrypted and only ever decrypted for a (co-)owner on an
  explicit, itself-audited "reveal" request.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.security import encrypt_secret
from voidswitch.models.db import AuditLog


class AuditScope(StrEnum):
    """Classifies an audit entry so the dashboard can group/filter the trail."""

    # An action on the management surface (providers, keys, proxies, settings,
    # other users' resources). The default for staff operations.
    ADMIN = "admin"
    # A user acting on their own account (sign-in/out, own Void-Tokens, managing
    # the resources they personally added). Hidden when filtering to admin only.
    SELF = "self"
    # An automated action performed by a background task (e.g. log retention),
    # with no human actor.
    SYSTEM = "system"


# Synthetic actor label for entries written by background tasks (no real user).
SYSTEM_ACTOR_NAME = "system"
SYSTEM_ACTOR_SUB = "system"


class AuditAction(StrEnum):
    """Canonical ``resource.verb`` action names.

    Centralised so the set is discoverable, typo-proof, and stable for the
    dashboard's action filter. The string values are the wire/stored format.
    """

    # Authentication / session (scope: self)
    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    AUTH_DEV_LOGIN = "auth.dev_login"

    # A user's own Void-Tokens (scope: self)
    ME_TOKEN_CREATE = "me.token.create"
    ME_TOKEN_UPDATE = "me.token.update"
    ME_TOKEN_ROTATE = "me.token.rotate"
    ME_TOKEN_DELETE = "me.token.delete"

    # Void-Tokens managed by an owner for any user
    TOKEN_CREATE = "token.create"
    TOKEN_UPDATE = "token.update"
    TOKEN_DELETE = "token.delete"

    # Providers
    PROVIDER_CREATE = "provider.create"
    PROVIDER_UPDATE = "provider.update"
    PROVIDER_DELETE = "provider.delete"
    PROVIDER_KEY_API_ENABLE = "provider.key_api_enable"
    PROVIDER_KEY_API_ROTATE = "provider.key_api_rotate"
    PROVIDER_KEY_API_DISABLE = "provider.key_api_disable"
    PROVIDER_KEY_API_REVEAL = "provider.key_api_reveal"

    # Upstream API keys
    KEY_ADD = "key.add"
    KEY_UPDATE = "key.update"
    KEY_DELETE = "key.delete"
    KEY_CLEANUP = "key.cleanup"
    KEY_REORDER = "key.reorder"
    KEY_REVEAL = "key.reveal"
    KEY_OAUTH_START = "key.oauth_start"
    KEY_OAUTH_ADD = "key.oauth_add"

    # Proxies
    PROXY_ADD = "proxy.add"
    PROXY_UPDATE = "proxy.update"
    PROXY_DELETE = "proxy.delete"
    PROXY_PROBE = "proxy.probe"

    # Model catalog
    MODEL_UPSERT = "model.upsert"
    MODEL_BATCH_UPDATE = "model.batch_update"
    MODEL_SYNC = "model.sync"
    MODEL_CLEAN_UNSERVED = "model.clean_unserved"
    MODEL_DELETE = "model.delete"

    # Users & settings
    USER_UPDATE = "user.update"
    SETTINGS_UPDATE = "settings.update"

    # Announcements
    ANNOUNCEMENT_CREATE = "announcement.create"
    ANNOUNCEMENT_UPDATE = "announcement.update"
    ANNOUNCEMENT_DELETE = "announcement.delete"

    # Role groups ("身份组")
    ROLE_GROUP_CREATE = "role_group.create"
    ROLE_GROUP_UPDATE = "role_group.update"
    ROLE_GROUP_DELETE = "role_group.delete"
    ROLE_GROUP_MEMBER_REMOVE = "role_group.member_remove"

    # Audit / housekeeping
    AUDIT_REVEAL = "audit.reveal"
    LOGS_CLEANUP = "logs.cleanup"


def split_sensitive(
    values: dict[str, Any], sensitive_keys: set[str]
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Partition ``values`` into a public detail dict and a sensitive dict.

    Keys listed in ``sensitive_keys`` are moved into the second dict (owner-only,
    stored encrypted); everything else stays in the public detail. Returns
    ``(public, sensitive_or_None)``.
    """
    public: dict[str, Any] = {}
    sensitive: dict[str, Any] = {}
    for key, value in values.items():
        if key in sensitive_keys:
            sensitive[key] = value
        else:
            public[key] = value
    return public, (sensitive or None)


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
    user_agent: str | None = None,
    sensitive: dict[str, Any] | None = None,
    secret_key: str | None = None,
    scope: str = AuditScope.ADMIN.value,
) -> None:
    """Append an audit entry. Caller owns the transaction.

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
            action=str(action),
            actor_sub=actor_sub,
            actor_name=actor_name,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            detail=detail or {},
            ip=ip,
            user_agent=user_agent,
            sensitive_ciphertext=sensitive_ciphertext,
            scope=str(scope),
        )
    )
