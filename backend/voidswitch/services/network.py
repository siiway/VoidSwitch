"""Outbound HTTP client factory with HTTP/SOCKS proxy and local-IP routing.

Clients are pooled per (proxy, local_address, timeout) tuple so connection reuse
survives across requests — critical for sustained coding-agent traffic.
"""

from __future__ import annotations

import asyncio
import contextvars
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from voidswitch.core.logging import get_logger

log = get_logger("network")


def _build_limits() -> httpx.Limits:
    from voidswitch.services.settings_store import get_int

    max_conns = get_int("max_connections", 400)
    max_keep = get_int("max_keepalive_connections", 150)
    return httpx.Limits(max_connections=max_conns, max_keepalive_connections=max_keep)


@dataclass(frozen=True, slots=True)
class Route:
    """An outbound network route: an optional proxy + optional source IP.

    ``agent_node_id`` is set for voidswitch-agent nodes so a custom relay
    transport can pick the shared agent connection (used once the agent lands).
    """

    proxy_url: str | None = None
    local_address: str | None = None
    agent_node_id: int | None = None

    @property
    def is_direct(self) -> bool:
        return not self.proxy_url and not self.local_address and not self.agent_node_id


@dataclass(frozen=True, slots=True)
class NetworkTarget:
    """Logical egress target resolved by the network executor."""

    scope: Literal["provider", "system", "explicit"]
    provider: Any | None = None
    routes: tuple[tuple[Route, Any | None], ...] = ()

    @classmethod
    def for_provider(cls, provider: Any) -> NetworkTarget:
        return cls("provider", provider=provider)

    @classmethod
    def system(cls) -> NetworkTarget:
        return cls("system")

    @classmethod
    def explicit(cls, routes: list[tuple[Route, Any | None]]) -> NetworkTarget:
        return cls("explicit", routes=tuple(routes))


@dataclass(frozen=True, slots=True)
class Deadline:
    """One wall-clock deadline shared by every layer of an outbound operation."""

    started_at: float
    expires_at: float | None

    @classmethod
    def after(cls, seconds: float) -> Deadline:
        now = time.monotonic()
        return cls(now, now + seconds if seconds > 0 else None)

    def remaining(self) -> float | None:
        if self.expires_at is None:
            return None
        return max(0.0, self.expires_at - time.monotonic())


_deadline: contextvars.ContextVar[Deadline | None] = contextvars.ContextVar(
    "voidswitch_network_deadline", default=None
)


def current_deadline() -> Deadline | None:
    return _deadline.get()


def set_current_deadline(deadline: Deadline | None) -> contextvars.Token[Deadline | None]:
    return _deadline.set(deadline)


def reset_current_deadline(token: contextvars.Token[Deadline | None]) -> None:
    _deadline.reset(token)


@dataclass(slots=True)
class NetworkAttempt:
    attempt: int
    route: Route
    node: Any | None
    duration_ms: float
    error: str | None = None
    pool_timeout: bool = False
    status_code: int | None = None
    deadline_timeout: bool = False


@dataclass(slots=True)
class OwnedResponse:
    """Open response returned by the network layer with explicit ownership."""

    response: httpx.Response
    route: Route
    node: Any | None
    started_at: float
    headers_at: float
    attempts: list[NetworkAttempt]

    async def aclose(self) -> None:
        close = asyncio.create_task(self.response.aclose())
        try:
            await asyncio.shield(close)
        except asyncio.CancelledError:
            await close
            raise


async def read_response_body(response: httpx.Response, deadline: Deadline | None = None) -> bytes:
    """Read a response body without outliving the operation's shared deadline."""
    effective_deadline = deadline or current_deadline()
    remaining = effective_deadline.remaining() if effective_deadline else None
    if remaining is not None:
        if remaining <= 0:
            raise TimeoutError("overall response deadline exceeded while reading body")
        return await asyncio.wait_for(response.aread(), remaining)
    return await response.aread()


class NetworkExhausted(Exception):
    def __init__(self, attempts: list[NetworkAttempt]) -> None:
        self.attempts = attempts
        detail = attempts[-1].error if attempts else "no outbound route available"
        super().__init__(detail)


