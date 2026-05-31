"""Background proxy resurrector.

Periodically probes ``disabled`` proxies with a lightweight GET. If a probe
succeeds (any HTTP response proves reachability), the proxy is re-enabled.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from voidswitch.constants import ProxyStatus
from voidswitch.core.database import get_database
from voidswitch.core.logging import get_logger
from voidswitch.models.db import Proxy
from voidswitch.services import settings_store
from voidswitch.services.network import Route, probe_route

log = get_logger("tasks.resurrector")


async def run_proxy_resurrector() -> None:
    db = get_database()
    probe_url = settings_store.get_cached("proxy_probe_url", "https://api.openai.com/v1/models")

    async with db.session() as session:
        proxies = (
            (
                await session.execute(
                    select(Proxy).where(
                        Proxy.enabled.is_(True),
                        Proxy.status == ProxyStatus.DISABLED.value,
                    )
                )
            )
            .scalars()
            .all()
        )
        for proxy in proxies:
            route = Route(proxy_url=proxy.url or None, local_address=proxy.local_address)
            ok, latency, _status, error = await probe_route(route, probe_url)
            proxy.last_checked_at = dt.datetime.now(dt.UTC)
            proxy.latency_ms = latency
            if ok:
                proxy.status = ProxyStatus.ACTIVE.value
                proxy.failed_count = 0
                proxy.disabled_reason = None
                log.info("proxy_resurrected", proxy_id=proxy.id, latency_ms=round(latency))
            else:
                proxy.disabled_reason = error
