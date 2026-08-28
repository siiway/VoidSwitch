"""Import upstream credentials from external tools' auth files.

Two ecosystems store subscription/OAuth accounts in a shape we can ingest:

* **CLIProxyAPI** (``cpa``) — one JSON file per account under its ``auths/``
  directory. The credential fields are *flattened* at the top level
  (``access_token`` / ``refresh_token`` / ``id_token`` / ``api_key``), with a
  ``type`` discriminator ("claude", "codex", "gemini", …) and, for OAuth
  accounts, an ``expired`` RFC3339 expiry timestamp.
* **sub2api** — its admin data export, ``{"accounts": [...], ...}``, or a single
  account object. Each account has ``platform`` (claude/openai/…), ``type``
  (``oauth`` / ``api_key`` / ``cookie``) and a nested ``credentials`` object.
  Only the *export* endpoint (or ``accounts export``) includes real secret
  values — ordinary API responses redact them, so those cannot be imported.

Every parsed account becomes one provider key. OAuth accounts are stored as a
Claude-style credential *bundle* (``{access_token, refresh_token, expires_at}``);
api-key / cookie / static accounts store their raw secret verbatim.

Grok (xAI) accounts are special. The console.x.ai ``grok`` adapter authenticates
with the raw browser ``sso`` cookie token, so we extract that token
(``sso_token`` / ``ssoToken`` / ``sso``) in preference to anything else — such a
key belongs on a ``grok`` provider. When no SSO cookie is present we instead
build an xAI OAuth bundle from whatever ``refresh_token`` / ``access_token`` the
export carries (sub2api converts the SSO cookie into a refresh token
server-side and exports only that); such a key belongs on an ``xai`` provider,
which mints and auto-refreshes the access token via
:mod:`voidswitch.services.xai_oauth`.

Claude and xAI OAuth bundles are auto-refreshed by VoidSwitch (see
:mod:`voidswitch.services.oauth_tokens` and
:mod:`voidswitch.services.xai_oauth`). Other platforms' OAuth tokens are
imported as-is and remain usable until they expire; refreshing them is the
operator's responsibility.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import KeyStatus
from voidswitch.core.audit import AuditAction, record_audit
from voidswitch.core.config import Settings
from voidswitch.core.security import encrypt_secret, hash_token
from voidswitch.models.db import ApiKey, Provider
from voidswitch.models.schemas import ApiKeyOut, AuthImportResult, AuthImportSkipped
from voidswitch.services import keymgmt

# Map an external platform/type discriminator onto a canonical label so the
# same provider reported by either tool aggregates together (cpa calls OpenAI
# "codex"; sub2api calls it "openai").
_PLATFORM_ALIASES = {
    "codex": "openai",
    "chatgpt": "openai",
    "xai": "grok",
}


def _canon_platform(value: str | None) -> str:
    label = (value or "unknown").strip().lower() or "unknown"
    return _PLATFORM_ALIASES.get(label, label)


@dataclass(slots=True)
class ParsedAccount:
    source: str  # "cpa" | "sub2api"
    platform: str
    account_type: str  # "oauth" | "api_key" | "cookie" | "token"
    secret: str  # a bundle JSON string (is_bundle) or a raw token
    is_bundle: bool = False
    label: str | None = None  # email / account name, for the key note


@dataclass(slots=True)
class SkippedAccount:
    source: str
    platform: str
    reason: str


@dataclass(slots=True)
class _Parsed:
    accounts: list[ParsedAccount] = field(default_factory=list)
    skipped: list[SkippedAccount] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Value normalisation
# --------------------------------------------------------------------------- #


def _to_epoch_seconds(value: object) -> float | None:
    """Normalise a mixed expiry representation to float UNIX epoch *seconds*.

    Handles a numeric epoch in seconds or milliseconds, a numeric string, and an
    RFC3339/ISO-8601 timestamp (cpa's ``expired``). Returns None when empty or
    unparseable, so a missing/garbled expiry simply yields a bundle without one.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        return seconds / 1000.0 if seconds > 1e11 else seconds
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            seconds = float(text)
        except ValueError:
            pass
        else:
            return seconds / 1000.0 if seconds > 1e11 else seconds
        iso = text.replace("Z", "+00:00") if text.endswith("Z") else text
        try:
            parsed = dt.datetime.fromisoformat(iso)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        return parsed.timestamp()
    return None


def _build_bundle(access: object, refresh: object, expires_at: float | None) -> str:
    """Serialise an OAuth credential bundle.

    Either half may be absent: a bundle with only a ``refresh_token`` (no access
    token yet) is valid for platforms that mint the access token on demand
    (see :mod:`voidswitch.services.xai_oauth`).
    """
    bundle: dict[str, object] = {}
    if isinstance(access, str) and access:
        bundle["access_token"] = access
    if isinstance(refresh, str) and refresh:
        bundle["refresh_token"] = refresh
    if expires_at is not None:
        bundle["expires_at"] = expires_at
    return json.dumps(bundle)


def _str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


# Field-name variants that carry a raw grok/xAI SSO cookie token across the
# tools we ingest (cpa flattens them at the top level; sub2api nests them under
# ``credentials``). The grok console adapter consumes this token directly.
_SSO_FIELDS = ("sso_token", "ssoToken", "sso")


def _normalize_sso(value: str) -> str:
    """Strip an optional leading ``sso=`` cookie prefix from an SSO token.

    Some exporters store the raw cookie pair (``sso=<jwt>``) rather than just the
    value. The grok adapter also strips this defensively, but normalising at
    import keeps the stored secret and its dedup hash canonical.
    """
    token = value.strip()
    if token.startswith("sso="):
        token = token[len("sso=") :].strip()
    return token


def _extract_sso(*containers: dict[Any, Any]) -> str | None:
    """Return the first non-empty, normalised SSO token found in ``containers``."""
    for container in containers:
        for field_name in _SSO_FIELDS:
            raw = _str(container.get(field_name))
            if raw:
                token = _normalize_sso(raw)
                if token:
                    return token
    return None


# Field-name variants that carry an xAI OAuth refresh token. sub2api converts an
# SSO cookie to a refresh token server-side and exports only this, so a grok
# account with no raw SSO cookie still yields a usable (auto-refreshed) bundle.
_REFRESH_FIELDS = ("refresh_token", "refreshToken", "rt", "RT")


def _extract_refresh(*containers: dict[Any, Any]) -> str | None:
    """Return the first non-empty xAI refresh token found in ``containers``."""
    for container in containers:
        for field_name in _REFRESH_FIELDS:
            raw = _str(container.get(field_name))
            if raw:
                return raw
    return None


# --------------------------------------------------------------------------- #
# Per-account parsers
# --------------------------------------------------------------------------- #


def _parse_sub2api_account(acc: dict[Any, Any]) -> ParsedAccount | SkippedAccount:
    platform = _canon_platform(_str(acc.get("platform")))
    atype = (_str(acc.get("type")) or "").lower()
    creds = acc.get("credentials")
    creds = creds if isinstance(creds, dict) else {}
    label = _str(acc.get("name")) or _str(acc.get("email")) or _str(creds.get("email"))

    # Grok's console adapter authenticates with the raw SSO cookie token, not an
    # xAI OAuth bundle. Prefer it whenever the export carries one (regardless of
    # the account's declared ``type``).
    if platform == "grok":
        sso = _extract_sso(creds, acc)
        if sso:
            return ParsedAccount("sub2api", platform, "sso", sso, False, label)
        # No raw SSO cookie — fall back to an xAI OAuth bundle. sub2api commonly
        # exports only a refresh_token (the SSO cookie was consumed server-side);
        # the xai adapter mints/refreshes the access token from it on demand.
        refresh = _extract_refresh(creds, acc)
        access = _str(creds.get("access_token"))
        if refresh or access:
            secret = _build_bundle(access, refresh, _to_epoch_seconds(creds.get("expires_at")))
            return ParsedAccount("sub2api", platform, "oauth", secret, True, label)
        if atype == "oauth":
            return SkippedAccount(
                "sub2api",
                platform,
                "Grok account has no SSO cookie, access_token or refresh_token",
            )

    if atype == "oauth":
        access = _str(creds.get("access_token"))
        if not access:
            return SkippedAccount("sub2api", platform, "OAuth account has no access_token")
        secret = _build_bundle(
            access, creds.get("refresh_token"), _to_epoch_seconds(creds.get("expires_at"))
        )
        return ParsedAccount("sub2api", platform, "oauth", secret, True, label)
    if atype == "api_key":
        raw = _str(creds.get("api_key"))
        if not raw:
            return SkippedAccount("sub2api", platform, "API-key account has no api_key")
        return ParsedAccount("sub2api", platform, "api_key", raw, False, label)
    if atype == "cookie":
        raw = _str(creds.get("session_key"))
        if not raw:
            return SkippedAccount("sub2api", platform, "Cookie account has no session_key")
        return ParsedAccount("sub2api", platform, "cookie", raw, False, label)

    # Unknown type: best-effort by inspecting the credentials that are present.
    access = _str(creds.get("access_token"))
    if access:
        secret = _build_bundle(
            access, creds.get("refresh_token"), _to_epoch_seconds(creds.get("expires_at"))
        )
        return ParsedAccount("sub2api", platform, "oauth", secret, True, label)
    raw = _str(creds.get("api_key")) or _str(creds.get("session_key"))
    if raw:
        return ParsedAccount("sub2api", platform, "token", raw, False, label)
    return SkippedAccount(
        "sub2api", platform, f"Unsupported account type '{atype or 'unknown'}' with no secret"
    )


def _parse_cpa_account(obj: dict[Any, Any]) -> ParsedAccount | SkippedAccount:
    platform = _canon_platform(_str(obj.get("type")))
    label = _str(obj.get("email")) or _str(obj.get("account")) or _str(obj.get("name"))

    # Grok's console adapter uses the raw SSO cookie token. cpa xai auth files
    # flatten it at the top level (often alongside an unrelated xAI OAuth
    # access/refresh pair), so extract it before the generic OAuth handling.
    if platform == "grok":
        sso = _extract_sso(obj)
        if sso:
            return ParsedAccount("cpa", platform, "sso", sso, False, label)
        # No raw SSO cookie — fall back to an xAI OAuth bundle. Handle the
        # refresh-only case here (the generic branch below requires an
        # access_token); an access+refresh pair falls through to it unchanged.
        refresh = _extract_refresh(obj)
        if refresh and not _str(obj.get("access_token")):
            expiry = (
                obj.get("expired")
                or obj.get("expire")
                or obj.get("expires")
                or obj.get("expires_at")
            )
            secret = _build_bundle(None, refresh, _to_epoch_seconds(expiry))
            return ParsedAccount("cpa", platform, "oauth", secret, True, label)

    access = _str(obj.get("access_token"))
    if access:
        expiry = (
            obj.get("expired") or obj.get("expire") or obj.get("expires") or obj.get("expires_at")
        )
        secret = _build_bundle(access, obj.get("refresh_token"), _to_epoch_seconds(expiry))
        return ParsedAccount("cpa", platform, "oauth", secret, True, label)

    raw = _str(obj.get("api_key"))
    if raw:
        return ParsedAccount("cpa", platform, "api_key", raw, False, label)
    # Some cpa executors keep only an id_token (used bearer-style). Store it raw.
    raw = _str(obj.get("id_token"))
    if raw:
        return ParsedAccount("cpa", platform, "token", raw, False, label)
    return SkippedAccount("cpa", platform, "No access_token / api_key / id_token found")


def _parse_object(obj: dict[Any, Any]) -> _Parsed:
    """Route a single JSON object to the right parser by its shape."""
    out = _Parsed()
    accounts = obj.get("accounts")
    if isinstance(accounts, list):
        # sub2api data export.
        for item in accounts:
            if isinstance(item, dict):
                _append(out, _parse_sub2api_account(item))
            else:
                out.skipped.append(SkippedAccount("sub2api", "unknown", "Account is not an object"))
        return out
    if isinstance(obj.get("credentials"), dict):
        _append(out, _parse_sub2api_account(obj))
        return out
    _append(out, _parse_cpa_account(obj))
    return out


def _append(out: _Parsed, item: ParsedAccount | SkippedAccount) -> None:
    if isinstance(item, ParsedAccount):
        out.accounts.append(item)
    else:
        out.skipped.append(item)


def parse_source(blob: str) -> _Parsed:
    """Parse one uploaded/pasted file's text into accounts + skips.

    Accepts a single JSON object, a JSON array, or JSONL (one JSON value per
    line). Blank input and unparseable text yield an empty result.
    """
    out = _Parsed()
    text = (blob or "").strip()
    if not text:
        return out
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _parse_jsonl(text)
    _ingest_value(out, data)
    return out


def _ingest_value(out: _Parsed, data: object) -> None:
    if isinstance(data, dict):
        merged = _parse_object(data)
        out.accounts.extend(merged.accounts)
        out.skipped.extend(merged.skipped)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                merged = _parse_object(item)
                out.accounts.extend(merged.accounts)
                out.skipped.extend(merged.skipped)
            else:
                out.skipped.append(SkippedAccount("unknown", "unknown", "Entry is not an object"))


def _parse_jsonl(text: str) -> _Parsed:
    out = _Parsed()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            out.skipped.append(SkippedAccount("unknown", "unknown", "Line is not valid JSON"))
            continue
        _ingest_value(out, data)
    return out


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #


def _key_note(acc: ParsedAccount, note: str | None) -> str:
    bits = [f"{acc.source}:{acc.platform}"]
    if acc.label:
        bits.append(acc.label)
    if note:
        bits.append(note)
    return " · ".join(bits)


async def import_credentials(
    session: AsyncSession,
    provider: Provider,
    *,
    sources: list[str],
    pool: str,
    note: str | None,
    actor: keymgmt.Actor,
    settings: Settings,
) -> AuthImportResult:
    """Parse the supplied auth files and store their credentials as keys.

    De-duplicates against the provider's existing keys and within the batch by
    secret hash. Records a single owner-revealable audit entry for the import.
    """
    parsed = _Parsed()
    for blob in sources:
        merged = parse_source(blob)
        parsed.accounts.extend(merged.accounts)
        parsed.skipped.extend(merged.skipped)

    existing_hashes = {
        h
        for (h,) in (
            await session.execute(select(ApiKey.key_hash).where(ApiKey.provider_id == provider.id))
        ).all()
    }
    max_order = (
        await session.execute(
            select(func.max(ApiKey.sort_order)).where(ApiKey.provider_id == provider.id)
        )
    ).scalar()
    next_order = (max_order or 0) + 1

    created: list[ApiKey] = []
    seen: set[str] = set()
    sensitive_keys: list[dict[str, str | None]] = []
    by_platform: dict[str, int] = {}
    by_source: dict[str, int] = {}
    duplicates = 0

    for acc in parsed.accounts:
        digest = hash_token(acc.secret)
        if digest in existing_hashes or digest in seen:
            duplicates += 1
            continue
        seen.add(digest)
        prev = (
            keymgmt.oauth_preview(json.loads(acc.secret))
            if acc.is_bundle
            else keymgmt.preview(acc.secret)
        )
        note_text = _key_note(acc, note)
        key = ApiKey(
            provider_id=provider.id,
            key_ciphertext=encrypt_secret(acc.secret, secret=settings.server.secret_key),
            key_hash=digest,
            key_preview=prev,
            status=KeyStatus.ACTIVE.value,
            weight=1,
            note=note_text,
            pool=pool or "",
            sort_order=next_order,
            added_by=actor.user_id,
            added_by_name=actor.name,
        )
        next_order += 1
        session.add(key)
        created.append(key)
        by_platform[acc.platform] = by_platform.get(acc.platform, 0) + 1
        by_source[acc.source] = by_source.get(acc.source, 0) + 1
        sensitive_keys.append(
            {"key": acc.secret, "preview": prev, "note": note_text, "pool": pool or ""}
        )

    if created:
        await session.flush()
        await record_audit(
            session,
            action=AuditAction.KEY_IMPORT,
            actor_sub=actor.sub,
            actor_name=actor.name,
            target_type="provider",
            target_id=provider.id,
            detail={
                "provider_name": provider.name,
                "imported": len(created),
                "duplicates": duplicates,
                "unusable": len(parsed.skipped),
                "pool": pool or "",
                "by_platform": by_platform,
                "by_source": by_source,
                "previews": [k["preview"] for k in sensitive_keys],
            },
            sensitive={"keys": sensitive_keys},
            secret_key=settings.server.secret_key,
            ip=actor.ip,
            user_agent=actor.user_agent,
            scope=actor.audit_scope,
        )

    return AuthImportResult(
        imported=len(created),
        duplicates=duplicates,
        unusable=len(parsed.skipped),
        by_platform=by_platform,
        by_source=by_source,
        skipped=[
            AuthImportSkipped(source=s.source, platform=s.platform, reason=s.reason)
            for s in parsed.skipped
        ],
        keys=[ApiKeyOut.model_validate(k) for k in created],
    )
