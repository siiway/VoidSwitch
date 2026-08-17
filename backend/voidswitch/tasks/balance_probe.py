"""Background balance probe.

Periodically queries each provider's balance endpoint (where supported) for its
active keys and fast-fails keys that report no balance.
"""

from __future__ import annotations

from sqlalchemy import select

from voidswitch.constants import KeyStatus
from voidswitch.core.config import get_settings
from voidswitch.core.database import get_database
from voidswitch.core.logging import get_logger
from voidswitch.models.db import ApiKey, Provider
from voidswitch.services import routing, settings_store
from voidswitch.services.balance import refresh_key_balance
from voidswitch.services.network import get_pool
from voidswitch.services.providers.registry import get_adapter

log = get_logger("tasks.balance")


async def run_balance_probe() -> None:
    db = get_database()
    settings = get_settings()
    auto_disable = settings_store.get_bool("auto_disable_zero_balance", True)
    pool = get_pool()

    async with db.session() as session:
        # System request → System node group (empty group degrades to direct).
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
                            ApiKey.status == KeyStatus.ACTIVE.value,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for key in keys:
                try:
                    is_available = await refresh_key_balance(
                        key,
                        provider,
                        client,
                        settings,
                        auto_disable=auto_disable,
                        adapter=adapter,
                    )
                except Exception as exc:
                    log.debug("balance_probe_error", key_id=key.id, error=str(exc))
                    continue
                if is_available is False and key.status != KeyStatus.ACTIVE.value:
                    log.info("key_disabled_by_balance_probe", key_id=key.id)
