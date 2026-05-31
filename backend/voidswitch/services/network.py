"""Outbound HTTP client factory with HTTP/SOCKS proxy and local-IP routing.

Clients are pooled per (proxy, local_address, timeout) tuple so connection reuse
survives across requests — critical for sustained coding-agent traffic.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from voidswitch.core.logging import get_logger

log = get_logger("network")

# Conservative-but-generous pool sizing for a high-throughput gateway.
_LIMITS = httpx.Limits(max_connections=200, max_keepalive_connections=80)


@dataclass(frozen=True, slots=True)
class Route:
    """An outbound network route: an optional proxy + optional source IP."""

    proxy_url: str | None = None
    local_address: str | None = None

    @property
    def is_direct(self) -> bool:
        return not self.proxy_url and not self.local_address


def _is_socks(url: str) -> bool:
    return url.lower().startswith(("socks4://", "socks5://", "socks5h://", "socks4a://"))


def build_transport(route: Route, *, retries: int = 0) -> httpx.AsyncBaseTransport:
    """Construct an async transport implementing the requested route."""
    if route.proxy_url and _is_socks(route.proxy_url):
        # SOCKS proxying via httpx-socks. local_address is applied when supported.
        from httpx_socks import AsyncProxyTransport

        kwargs: dict[str, object] = {"limits": _LIMITS, "retries": retries}
        if route.local_address:
            kwargs["local_address"] = (route.local_address, 0)
        try:
            return AsyncProxyTransport.from_url(route.proxy_url, **kwargs)
        except TypeError:
            # Older httpx-socks without local_address support.
            kwargs.pop("local_address", None)
            return AsyncProxyTransport.from_url(route.proxy_url, **kwargs)

    proxy = httpx.Proxy(route.proxy_url) if route.proxy_url else None
    return httpx.AsyncHTTPTransport(
        proxy=proxy,
        local_address=route.local_address,
        limits=_LIMITS,
        retries=retries,
        http2=False,
    )


class ClientPool:
    """Caches AsyncClients keyed by route + timeout profile."""

    def __init__(self) -> None:
        self._clients: dict[tuple[str | None, str | None, float, float], httpx.AsyncClient] = {}
        self._lock = asyncio.Lock()

    async def get(
        self,
        route: Route,
        *,
        connect_timeout: float = 15.0,
        read_timeout: float = 300.0,
    ) -> httpx.AsyncClient:
        key = (route.proxy_url, route.local_address, connect_timeout, read_timeout)
        client = self._clients.get(key)
        if client is not None and not client.is_closed:
            return client
        async with self._lock:
            client = self._clients.get(key)
            if client is not None and not client.is_closed:
                return client
            timeout = httpx.Timeout(
                connect=connect_timeout,
                read=read_timeout,
                write=read_timeout,
                pool=connect_timeout,
            )
            client = httpx.AsyncClient(
                transport=build_transport(route),
                timeout=timeout,
                follow_redirects=False,
                limits=_LIMITS,
            )
            self._clients[key] = client
            log.debug(
                "created_client",
                proxy=route.proxy_url,
                local_address=route.local_address,
            )
            return client

    async def aclose(self) -> None:
        async with self._lock:
            for client in self._clients.values():
                await client.aclose()
            self._clients.clear()


# Process-wide pool.
_pool = ClientPool()


def get_pool() -> ClientPool:
    return _pool


async def probe_route(
    route: Route,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout_seconds: float = 10.0,
) -> tuple[bool, float, int | None, str | None]:
    """Lightweight GET used by the proxy resurrector / health checks.

    Returns ``(ok, latency_ms, status_code, error)``.
    """
    loop = asyncio.get_event_loop()
    start = loop.time()
    try:
        async with httpx.AsyncClient(
            transport=build_transport(route),
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
        ) as client:
            resp = await client.get(url, headers=headers or {})
        latency = (loop.time() - start) * 1000.0
        # Any HTTP response (even 401/403) proves the route reaches upstream.
        return True, latency, resp.status_code, None
    except Exception as exc:
        latency = (loop.time() - start) * 1000.0
        return False, latency, None, f"{type(exc).__name__}: {exc}"
