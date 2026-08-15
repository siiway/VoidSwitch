"""Shared balance-reading logic.

Centralises how a fresh balance reading is applied to a key so the periodic
balance probe, the slow rescan, and the on-demand "refresh balance" admin
endpoint all behave identically: persist the latest balance detail, and (when
enabled) auto-disable empty keys / auto-re-enable recovered ones.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx

from voidswitch.constants import KeyStatus
from voidswitch.core.config import Settings
from voidswitch.core.security import decrypt_secret
from voidswitch.models.db import ApiKey, Provider
from voidswitch.services.providers.base import BaseProvider
from voidswitch.services.providers.registry import get_adapter


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def apply_balance(
    key: ApiKey,
    is_available: bool,
    detail: dict[str, Any],
    *,
    auto_disable: bool,
) -> None:
    """Apply a fresh balance reading to ``key`` in place.

    - Always records the latest ``detail`` and the check timestamp.
    - If the balance is available and the key was balance-disabled, re-enable it.
    - If empty and ``auto_disable`` is set, move the key to the matching disabled
      state (invalid on an auth error, otherwise insufficient_balance) and stamp
      ``disabled_since`` the first time it leaves the active state.
    """
    key.balance = detail
    key.last_checked_at = _utcnow()
    if is_available:
        # Recovered: bring a key back that was parked for an empty balance.
        if key.status == KeyStatus.INSUFFICIENT_BALANCE.value:
            key.status = KeyStatus.ACTIVE.value
            key.failed_count = 0
            key.disabled_reason = None
            key.disabled_since = None
        return
    if not auto_disable:
        return
    # A manually-disabled key is sticky: the on-demand "refresh balance" endpoint
    # probes any key (not just ACTIVE ones), and an operator's explicit disable
    # must not be silently flipped to insufficient_balance (which the rescan would
    # then auto-re-enable). The recovery branch above already refuses to
    # auto-re-enable such keys — keep the disable branch consistent.
    if key.status == KeyStatus.DISABLED.value:
        return
    if detail.get("error") == "authentication_error":
        key.status = KeyStatus.INVALID.value
        key.disabled_reason = "balance probe: authentication failed"
    else:
        key.status = KeyStatus.INSUFFICIENT_BALANCE.value
        key.disabled_reason = "balance probe: insufficient balance"
    if key.disabled_since is None:
        key.disabled_since = _utcnow()


async def refresh_key_balance(
    key: ApiKey,
    provider: Provider,
    client: httpx.AsyncClient,
    settings: Settings,
    *,
    auto_disable: bool,
    adapter: BaseProvider | None = None,
) -> bool | None:
    """Fetch and apply a single key's balance.

    Returns ``True``/``False`` for available/empty, or ``None`` when the provider
    has no balance endpoint or the read could not be parsed.
    """
    adapter = adapter or get_adapter(provider)
    if adapter.balance_url is None:
        return None
    plaintext = decrypt_secret(key.key_ciphertext, secret=settings.server.secret_key)
    result = await adapter.fetch_balance(client, plaintext)
    if result is None:
        return None
    is_available, detail = result
    apply_balance(key, is_available, detail, auto_disable=auto_disable)
    return is_available
