"""Owner-only key lookup across provider keys and Void-Tokens."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.audit import AuditAction, record_audit
from voidswitch.core.auth import actor_display_name, require_owner
from voidswitch.core.config import Settings, get_settings
from voidswitch.core.database import get_session
from voidswitch.core.security import decrypt_secret, hash_token
from voidswitch.models.db import ApiKey, Provider, User, VoidToken
from voidswitch.models.schemas import (
    KeyRevealProviderMatch,
    KeyRevealRequest,
    KeyRevealResult,
    KeyRevealTokenMatch,
)
from voidswitch.services import oauth_tokens

router = APIRouter(prefix="/api/admin/reveal", tags=["admin:reveal"])

SCOPES = {"provider", "token", "all"}


def _owner_label(user: User | None) -> str | None:
    if user is None:
        return None
    label = user.username or user.name or user.email or user.sub
    return f"{label}#{user.id}" if label else f"#{user.id}"


def _provider_key_matches(provider: Provider, plaintext: str, raw: str) -> bool:
    if plaintext == raw:
        return True
    # Partial reveal: `…`, `...`, or `*` acts as a wildcard — e.g.
    # `sk-S…TAmY` matches any key that starts with `sk-S` and ends with `TAmY`.
    for char in ("…", "...", "*"):
        prefix, sep, suffix = raw.partition(char)
        if not sep:
            continue
        matched = (
            (prefix and suffix and plaintext.startswith(prefix) and plaintext.endswith(suffix))
            or (prefix and not suffix and plaintext.startswith(prefix))
            or (suffix and not prefix and plaintext.endswith(suffix))
        )
        if matched:
            return True
    if provider.type != "claude-code":
        return False
    bundle = oauth_tokens.parse_bundle(plaintext)
    if bundle is None:
        return False
    return raw in {str(bundle.get("access_token") or ""), str(bundle.get("refresh_token") or "")}


@router.post("/key", response_model=KeyRevealResult)
async def reveal_key_search(
    body: KeyRevealRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_owner),
    settings: Settings = Depends(get_settings),
) -> KeyRevealResult:
    raw = body.key.strip()
    scope = body.scope.strip().lower()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Key is required.")
    if scope not in SCOPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid reveal scope.")

    provider_matches: list[KeyRevealProviderMatch] = []
    token_matches: list[KeyRevealTokenMatch] = []

    if scope in ("provider", "all"):
        rows = (
            await session.execute(
                select(ApiKey, Provider)
                .join(Provider, Provider.id == ApiKey.provider_id)
                .order_by(Provider.id, ApiKey.sort_order, ApiKey.id)
            )
        ).all()
        positions: dict[int, int] = {}
        for key, provider in rows:
            positions[provider.id] = positions.get(provider.id, 0) + 1
            try:
                plaintext = decrypt_secret(key.key_ciphertext, secret=settings.server.secret_key)
            except Exception:
                continue
            if _provider_key_matches(provider, plaintext, raw):
                provider_matches.append(
                    KeyRevealProviderMatch(
                        provider_id=provider.id,
                        provider_name=provider.name,
                        key_id=key.id,
                        position=positions[provider.id],
                        preview=key.key_preview,
                        comment=key.note,
                        pool=key.pool or "",
                        added_by_name=key.added_by_name,
                    )
                )

    if scope in ("token", "all"):
        digest = hash_token(raw)
        rows = (
            await session.execute(
                select(VoidToken, User)
                .join(User, User.id == VoidToken.user_id)
                .where(VoidToken.token_hash == digest)
                .order_by(VoidToken.id)
            )
        ).all()
        for token, owner in rows:
            token_matches.append(
                KeyRevealTokenMatch(
                    token_id=token.id,
                    name=token.name,
                    owner_id=owner.id,
                    owner_name=_owner_label(owner),
                    total_requests=token.total_requests,
                    total_tokens=token.total_tokens,
                    enabled=token.enabled,
                    created_at=token.created_at,
                    deleted=token.deleted,
                )
            )
        # Partial reveal for tokens: `…`/`...`/`*` only matches the prefix
        # (``token_prefix``) since tokens are stored as hashes and cannot be
        # decrypted.  Suffix-only patterns are not supported for tokens.
        if not rows:
            for char in ("…", "...", "*"):
                prefix, sep, suffix = raw.partition(char)
                if not sep or not prefix or suffix:
                    continue
                partial_rows = (
                    await session.execute(
                        select(VoidToken, User)
                        .join(User, User.id == VoidToken.user_id)
                        .where(VoidToken.token_prefix.like(f"{prefix}%"))
                        .order_by(VoidToken.id)
                    )
                ).all()
                for token, owner in partial_rows:
                    token_matches.append(
                        KeyRevealTokenMatch(
                            token_id=token.id,
                            name=token.name,
                            owner_id=owner.id,
                            owner_name=_owner_label(owner),
                            total_requests=token.total_requests,
                            total_tokens=token.total_tokens,
                            enabled=token.enabled,
                            created_at=token.created_at,
                            deleted=token.deleted,
                        )
                    )
                break

    await record_audit(
        session,
        action=AuditAction.KEY_SEARCH_REVEAL,
        actor_sub=actor.sub,
        actor_name=actor_display_name(actor),
        target_type="key",
        detail={
            "scope": scope,
            "provider_matches": len(provider_matches),
            "token_matches": len(token_matches),
        },
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return KeyRevealResult(
        provider_matches=provider_matches,
        token_matches=token_matches,
    )