def _route_key(route: Route) -> tuple[str | None, str | None, int | None]:
    return route.proxy_url, route.local_address, route.agent_node_id


async def resolve_target(
    target: NetworkTarget, session: Any | None
) -> list[tuple[Route, Any | None]]:
    """Resolve configuration, node groups, filtering, and ranking at the I/O boundary."""
    from voidswitch.services import routing, settings_store
    from voidswitch.services.selector import static_routes

    if target.scope == "explicit":
        return list(target.routes) or [(Route(), None)]
    if not settings_store.get_bool("proxy_switching_enabled", True):
        return static_routes(settings_store.get_str("static_proxy_url", ""))
    if session is None:
        return [(Route(), None)]
    if target.scope == "system":
        return await routing.system_routes(session)
    group = await routing.provider_routes(session, target.provider)
    return await routing.group_routes(session, group)


async def execute_request(
    *,
    target: NetworkTarget,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    json_body: Any = None,
    data: Any = None,
    connect_timeout: float = 15.0,
    read_timeout: float = 300.0,
    max_attempts: int | None = None,
    deadline: Deadline | None = None,
    session: Any | None = None,
    auto_disable_nodes: bool = True,
    retry_response: Callable[[httpx.Response], bool] | None = None,
) -> OwnedResponse:
    """Open a request and retry only failures that occur before HTTP headers.

    Every request is opened in streaming mode. Receiving any valid HTTP status is
    a connectivity success and transfers response ownership to the caller.
    """
    from voidswitch.services import node_health, routing, settings_store

    routes = await resolve_target(target, session)
    limit = max(1, max_attempts or settings_store.get_int("network_max_attempts", 3))
    selected: list[tuple[Route, Any | None]] = []
    seen: set[tuple[str | None, str | None, int | None]] = set()
    for candidate in routes or [(Route(), None)]:
        key = _route_key(candidate[0])
        if key not in seen:
            seen.add(key)
            selected.append(candidate)
        if len(selected) >= limit:
            break

    trace: list[NetworkAttempt] = []
    last_http: tuple[int, httpx.Headers, bytes, Route, Any | None, httpx.Request] | None = None
    operation_started = time.monotonic()
    effective_deadline = deadline or current_deadline()
    for index, (route, node) in enumerate(selected, 1):
        started = time.monotonic()
        owned: OwnedResponse | None = None
        try:
            remaining = effective_deadline.remaining() if effective_deadline else None
            if remaining is not None and remaining <= 0:
                raise TimeoutError("overall response deadline exceeded")
            client = await get_pool().get(
                route, connect_timeout=connect_timeout, read_timeout=read_timeout
            )
            request = client.build_request(method, url, headers=headers, json=json_body, data=data)
            send = client.send(request, stream=True)
            response = (
                await asyncio.wait_for(send, remaining) if remaining is not None else await send
            )
            elapsed = round((time.monotonic() - started) * 1000.0, 1)
            trace.append(
                NetworkAttempt(index, route, node, elapsed, status_code=response.status_code)
            )
            if node is not None:
                routing.reward_node(node)
                routing.update_node_latency(node, elapsed)
                if session is not None:
                    node_health.add_sample(
                        session,
                        node,
                        success=True,
                        latency_ms=elapsed,
                        source="request",
                        status_code=response.status_code,
                    )
            owned = OwnedResponse(
                response=response,
                route=route,
                node=node,
                started_at=operation_started,
                headers_at=time.monotonic(),
                attempts=trace,
            )
            if retry_response is None:
                transferred = owned
                owned = None
                return transferred
            await read_response_body(response, effective_deadline)
            if not retry_response(response):
                transferred = owned
                owned = None
                return transferred
            last_http = (
                response.status_code,
                response.headers,
                response.content,
                route,
                node,
                response.request,
            )
        except asyncio.CancelledError:
            raise
        except httpx.PoolTimeout as exc:
            elapsed = round((time.monotonic() - started) * 1000.0, 1)
            trace.append(NetworkAttempt(index, route, node, elapsed, str(exc), pool_timeout=True))
            # A saturated local pool is not a route fault, so rotating nodes only
            # adds pressure and gives a misleading health signal.
            break
        except TimeoutError:
            elapsed = round((time.monotonic() - started) * 1000.0, 1)
            deadline_expired = bool(
                effective_deadline is not None and effective_deadline.remaining() == 0
            )
            trace.append(
                NetworkAttempt(
                    index,
                    route,
                    node,
                    elapsed,
                    "overall response deadline exceeded" if deadline_expired else "timeout",
                    deadline_timeout=deadline_expired,
                )
            )
            if deadline_expired:
                raise NetworkExhausted(trace) from None
            if node is not None:
                routing.penalize_node(node, "timeout", auto_disable=auto_disable_nodes)
                if session is not None:
                    node_health.add_sample(
                        session,
                        node,
                        success=False,
                        latency_ms=elapsed,
                        source="request",
                        error="timeout",
                    )
        except httpx.HTTPError as exc:
            elapsed = round((time.monotonic() - started) * 1000.0, 1)
            error = f"{type(exc).__name__}: {exc}"
            trace.append(NetworkAttempt(index, route, node, elapsed, error))
            if node is not None:
                routing.penalize_node(node, error, auto_disable=auto_disable_nodes)
                if session is not None:
                    node_health.add_sample(
                        session,
                        node,
                        success=False,
                        latency_ms=elapsed,
                        source="request",
                        error=error,
                    )
        finally:
            # Until an OwnedResponse is explicitly returned above, this layer
            # retains ownership. This covers body-read failures, deadline expiry,
            # cancellation, and exceptions raised by retry_response.
            if owned is not None:
                await owned.aclose()
    if last_http is not None:
        status, response_headers, content, route, node, request = last_http
        return OwnedResponse(
            response=httpx.Response(
                status, headers=response_headers, content=content, request=request
            ),
            route=route,
            node=node,
            started_at=operation_started,
            headers_at=time.monotonic(),
            attempts=trace,
        )
    raise NetworkExhausted(trace)


