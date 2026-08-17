"""Slow background rescan of balance-disabled keys.

Keys parked in the ``insufficient_balance`` state are re-checked on a slow cadence
(default once per day, tunable) and automatically re-enabled if they report a
balance again. Keys disabled for other reasons (e.g. ``invalid``) are left alone.
"""

from __future__ import annotations

from sqlalchemy import select

from voidswitch.constants import KeyStatus
from voidswitch.core.config import get_settings
from voidswitch.core.database import get_database
from voidswitch.core.logging import get_logger
from voidswitch.models.db import ApiKey, Provider
from voidswitch.services import routing
from voidswitch.services.balance import refresh_key_balance
from voidswitch.services.network import get_pool
from voidswitch.services.providers.registry import get_adapter

log = get_logger("tasks.balance_rescan")


async def run_balance_rescan() -> None:
    db = get_database()
    settings = get_settings()
    pool = get_pool()

    async with db.session() as session:
        routes = await routing.system_routes(session)
        route, _node = routes[0]
        client = await pool.get(route, connect_timeout=15.0, read_timeout=30.0)

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
                            ApiKey.status == KeyStatus.INSUFFICIENT_BALANCE.value,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for key in keys:
                try:
                    # auto_disable keeps empty keys parked; an available balance
                    # re-enables the key inside apply_balance().
                    is_available = await refresh_key_balance(
                        key,
                        provider,
                        client,
                        settings,
                        auto_disable=True,
                        adapter=adapter,
                    )
                except Exception as exc:
                    log.debug("balance_rescan_error", key_id=key.id, error=str(exc))
                    continue
                if is_available and key.status == KeyStatus.ACTIVE.value:
                    log.info("key_reenabled_by_balance_rescan", key_id=key.id)
