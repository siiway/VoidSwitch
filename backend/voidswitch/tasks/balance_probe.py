"""Background balance probe.

Periodically queries each provider's balance endpoint (where supported) for its
active keys and fast-fails keys that report no balance.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from voidswitch.constants import KeyStatus
from voidswitch.core.config import get_settings
from voidswitch.core.database import get_database
from voidswitch.core.logging import get_logger
from voidswitch.core.security import decrypt_secret
from voidswitch.models.db import ApiKey, Provider
from voidswitch.services import settings_store
from voidswitch.services.network import Route, get_pool
from voidswitch.services.providers.registry import get_adapter

log = get_logger("tasks.balance")


async def run_balance_probe() -> None:
    db = get_database()
    settings = get_settings()
    auto_disable = settings_store.get_bool("auto_disable_zero_balance", True)
    pool = get_pool()
    client = await pool.get(Route(), connect_timeout=15.0, read_timeout=30.0)

    async with db.session() as session:
        providers = (
            (await session.execute(select(Provider).where(Provider.enabled.is_(True))))
            .scalars()
            .all()
        )
        for provider in providers:
            adapter = get_adapter(provider)
            if adapter.balance_url is None:
                continue
            keys = (
                (
                    await session.execute(
                        select(ApiKey).where(
                            ApiKey.provider_id == provider.id,
                            ApiKey.status == KeyStatus.ACTIVE.value,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for key in keys:
                plaintext = decrypt_secret(key.key_ciphertext, secret=settings.server.secret_key)
                try:
                    result = await adapter.fetch_balance(client, plaintext)
                except Exception as exc:
                    log.debug("balance_probe_error", key_id=key.id, error=str(exc))
                    continue
                if result is None:
                    continue
                is_available, detail = result
                key.balance = detail
                key.last_checked_at = dt.datetime.now(dt.UTC)
                if not is_available and auto_disable:
                    if detail.get("error") == "authentication_error":
                        key.status = KeyStatus.INVALID.value
                        key.disabled_reason = "balance probe: authentication failed"
                    else:
                        key.status = KeyStatus.INSUFFICIENT_BALANCE.value
                        key.disabled_reason = "balance probe: insufficient balance"
                    log.info("key_disabled_by_balance_probe", key_id=key.id)