def _is_socks(url: str) -> bool:
    return url.lower().startswith(("socks4://", "socks5://", "socks5h://", "socks4a://"))


def build_transport(route: Route, *, retries: int = 0) -> httpx.AsyncBaseTransport:
    """Construct an async transport implementing the requested route."""
    limits = _build_limits()
    if route.proxy_url and _is_socks(route.proxy_url):
        # SOCKS proxying via httpx-socks. local_address is applied when supported.
        from httpx_socks import AsyncProxyTransport

        kwargs: dict[str, object] = {"limits": limits, "retries": retries}
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
        limits=limits,
        retries=retries,
        http2=False,
    )


class ClientPool:
    """Caches AsyncClients keyed by route + timeout profile."""

    def __init__(self) -> None:
        self._clients: dict[
            tuple[str | None, str | None, int | None, float, float], httpx.AsyncClient
        ] = {}
        self._lock = asyncio.Lock()

    async def get(
        self,
        route: Route,
        *,
        connect_timeout: float = 15.0,
        read_timeout: float = 300.0,
    ) -> httpx.AsyncClient:
        key = (
            route.proxy_url,
            route.local_address,
            route.agent_node_id,
            connect_timeout,
            read_timeout,
        )
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
            limits = _build_limits()
            client = httpx.AsyncClient(
                transport=build_transport(route),
                timeout=timeout,
                follow_redirects=False,
                limits=limits,
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

    Returns ``(ok, latency_ms, status_code, error)``. Reuses the shared client
    pool so TLS connections are kept alive across probes.
    """
    loop = asyncio.get_event_loop()
    start = loop.time()
    try:
        # Reuse the shared pool's keep-alive client for this (route, timeout)
        # profile instead of building — and tearing down — a fresh client (and TLS
        # session) on every probe. Health checks fire on a periodic loop, so this
        # keeps their connections warm alongside the gateway's own traffic.
        client = await get_pool().get(
            route, connect_timeout=timeout_seconds, read_timeout=timeout_seconds
        )
        resp = await client.get(url, headers=headers or {})
        latency = (loop.time() - start) * 1000.0
        # Any HTTP response (even 401/403) proves the route reaches upstream.
        return True, latency, resp.status_code, None
    except Exception as exc:
        latency = (loop.time() - start) * 1000.0
        return False, latency, None, f"{type(exc).__name__}: {exc}"
